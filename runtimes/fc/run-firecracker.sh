#!/usr/bin/env bash
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"
source "$FC_DIR/../common/guest/ssh.sh"
if [[ -n ${FC_ARGS_BASE64:-} ]]; then
    mapfile -d '' -t transported < <(python3 -c 'import base64,json,os,sys; args=json.loads(base64.b64decode(os.environ["FC_ARGS_BASE64"])); sys.stdout.buffer.write(b"".join(a.encode()+b"\0" for a in args))')
    set -- "${transported[@]}"
    unset FC_ARGS_BASE64
fi
COMMAND=${1:-run}
shift || true
log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }
trap 'printf "ERROR at line %s (exit %s)\n" "$LINENO" "$?" >&2' ERR
[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || fail 'Requires Linux ARM64; use dev.sh on macOS.'
[[ $EUID == 0 ]] || fail 'Run as root (TAP/NAT/debugging require it).'
[[ "$WORKDIR" == /* && "$WORKDIR" != / && ${#WORKDIR} -lt 80 ]] || fail 'WORKDIR must be an absolute path shorter than 80 characters.'
mkdir -p "$WORKDIR" "$FC_DIR/bin"
chmod 700 "$WORKDIR"

install_deps() {
    if command -v apk >/dev/null; then
        apk --timeout 30 add --no-cache bash ca-certificates curl python3 file coreutils util-linux \
            e2fsprogs e2fsprogs-extra squashfs-tools iproute2 iptables gdb openssh-client \
            rustup build-base linux-headers cmake perl pkgconf git clang-dev libseccomp-dev gperf
    elif command -v apt-get >/dev/null; then
        export DEBIAN_FRONTEND=noninteractive
        local packages=(bash ca-certificates curl python3 file \
            coreutils util-linux e2fsprogs squashfs-tools iproute2 iptables gdb openssh-client \
            build-essential linux-libc-dev cmake perl pkg-config musl-tools git libclang-dev libseccomp-dev gperf)
        local missing=() package
        for package in "${packages[@]}"; do
            if [[ $(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true) != installed ]]; then
                missing+=("$package")
            fi
        done
        if (( ${#missing[@]} )); then
            apt-get -o Acquire::Retries=3 update
            apt-get -o Acquire::Retries=3 install -y --no-install-recommends "${missing[@]}"
        else log 'Ubuntu Host dependencies already installed'; fi
        # Let musl compile dependencies which include Linux UAPI headers.
        local include=/usr/include/aarch64-linux-musl entry
        for entry in asm linux asm-generic; do
            if [[ ! -e "$include/$entry" ]]; then
                if [[ "$entry" == asm ]]; then
                    ln -s ../aarch64-linux-gnu/asm "$include/asm"
                else ln -s "../$entry" "$include/$entry"; fi
            fi
        done
    else fail 'Supported Hosts: Alpine Linux and Ubuntu Linux.'; fi
}

doctor() {
    local errors=0 tool
    log "Host: $(uname -srmo)"
    if [[ -c /dev/kvm && -r /dev/kvm && -w /dev/kvm ]]; then
        log 'OK /dev/kvm'
        python3 - <<'PY'
import fcntl, os
fd = os.open('/dev/kvm', os.O_RDWR)
assert fcntl.ioctl(fd, 0xAE00, 0) == 12, 'Unsupported KVM API version'
vm = fcntl.ioctl(fd, 0xAE01, 0)
os.close(vm)
os.close(fd)
print('OK KVM_CREATE_VM (nested virtualization works)')
PY
    else log 'MISSING usable /dev/kvm'; errors=1; fi
    [[ -c /dev/net/tun ]] || { log 'MISSING /dev/net/tun'; errors=1; }
    for tool in curl python3 debugfs mke2fs e2fsck unsquashfs ip iptables flock gdb; do
        command -v "$tool" >/dev/null || { log "MISSING $tool (run setup)"; errors=1; }
    done
    local binaries=("$FC_BIN")
    if [[ "$GUEST_MODE" == liquidmetal ]]; then binaries+=("$AGENT_BIN" "$VSOCK_CONNECT"); fi
    if [[ "$GUEST_MODE" == ssh ]]; then
        for tool in ssh ssh-keygen; do command -v "$tool" >/dev/null || { log "MISSING $tool (run setup)"; errors=1; }; done
    fi
    for tool in "${binaries[@]}"; do
        if [[ -x "$tool" ]]; then file "$tool"; else log "MISSING $tool"; fi
    done
    log "Guest mode: $GUEST_MODE; sources: $FC_SOURCE"
    log "Artifacts: $WORKDIR; reuse: $EXISTING_LAB"
    return "$errors"
}

setup() {
    install_deps
    local name source
    for name in guest-agent vsock-connect; do
        source=$EXISTING_LAB/$name
        if [[ ! -s "$FC_DIR/bin/$name" && -s "$source" ]]; then
            cp "$source" "$FC_DIR/bin/$name"
            chmod +x "$FC_DIR/bin/$name"
        fi
    done
    if [[ ! -s "$FC_DIR/bin/firecracker-release" && -x "$EXISTING_LAB/firecracker" ]]; then
        cp "$EXISTING_LAB/firecracker" "$FC_DIR/bin/firecracker-release"
    fi
    doctor
}

ensure_seccomp() {
    # Current Firecracker uses seccomp_export_bpf_mem, absent in Ubuntu's 2.5.x.
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
    if pkg-config --atleast-version=2.6.1 libseccomp; then return; fi
    local archive=$WORKDIR/libseccomp-2.6.1.tar.gz
    if [[ ! -s "$archive" ]]; then
        curl --fail --location --retry 3 --max-time 120 \
            https://github.com/seccomp/libseccomp/releases/download/v2.6.1/libseccomp-2.6.1.tar.gz \
            -o "$archive.part"
        mv "$archive.part" "$archive"
    fi
    printf '501f66c667225d53791b97e1d7cf85ab764c297d04881f60f38f451c4b0ee1be  %s\n' "$archive" | sha256sum -c -
    tar -xzf "$archive" -C "$WORKDIR"
    (
        cd "$WORKDIR/libseccomp-2.6.1"
        ./configure --prefix=/usr/local --enable-static --disable-shared --disable-python
        make -j4
        make install
    ) > "$WORKDIR/libseccomp-build.log" 2>&1 || {
        tail -50 "$WORKDIR/libseccomp-build.log" >&2; return 1;
    }
    log 'Built libseccomp 2.6.1 for the native Rust build scripts'
}

build_fc() {
    [[ -f "$FC_SOURCE/Cargo.toml" ]] || fail "Missing Firecracker source: $FC_SOURCE"
    ensure_seccomp
    export RUSTUP_HOME=$WORKDIR/rustup CARGO_HOME=$WORKDIR/cargo
    export PATH="$CARGO_HOME/bin:$PATH"
    if ! command -v rustup >/dev/null; then
        curl --fail --location --proto '=https' --tlsv1.2 \
            https://sh.rustup.rs -o "$WORKDIR/rustup-init.sh"
        sh "$WORKDIR/rustup-init.sh" -y --no-modify-path --profile minimal --default-toolchain none
    fi
    local channel target=aarch64-unknown-linux-musl
    channel=$(python3 -c 'import tomllib,sys; print(tomllib.load(open(sys.argv[1], "rb"))["toolchain"]["channel"])' "$FC_SOURCE/rust-toolchain.toml")
    rustup toolchain install "$channel" --profile minimal --target "$target"
    export CARGO_PROFILE_DEV_DEBUG=2 CARGO_PROFILE_DEV_OPT_LEVEL=0 CARGO_PROFILE_DEV_STRIP=none
    export CARGO_BUILD_JOBS=${JOBS:-4}
    if command -v musl-gcc >/dev/null; then
        export CC_aarch64_unknown_linux_musl=musl-gcc
        export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER=musl-gcc
        local include=/usr/include/aarch64-linux-musl entry
        for entry in asm linux asm-generic; do
            if [[ ! -e "$include/$entry" ]]; then
                if [[ "$entry" == asm ]]; then ln -s ../aarch64-linux-gnu/asm "$include/asm"
                else ln -s "../$entry" "$include/$entry"; fi
            fi
        done
    fi
    log "Building Firecracker ($channel, $target, debug symbols, guest GDB support)"
    (
        cd "$FC_SOURCE"
        rustup run "$channel" cargo build --locked -p firecracker --features gdb \
            --target "$target" --target-dir "$WORKDIR/target"
    )
    cp "$WORKDIR/target/$target/debug/firecracker" "$FC_DIR/bin/firecracker-debug.part"
    chmod +x "$FC_DIR/bin/firecracker-debug.part"
    mv "$FC_DIR/bin/firecracker-debug.part" "$FC_DIR/bin/firecracker-debug"
    git -C "$FC_SOURCE" rev-parse HEAD > "$FC_DIR/bin/firecracker-debug.commit"
    file "$FC_DIR/bin/firecracker-debug"
}

validate() {
    [[ "$GUEST_MODE" != ssh || "$ENABLE_NETWORK" == 1 ]] || fail 'SSH mode requires ENABLE_NETWORK=1.'
    [[ "$SSH_PORT" =~ ^[0-9]+$ && "$SSH_PORT" -ge 1 && "$SSH_PORT" -le 65535 ]] || fail 'Invalid SSH_PORT.'
    python3 - "$HOST_IP" "$GUEST_IP" "$PREFIX" "$DNS_SERVER" "$DNS_SECONDARY" \
        "$GUEST_MAC" "$TAP_DEV" "$AGENT_PORT" "$VCPUS" "$MEMORY_MIB" \
        "$ENABLE_NETWORK" "$ENABLE_NAT" "$GUEST_DEBUG" <<'PY'
import ipaddress, re, sys
host, guest, prefix, dns1, dns2, mac, tap, port, cpus, memory, *flags = sys.argv[1:]
network = ipaddress.IPv4Network(f'{host}/{prefix}', strict=False)
addresses = [ipaddress.IPv4Address(a) for a in (host, guest, dns1, dns2)]
assert addresses[0] != addresses[1] and addresses[1] in network, 'Guest and gateway must share a subnet'
assert all(a not in (network.network_address, network.broadcast_address) for a in addresses[:2]), 'Invalid guest/gateway address'
assert re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', mac), 'Invalid MAC'
assert not int(mac[:2], 16) & 1, 'Multicast MAC is invalid'
assert re.fullmatch(r'[a-zA-Z0-9_-]{1,15}', tap), 'Invalid TAP device'
assert 1 <= int(port) <= 65535 and 1 <= int(cpus) <= 32 and int(memory) >= 128, 'Invalid machine settings'
assert all(flag in ('0', '1') for flag in flags), 'Flags must be 0 or 1'
PY
}

prepare() {
    validate
    [[ -x "$FC_BIN" ]] || fail 'Run setup and build, or set FC_BIN to bin/firecracker-release.'
    if [[ "$GUEST_MODE" == liquidmetal ]]; then
        [[ -x "$AGENT_BIN" && -x "$VSOCK_CONNECT" ]] || fail 'LiquidMetal mode needs guest-agent and vsock-connect; run setup.'
    elif [[ "$GUEST_MODE" == ssh ]]; then ensure_ssh_keys; fi
    local file source fingerprint old_fingerprint=
    # Reuse only base artifacts, never the writable disk of an existing VM.
    for file in guest-Image rootfs.ext4 ubuntu.squashfs; do
        case $file in
            guest-Image) source=$EXISTING_LAB/guest-vmlinux; file=$KERNEL ;;
            rootfs.ext4) source=$EXISTING_LAB/$file; file=$BASE_ROOTFS ;;
            *) source=$EXISTING_LAB/$file; file=$WORKDIR/$file ;;
        esac
        if [[ ! -s "$file" && -s "$source" ]]; then
            mkdir -p "$(dirname "$file")"
            log "Reusing $source"
            cp --reflink=auto --sparse=always "$source" "$file.part"
            mv "$file.part" "$file"
        fi
    done
    if [[ ! -s "$KERNEL" || ! -s "$BASE_ROOTFS" ]]; then
        KERNEL="$KERNEL" python3 "$FC_DIR/artifacts.py" "$WORKDIR"
    fi
    python3 - "$KERNEL" <<'PY'
import sys
with open(sys.argv[1], 'rb') as f:
    f.seek(56)
    assert f.read(4) == b'ARM\x64', 'KERNEL must be a raw ARM64 Linux Image, not ELF, config or compressed data'
PY
    if [[ ! -s "$BASE_ROOTFS" ]]; then
        local extracted
        extracted=$(mktemp -d "$WORKDIR/.squashfs.XXXXXX")
        unsquashfs -d "$extracted/root" "$WORKDIR/ubuntu.squashfs"
        truncate -s "$ROOTFS_SIZE" "$BASE_ROOTFS.part"
        mke2fs -q -t ext4 -F -d "$extracted/root" "$BASE_ROOTFS.part"
        e2fsck -fn "$BASE_ROOTFS.part"
        mv "$BASE_ROOTFS.part" "$BASE_ROOTFS"
        rm -rf -- "$extracted"
    fi
    # Each control mode owns its cache; Agent binaries are inputs only in Agent mode.
    fingerprint=$({ sha256sum "$BASE_ROOTFS" "$FC_DIR/inject-fc-rootfs.sh";
        if [[ "$GUEST_MODE" == liquidmetal ]]; then sha256sum "$AGENT_BIN"; fi
        if [[ "$GUEST_MODE" == ssh ]]; then sha256sum "$SSH_IDENTITY.pub" "$SSH_HOST_KEY"; fi
        printf '%s\n' "$HOST_IP" "$GUEST_IP" "$PREFIX" "$GUEST_MAC" "$DNS_SERVER" \
            "$DNS_SECONDARY" "$AGENT_PORT" "$ENABLE_NETWORK" "$GUEST_MODE" "$SSH_PORT";
    } | sha256sum | cut -d ' ' -f1)
    [[ ! -f "$PREPARED_ROOTFS.sha256" ]] || old_fingerprint=$(cat "$PREPARED_ROOTFS.sha256")
    if [[ ! -s "$PREPARED_ROOTFS" || "$old_fingerprint" != "$fingerprint" ]]; then
        bash "$FC_DIR/inject-fc-rootfs.sh" "$BASE_ROOTFS" "$PREPARED_ROOTFS"
        printf '%s\n' "$fingerprint" > "$PREPARED_ROOTFS.sha256"
    else log "Reusing cached $GUEST_MODE/network/DNS image"; fi
    cp --reflink=auto --sparse=always "$PREPARED_ROOTFS" "$RUN_ROOTFS.part"
    mv "$RUN_ROOTFS.part" "$RUN_ROOTFS"
    python3 - "$WORKDIR/config.json" "$KERNEL" "$RUN_ROOTFS" "$VSOCK_UDS" \
        "$VCPUS" "$MEMORY_MIB" "$ENABLE_NETWORK" "$TAP_DEV" "$GUEST_MAC" "$GUEST_DEBUG" "$GDB_SOCKET" "$GUEST_MODE" <<'PY'
import json, sys
path, kernel, rootfs, vsock, cpus, memory, network, tap, mac, debug, gdb, mode = sys.argv[1:]
config = {
    'boot-source': {'kernel_image_path': kernel, 'boot_args': 'keep_bootcon console=ttyS0 reboot=k panic=1 pci=off root=/dev/vda rw nokaslr'},
    'drives': [{'drive_id': 'rootfs', 'path_on_host': rootfs, 'is_root_device': True, 'is_read_only': False}],
    'machine-config': {'vcpu_count': int(cpus), 'mem_size_mib': int(memory)},
}
if mode == 'liquidmetal':
    config['vsock'] = {'guest_cid': 3, 'uds_path': vsock}
if network == '1':
    config['network-interfaces'] = [{'iface_id': 'eth0', 'host_dev_name': tap, 'guest_mac': mac}]
if debug == '1':
    config['machine-config'].update(vcpu_count=1, gdb_socket_path=gdb)
with open(path, 'w') as f:
    json.dump(config, f, indent=2)
    f.write('\n')
PY
    log "Prepared $WORKDIR/config.json"
}

network_up() {
    [[ "$ENABLE_NETWORK" == 1 ]] || return 0
    ip link show "$TAP_DEV" >/dev/null 2>&1 && fail "TAP already exists: $TAP_DEV (choose another name)."
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
    # Rules belong only to this launcher, recorded for cleanup after any failure.
    iptables -I FORWARD 1 -i "$TAP_DEV" -o "$UPLINK_IF" -s "$GUEST_IP/32" -m comment --comment fc-debug-config -j ACCEPT
    FORWARD_OUT=1
    iptables -I FORWARD 1 -i "$UPLINK_IF" -o "$TAP_DEV" -d "$GUEST_IP/32" -m conntrack \
        --ctstate ESTABLISHED,RELATED -m comment --comment fc-debug-config -j ACCEPT
    FORWARD_IN=1
    iptables -t nat -A POSTROUTING -s "$GUEST_IP/32" -o "$UPLINK_IF" -m comment --comment fc-debug-config -j MASQUERADE
    NAT_CREATED=1
    log "NAT: $GUEST_IP -> $UPLINK_IF; DNS: $DNS_SERVER, $DNS_SECONDARY"
}

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if [[ -n ${FC_PID:-} ]] && kill -0 "$FC_PID" 2>/dev/null; then
        kill "$FC_PID" 2>/dev/null || true
        wait "$FC_PID" 2>/dev/null || true
    fi
    if [[ -n ${CONSOLE_PID:-} ]]; then
        kill "$CONSOLE_PID" 2>/dev/null || true
        wait "$CONSOLE_PID" 2>/dev/null || true
    fi
    if [[ ${NAT_CREATED:-0} == 1 ]]; then
        iptables -t nat -D POSTROUTING -s "$GUEST_IP/32" -o "$UPLINK_IF" -m comment --comment fc-debug-config -j MASQUERADE || true
    fi
    if [[ ${FORWARD_IN:-0} == 1 ]]; then
        iptables -D FORWARD -i "$UPLINK_IF" -o "$TAP_DEV" -d "$GUEST_IP/32" -m conntrack \
            --ctstate ESTABLISHED,RELATED -m comment --comment fc-debug-config -j ACCEPT || true
    fi
    if [[ ${FORWARD_OUT:-0} == 1 ]]; then
        iptables -D FORWARD -i "$TAP_DEV" -o "$UPLINK_IF" -s "$GUEST_IP/32" -m comment --comment fc-debug-config -j ACCEPT || true
    fi
    if [[ ${TAP_CREATED:-0} == 1 ]]; then ip link del "$TAP_DEV" || true; fi
    rm -f "$API_SOCKET" "$VSOCK_UDS" "$VSOCK_UDS"_* "$GDB_SOCKET" "$WORKDIR/firecracker.pid" \
        "$CONSOLE_SOCKET" "$CONSOLE_TTY_FILE" "$WORKDIR/session.json"
    if [[ $status != 0 && -f "$WORKDIR/console.log" ]]; then tail -40 "$WORKDIR/console.log" >&2; fi
    exit "$status"
}

guest_exec() {
    case "$GUEST_MODE" in
        liquidmetal) "$VSOCK_CONNECT" exec --uds "$VSOCK_UDS" --port "$AGENT_PORT" -- "$@" ;;
        ssh) guest_ssh "$@" ;;
        serial) fail 'Serial mode has no Guest RPC. Use dev.sh console and enter the command there.' ;;
    esac
}

load_session() {
    [[ -f "$WORKDIR/session.json" ]] || return 0
    local values=()
    mapfile -d '' -t values < <(python3 - "$WORKDIR/session.json" <<'PY'
import ipaddress, json, sys
data = json.load(open(sys.argv[1]))
assert data['mode'] in ('serial', 'ssh', 'liquidmetal')
for key in ('guest_ip', 'host_ip'):
    ipaddress.IPv4Address(data[key])
assert 1 <= int(data['ssh_port']) <= 65535
keys = ('mode', 'guest_ip', 'host_ip', 'network', 'nat', 'ssh_port', 'identity', 'known_hosts')
sys.stdout.buffer.write(b''.join(str(data[key]).encode() + b'\0' for key in keys))
PY
    )
    [[ ${#values[@]} == 8 ]] || fail 'Invalid active Guest session metadata.'
    GUEST_MODE=${values[0]}; GUEST_IP=${values[1]}; HOST_IP=${values[2]}
    ENABLE_NETWORK=${values[3]}; ENABLE_NAT=${values[4]}; SSH_PORT=${values[5]}
    SSH_IDENTITY=${values[6]}; SSH_KNOWN_HOSTS=${values[7]}
}

start_console() {
    python3 "$FC_DIR/../common/guest/console.py" serve "$CONSOLE_SOCKET" --tty-file "$CONSOLE_TTY_FILE" \
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
check() {
    guest_exec uname -a
    guest_exec cat /etc/resolv.conf
    [[ "$ENABLE_NETWORK" == 1 ]] || return 0
    guest_exec ip route
    guest_exec ping -c 2 -W 3 "$HOST_IP"
    if [[ "$ENABLE_NAT" == 1 ]]; then
        guest_exec ping -c 2 -W 3 1.1.1.1
        guest_exec getent ahostsv4 example.com
    fi
}

run_vm() {
    exec 9> "$WORKDIR/run.lock"
    flock -n 9 || fail 'Another run/prepare/debug already owns this WORKDIR.'
    for socket in "$API_SOCKET" "$VSOCK_UDS" "$GDB_SOCKET" "$CONSOLE_SOCKET" "$CONSOLE_TTY_FILE"; do
        [[ ! -e "$socket" ]] || fail "Existing socket $socket; verify its owner before removing."
    done
    if [[ "$COMMAND" == debug-mi ]]; then
        prepare >> "$WORKDIR/launcher.log" 2>&1
    else prepare; fi
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    start_console
    python3 - "$WORKDIR/session.json" "$GUEST_MODE" "$GUEST_IP" "$HOST_IP" "$ENABLE_NETWORK" \
        "$ENABLE_NAT" "$SSH_PORT" "$SSH_IDENTITY" "$SSH_KNOWN_HOSTS" <<'PY'
import json, sys
keys = ('mode', 'guest_ip', 'host_ip', 'network', 'nat', 'ssh_port', 'identity', 'known_hosts')
with open(sys.argv[1], 'w') as output:
    json.dump(dict(zip(keys, sys.argv[2:])), output)
PY
    if [[ "$COMMAND" == debug-mi ]]; then
        network_up >> "$WORKDIR/launcher.log" 2>&1
        gdb --tty="$CONSOLE_TTY" "$@"
        return
    fi
    network_up
    local args=(--id fc-debug-config --api-sock "$API_SOCKET" --config-file "$WORKDIR/config.json" --level "$LOG_LEVEL")
    if [[ "$COMMAND" == debug ]]; then
        # GDB controls the Linux userspace VMM; upstream debug builds use an empty policy.
        gdb --tty="$CONSOLE_TTY" -q -ex 'set pagination off' -ex 'set breakpoint pending on' \
            -ex 'handle SIG35 nostop noprint pass' \
            -ex 'break firecracker::main' -ex run --args "$FC_BIN" "${args[@]}"
        return
    fi
    "$FC_BIN" "${args[@]}" < "$CONSOLE_TTY" > "$CONSOLE_TTY" 2>&1 &
    FC_PID=$!
    printf '%s\n' "$FC_PID" > "$WORKDIR/firecracker.pid"
    log "Firecracker PID=$FC_PID; API=$API_SOCKET; console=$WORKDIR/console.log"
    if [[ "$GUEST_DEBUG" == 1 ]]; then
        log 'Guest waits for GDB. In another terminal: VMLINUX=/matching/vmlinux ./dev.sh guest-gdb'
    elif [[ "$GUEST_MODE" == serial ]]; then
        log 'Serial Guest started; no Agent readiness check. Use dev.sh console (root autologin).'
    else
        local ready=0 attempt
        for ((attempt=0; attempt<120; attempt++)); do
            kill -0 "$FC_PID" 2>/dev/null || fail "Firecracker exited before $GUEST_MODE became ready."
            if [[ "$GUEST_MODE" == ssh ]]; then
                if timeout 5 bash -c 'source "$1/../common/guest/ssh.sh"; guest_ssh true' fc-ssh "$FC_DIR" >/dev/null 2>&1; then ready=1; break; fi
            elif timeout 2 "$VSOCK_CONNECT" ping --uds "$VSOCK_UDS" --port "$AGENT_PORT" >/dev/null 2>&1; then ready=1; break; fi
            sleep 0.5
        done
        [[ "$ready" == 1 ]] || fail "Guest $GUEST_MODE timed out; inspect $WORKDIR/console.log"
        log "Guest $GUEST_MODE ready. Use dev.sh exec / check / console / api. Ctrl+C stops this VM."
    fi
    local status=0
    wait "$FC_PID" || status=$?
    # dev.sh stop sends SIGTERM to the managed child; this is a normal shutdown.
    [[ $status == 0 || $status == 143 ]] || return "$status"
}

case "$COMMAND" in
    export-artifacts)
        destination=$FC_DIR/output/import
        mkdir -p "$destination"
        for name in guest-vmlinux rootfs.ext4 ubuntu.squashfs; do
            [[ -s "$EXISTING_LAB/$name" ]] || fail "Missing $EXISTING_LAB/$name"
            if [[ ! -s "$destination/$name" ]]; then
                cp --sparse=always "$EXISTING_LAB/$name" "$destination/$name.part"
                mv "$destination/$name.part" "$destination/$name"
            fi
        done
        if [[ ! -s "$FC_DIR/bin/firecracker-release" && -s "$EXISTING_LAB/firecracker" ]]; then
            cp "$EXISTING_LAB/firecracker" "$FC_DIR/bin/firecracker-release"
        fi
        log "Imported base artifacts to $destination" ;;
    setup) setup ;;
    doctor) doctor ;;
    build) build_fc ;;
    prepare)
        exec 9> "$WORKDIR/run.lock"
        flock -n 9 || fail 'VM is running; refusing to replace its writable disk.'
        prepare ;;
    run|debug) run_vm ;;
    debug-mi) run_vm "$@" ;;
    guest-debug) GUEST_DEBUG=1; run_vm ;;
    guest-gdb)
        [[ -s "$VMLINUX" ]] || fail 'Set VMLINUX to the unstripped ELF matching KERNEL.'
        exec gdb -q "$VMLINUX" -ex "target remote $GDB_SOCKET" ;;
    console) exec python3 "$FC_DIR/../common/guest/console.py" connect "$CONSOLE_SOCKET" ;;
    ssh)
        load_session
        [[ "$GUEST_MODE" == ssh ]] || fail 'The active Guest is not in SSH mode.'
        guest_ssh "$@" ;;
    exec) load_session; [[ $# -gt 0 ]] || fail 'Usage: dev.sh exec COMMAND [ARG...]'; guest_exec "$@" ;;
    check) load_session; check ;;
    api)
        [[ $# -ge 2 ]] || fail 'Usage: dev.sh api METHOD /endpoint [JSON]'
        [[ -S "$API_SOCKET" ]] || fail "Firecracker API socket is missing: $API_SOCKET. Start FC with ./dev.sh run, or launch in VSCode and press F5 to continue past main."
        args=(--fail-with-body --silent --show-error --unix-socket "$API_SOCKET" -X "$1" -H 'Content-Type: application/json')
        if [[ $# -gt 2 ]]; then args+=(--data "$3"); fi
        if curl "${args[@]}" "http://localhost$2"; then
            printf '\n'
        else
            curl_status=$?
            if [[ $curl_status == 7 ]]; then
                log "ERROR: No Firecracker API listener at $API_SOCKET. Check that FC is running and has continued past main; the socket may belong to an ended session." >&2
            fi
            exit "$curl_status"
        fi ;;
    stop)
        [[ -f "$WORKDIR/firecracker.pid" ]] || fail 'No managed Firecracker PID file.'
        pid=$(cat "$WORKDIR/firecracker.pid")
        [[ "$pid" =~ ^[0-9]+$ && -r /proc/$pid/cmdline ]] || fail 'Stale PID file.'
        tr '\0' '\n' < "/proc/$pid/cmdline" | grep -Fxq "$API_SOCKET" || fail 'PID belongs to another process; refusing to stop it.'
        kill -TERM "$pid" ;;
    *) fail "Unknown command: $COMMAND" ;;
esac
