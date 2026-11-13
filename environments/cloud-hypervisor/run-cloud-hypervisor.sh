#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"
source "$CH_DIR/ssh.sh"
if [[ -n ${CH_ARGS_BASE64:-} ]]; then
    mapfile -d '' -t transported < <(python3 - <<'PY'
import base64, json, os, sys
args = json.loads(base64.b64decode(os.environ['CH_ARGS_BASE64']))
sys.stdout.buffer.write(b''.join(a.encode() + b'\0' for a in args))
PY
    )
    (( ${#transported[@]} > 0 )) || { echo 'Invalid remote command.' >&2; exit 1; }
    set -- "${transported[@]}"
    unset CH_ARGS_BASE64
fi
COMMAND=${1:-run}; shift || true
log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || fail 'Requires Linux ARM64; use dev.sh from macOS.'
[[ $EUID == 0 ]] || fail 'Run as root on Linux.'
python3 "$CH_DIR/guest.py" validate
mkdir -p "$WORKDIR" "$CH_DIR/bin"
chmod 700 "$WORKDIR"

setup() {
    command -v apt-get >/dev/null || fail 'setup currently supports Ubuntu/Debian Hosts.'
    local packages=(ca-certificates curl python3 build-essential git pkg-config gdb file
        libssl-dev m4 bison flex uuid-dev e2fsprogs iproute2 iptables util-linux openssh-client)
    local missing=() package
    for package in "${packages[@]}"; do
        [[ $(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true) == installed ]] || missing+=("$package")
    done
    if (( ${#missing[@]} )); then
        export DEBIAN_FRONTEND=noninteractive
        apt-get -o Acquire::Retries=3 update
        apt-get -o Acquire::Retries=3 install -y --no-install-recommends "${missing[@]}"
    fi
}

doctor() {
    log "Host=$(uname -sm); source=$CH_SOURCE; work=$WORKDIR; mode=$GUEST_MODE"
    python3 - <<'PY'
import fcntl, os
fd = os.open('/dev/kvm', os.O_RDWR)
try:
    assert fcntl.ioctl(fd, 0xAE00, 0) == 12, 'Unsupported KVM API version'
    os.close(fcntl.ioctl(fd, 0xAE01, 0))
finally:
    os.close(fd)
print('OK KVM_CREATE_VM (nested virtualization available)')
PY
    local errors=0 tool
    for tool in gdb curl debugfs e2fsck flock ip iptables ssh ssh-keygen; do
        command -v "$tool" >/dev/null || { log "MISSING $tool (run setup)"; errors=1; }
    done
    [[ -c /dev/net/tun ]] || { log 'MISSING /dev/net/tun'; errors=1; }
    [[ -f "$CH_SOURCE/vmm/src/lib.rs" ]] || { log 'MISSING CH source (run bind)'; errors=1; }
    [[ -x "$CH_BIN" ]] && file "$CH_BIN" || log 'Build the debug binary with dev.sh build.'
    [[ -s "$BASE_ROOTFS" ]] || { log 'MISSING BASE_ROOTFS; set an Ubuntu/systemd raw ext4 filesystem.'; errors=1; }
    [[ ! -f "$KERNEL" ]] || python3 "$CH_DIR/guest.py" kernel
    return "$errors"
}

build_ch() {
    [[ -f "$CH_SOURCE/Cargo.toml" && -f "$CH_SOURCE/vmm/src/lib.rs" ]] || fail 'Bind a Cloud Hypervisor checkout first.'
    exec 9> "$WORKDIR/run.lock"
    flock -n 9 || fail 'Stop this environment before replacing its debug binary.'
    export RUSTUP_HOME=$TOOLS_DIR/rustup CARGO_HOME=$TOOLS_DIR/cargo
    export PATH="$CARGO_HOME/bin:$PATH"
    mkdir -p "$TOOLS_DIR"
    if [[ ! -x "$CARGO_HOME/bin/rustup" ]]; then
        curl --fail --location --retry 3 --proto '=https' --tlsv1.2 https://sh.rustup.rs -o "$TOOLS_DIR/rustup-init.sh"
        sh "$TOOLS_DIR/rustup-init.sh" -y --no-modify-path --profile minimal --default-toolchain none
    fi
    if ! rustup run "$CH_RUST_VERSION" rustc --version >/dev/null 2>&1; then
        rustup toolchain install "$CH_RUST_VERSION" --profile minimal
    fi
    export CARGO_PROFILE_DEV_DEBUG=2 CARGO_PROFILE_DEV_OPT_LEVEL=0 CARGO_PROFILE_DEV_STRIP=none
    export CARGO_BUILD_JOBS=$JOBS
    log "Building CH with $CH_RUST_VERSION, native GNU, full symbols and guest_debug"
    (
        cd "$CH_SOURCE"
        rustup run "$CH_RUST_VERSION" cargo build --locked -p cloud-hypervisor --bin cloud-hypervisor \
            --features guest_debug --target aarch64-unknown-linux-gnu --target-dir "$WORKDIR/target"
    )
    mkdir -p "$(dirname "$CH_BIN")"
    cp "$WORKDIR/target/aarch64-unknown-linux-gnu/debug/cloud-hypervisor" "$CH_BIN.part"
    chmod +x "$CH_BIN.part"
    mv "$CH_BIN.part" "$CH_BIN"
    git -C "$CH_SOURCE" rev-parse HEAD > "$CH_BIN.commit"
    file "$CH_BIN"
}

prepare() {
    [[ -x "$CH_BIN" ]] || fail 'Run dev.sh build first.'
    [[ -s "$BASE_ROOTFS" ]] || fail 'Set BASE_ROOTFS to an Ubuntu/systemd raw ext4 filesystem (see README).'
    # This is deliberately a CH kernel; FC kernels often omit PCI/PL011 drivers.
    python3 "$CH_DIR/guest.py" kernel
    [[ "$GUEST_MODE" != ssh ]] || ensure_ssh_keys
    local fingerprint old=
    fingerprint=$({
        sha256sum "$BASE_ROOTFS" "$CH_DIR/inject-rootfs.sh"
        [[ "$GUEST_MODE" != ssh ]] || sha256sum "$SSH_IDENTITY.pub" "$SSH_HOST_KEY"
        printf '%s\n' "$GUEST_MODE" "$GUEST_IP" "$HOST_IP" "$PREFIX" "$GUEST_MAC" \
            "$DNS_SERVER" "$DNS_SECONDARY" "$ENABLE_NETWORK" "$SSH_PORT"
    } | sha256sum | cut -d ' ' -f1)
    [[ ! -f "$PREPARED_ROOTFS.sha256" ]] || old=$(cat "$PREPARED_ROOTFS.sha256")
    if [[ ! -s "$PREPARED_ROOTFS" || "$old" != "$fingerprint" ]]; then
        bash "$CH_DIR/inject-rootfs.sh" "$BASE_ROOTFS" "$PREPARED_ROOTFS"
        printf '%s\n' "$fingerprint" > "$PREPARED_ROOTFS.sha256"
    fi
    cp --reflink=auto --sparse=always "$PREPARED_ROOTFS" "$RUN_ROOTFS.part"
    mv "$RUN_ROOTFS.part" "$RUN_ROOTFS"
    python3 "$CH_DIR/guest.py" args
    log "Prepared $WORKDIR/args.json; fresh run disk=$RUN_ROOTFS"
}

network_up() {
    [[ "$ENABLE_NETWORK" == 1 ]] || return 0
    ip link show "$TAP_DEV" >/dev/null 2>&1 && fail "TAP already exists: $TAP_DEV"
    ip tuntap add dev "$TAP_DEV" mode tap
    TAP_CREATED=1
    ip addr add "$HOST_IP/$PREFIX" dev "$TAP_DEV"
    ip link set "$TAP_DEV" up
    [[ "$ENABLE_NAT" == 1 ]] || return 0
    if [[ -z "$UPLINK_IF" ]]; then
        UPLINK_IF=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="dev") {print $(i+1); exit}}')
    fi
    [[ -n "$UPLINK_IF" && "$UPLINK_IF" != "$TAP_DEV" ]] || fail 'Cannot determine uplink; set UPLINK_IF.'
    sysctl -w net.ipv4.ip_forward=1
    iptables -I FORWARD 1 -i "$TAP_DEV" -o "$UPLINK_IF" -s "$GUEST_IP/32" -m comment --comment ch-debug-config -j ACCEPT
    FORWARD_OUT=1
    iptables -I FORWARD 1 -i "$UPLINK_IF" -o "$TAP_DEV" -d "$GUEST_IP/32" -m conntrack \
        --ctstate ESTABLISHED,RELATED -m comment --comment ch-debug-config -j ACCEPT
    FORWARD_IN=1
    iptables -t nat -A POSTROUTING -s "$GUEST_IP/32" -o "$UPLINK_IF" -m comment --comment ch-debug-config -j MASQUERADE
    NAT_CREATED=1
}

managed_pid() {
    [[ -f "$WORKDIR/cloud-hypervisor.pid" ]] || fail 'No managed CH PID. Stop the active GDB session if it is paused at entry.'
    local pid
    pid=$(cat "$WORKDIR/cloud-hypervisor.pid")
    [[ "$pid" =~ ^[1-9][0-9]*$ && -r /proc/$pid/cmdline ]] || fail 'Stale PID file.'
    python3 - "$pid" "$API_SOCKET" <<'PY'
from pathlib import Path
import sys
args = Path('/proc', sys.argv[1], 'cmdline').read_bytes().split(b'\0')
assert sys.argv[2].encode() in args, 'PID belongs to another process; refusing to stop it'
PY
    printf '%s\n' "$pid"
}

stop_vm() {
    local pid
    pid=$(managed_pid)
    kill -TERM "$pid"
}

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if [[ -n ${CH_PID:-} ]] && kill -0 "$CH_PID" 2>/dev/null; then
        kill "$CH_PID" 2>/dev/null || true
        wait "$CH_PID" 2>/dev/null || true
    fi
    if [[ -n ${CONSOLE_PID:-} ]]; then
        kill "$CONSOLE_PID" 2>/dev/null || true
        wait "$CONSOLE_PID" 2>/dev/null || true
    fi
    if [[ ${NAT_CREATED:-0} == 1 ]]; then
        iptables -t nat -D POSTROUTING -s "$GUEST_IP/32" -o "$UPLINK_IF" -m comment --comment ch-debug-config -j MASQUERADE || true
    fi
    if [[ ${FORWARD_IN:-0} == 1 ]]; then
        iptables -D FORWARD -i "$UPLINK_IF" -o "$TAP_DEV" -d "$GUEST_IP/32" -m conntrack \
            --ctstate ESTABLISHED,RELATED -m comment --comment ch-debug-config -j ACCEPT || true
    fi
    if [[ ${FORWARD_OUT:-0} == 1 ]]; then
        iptables -D FORWARD -i "$TAP_DEV" -o "$UPLINK_IF" -s "$GUEST_IP/32" -m comment --comment ch-debug-config -j ACCEPT || true
    fi
    [[ ${TAP_CREATED:-0} != 1 ]] || ip link del "$TAP_DEV" || true
    rm -f "$API_SOCKET" "$GDB_SOCKET" "$CONSOLE_SOCKET" "$CONSOLE_TTY_FILE" \
        "$WORKDIR/cloud-hypervisor.pid" "$WORKDIR/session.json"
    if [[ $status != 0 && -f "$WORKDIR/console.log" ]]; then tail -40 "$WORKDIR/console.log" >&2; fi
    exit "$status"
}

start_console() {
    # Stateless PTY/socket bridge shared with the FC environment.
    python3 "$CH_DIR/../fc/console.py" serve "$CONSOLE_SOCKET" --tty-file "$CONSOLE_TTY_FILE" \
        --log "$WORKDIR/console.log" > "$WORKDIR/console-bridge.log" 2>&1 &
    CONSOLE_PID=$!
    local attempt
    for ((attempt=0; attempt<100; attempt++)); do
        if [[ -s "$CONSOLE_TTY_FILE" && -S "$CONSOLE_SOCKET" ]]; then
            CONSOLE_TTY=$(cat "$CONSOLE_TTY_FILE")
            [[ -c "$CONSOLE_TTY" ]] || fail 'Invalid console PTY.'
            return
        fi
        kill -0 "$CONSOLE_PID" 2>/dev/null || fail "Console bridge failed; inspect $WORKDIR/console-bridge.log"
        sleep 0.05
    done
    fail 'Console bridge did not become ready.'
}

load_session() {
    [[ -f "$WORKDIR/session.json" ]] || fail 'No active Guest session.'
    local values=()
    mapfile -d '' -t values < <(python3 - "$WORKDIR/session.json" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
keys = ('mode', 'guest_ip', 'host_ip', 'network', 'nat', 'ssh_port', 'identity', 'known_hosts')
sys.stdout.buffer.write(b''.join(str(data[k]).encode() + b'\0' for k in keys))
PY
    )
    [[ ${#values[@]} == 8 ]] || fail 'Invalid session metadata.'
    GUEST_MODE=${values[0]}; GUEST_IP=${values[1]}; HOST_IP=${values[2]}
    ENABLE_NETWORK=${values[3]}; ENABLE_NAT=${values[4]}; SSH_PORT=${values[5]}
    SSH_IDENTITY=${values[6]}; SSH_KNOWN_HOSTS=${values[7]}
}

check() {
    [[ "$GUEST_MODE" == ssh ]] || fail 'Serial mode: use dev.sh console. exec/check require SSH mode.'
    guest_ssh uname -a
    guest_ssh cat /etc/resolv.conf
    guest_ssh ip route
    guest_ssh ping -c 2 -W 3 "$HOST_IP"
    if [[ "$ENABLE_NAT" == 1 ]]; then
        guest_ssh ping -c 2 -W 3 1.1.1.1
        guest_ssh getent ahostsv4 example.com
    fi
}

run_vm() {
    exec 9> "$WORKDIR/run.lock"
    flock -n 9 || fail 'Another run/prepare/debug owns this WORKDIR.'
    local socket
    for socket in "$API_SOCKET" "$GDB_SOCKET" "$CONSOLE_SOCKET" "$CONSOLE_TTY_FILE"; do
        [[ ! -e "$socket" ]] || fail "Existing socket $socket; verify its owner before removing."
    done
    if [[ "$COMMAND" == debug-mi ]]; then prepare >> "$WORKDIR/launcher.log" 2>&1
    else prepare; fi
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    start_console
    if [[ "$COMMAND" == debug-mi ]]; then network_up >> "$WORKDIR/launcher.log" 2>&1
    else network_up; fi
    python3 - "$WORKDIR/session.json" "$GUEST_MODE" "$GUEST_IP" "$HOST_IP" "$ENABLE_NETWORK" \
        "$ENABLE_NAT" "$SSH_PORT" "$SSH_IDENTITY" "$SSH_KNOWN_HOSTS" <<'PY'
import json, sys
keys = ('mode', 'guest_ip', 'host_ip', 'network', 'nat', 'ssh_port', 'identity', 'known_hosts')
with open(sys.argv[1], 'w') as output:
    json.dump(dict(zip(keys, sys.argv[2:])), output)
PY
    if [[ "$COMMAND" == debug-mi || "$COMMAND" == debug ]]; then
        local wrapper
        wrapper=$(python3 -c 'import shlex,sys; print(shlex.join(["/bin/bash", sys.argv[1]]))' "$CH_DIR/vm-exec.sh")
        if [[ "$COMMAND" == debug-mi ]]; then
            gdb --tty="$CONSOLE_TTY" -iex "set exec-wrapper $wrapper" "$@"
        else
            gdb --tty="$CONSOLE_TTY" -iex "set exec-wrapper $wrapper" -q \
                -ex 'set pagination off' -ex 'handle SIG34 nostop noprint pass' \
                -ex 'set breakpoint pending on' -ex 'break cloud_hypervisor::main' -ex run --args "$CH_BIN"
        fi
        return
    fi
    mapfile -d '' -t args < <(python3 - "$WORKDIR/args.json" <<'PY'
import json, sys
sys.stdout.buffer.write(b''.join(a.encode() + b'\0' for a in json.load(open(sys.argv[1]))))
PY
    )
    "$CH_BIN" "${args[@]}" < "$CONSOLE_TTY" > "$CONSOLE_TTY" 2>&1 &
    CH_PID=$!
    printf '%s\n' "$CH_PID" > "$WORKDIR/cloud-hypervisor.pid"
    log "Cloud Hypervisor PID=$CH_PID; API=$API_SOCKET; console=$WORKDIR/console.log"
    if [[ "$GUEST_DEBUG" == 1 ]]; then
        log 'Guest waits for GDB; use VMLINUX=/matching/vmlinux ./dev.sh guest-gdb'
    elif [[ "$GUEST_MODE" == ssh ]]; then
        local attempt ready=0
        for ((attempt=0; attempt<120; attempt++)); do
            kill -0 "$CH_PID" 2>/dev/null || fail 'CH exited before Guest SSH became ready.'
            if timeout 5 bash -c 'source "$1/ssh.sh"; guest_ssh true' ch-ssh "$CH_DIR" >/dev/null 2>&1; then ready=1; break; fi
            sleep 0.5
        done
        [[ "$ready" == 1 ]] || fail 'Guest SSH timed out; inspect console.log.'
        log 'Guest SSH ready; use dev.sh ssh / exec / check. Ctrl+C stops this VM.'
    else log 'Guest serial started; use dev.sh console (root autologin).'; fi
    local status=0
    wait "$CH_PID" || status=$?
    [[ "$status" == 0 || "$status" == 143 ]] || return "$status"
}

case "$COMMAND" in
    setup) setup ;;
    doctor) doctor ;;
    build) build_ch ;;
    prepare)
        exec 9> "$WORKDIR/run.lock"
        flock -n 9 || fail 'VM is running; refusing to replace its disk.'
        prepare ;;
    run|debug) run_vm "$@" ;;
    debug-mi) run_vm "$@" ;;
    attach)
        [[ $# -ge 1 ]] || fail 'Usage: dev.sh attach PID [GDB arguments]'
        pid=$(managed_pid)
        [[ "$1" == "$pid" ]] || fail 'PID does not match this environment; refusing to attach.'
        shift
        exec gdb -q "$CH_BIN" -ex 'handle SIG34 nostop noprint pass' -p "$pid" "$@" ;;
    guest-debug) export GUEST_DEBUG=1; run_vm ;;
    guest-gdb)
        [[ -s "$VMLINUX" ]] || fail 'Set VMLINUX to the unstripped ELF matching KERNEL.'
        exec gdb -q "$VMLINUX" -ex "target remote $GDB_SOCKET" ;;
    console) exec python3 "$CH_DIR/../fc/console.py" connect "$CONSOLE_SOCKET" ;;
    ssh|exec|check)
        load_session
        [[ "$GUEST_MODE" == ssh ]] || fail 'Use dev.sh console in serial mode; SSH mode is required.'
        if [[ "$COMMAND" == check ]]; then check
        elif [[ "$COMMAND" == exec && $# == 0 ]]; then fail 'Usage: dev.sh exec COMMAND [ARG...]'
        else guest_ssh "$@"; fi ;;
    api)
        [[ $# -ge 2 && "$2" == /api/v1/* ]] || fail 'Usage: dev.sh api METHOD /api/v1/endpoint [JSON]'
        args=(--fail-with-body --silent --show-error --unix-socket "$API_SOCKET" -X "$1" -H 'Content-Type: application/json')
        if [[ $# -gt 2 ]]; then args+=(--data "$3"); fi
        curl "${args[@]}" "http://localhost$2"; printf '\n' ;;
    stop) stop_vm ;;
    *) fail "Unknown command: $COMMAND" ;;
esac
