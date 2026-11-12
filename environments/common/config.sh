#!/usr/bin/env bash
# Source after setting DEBUG_KIND to gvisor or kata.
DEBUG_COMMON=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEBUG_ROOT=$(dirname "$DEBUG_COMMON")
DEBUG_REPO_ROOT=$(dirname "$DEBUG_ROOT")
DEBUG_SOURCE_ROOT=$(dirname "$DEBUG_REPO_ROOT")
DEBUG_DIR=$DEBUG_ROOT/${DEBUG_KIND:?Set DEBUG_KIND}
[[ ! -f "$DEBUG_COMMON/.env" ]] || source "$DEBUG_COMMON/.env"
[[ ! -f "$DEBUG_DIR/.env" ]] || source "$DEBUG_DIR/.env"
MACHINE=${MACHINE:-fc-ubuntu}
SOURCE_DIR=${SOURCE_DIR:-$DEBUG_SOURCE_ROOT/$([[ "$DEBUG_KIND" == kata ]] && echo kata-containers || echo gvisor)}
WORKDIR=${WORKDIR:-/var/tmp/$DEBUG_KIND-debug}
TOOLS_DIR=${TOOLS_DIR:-/var/tmp/sandbox-debug-tools}
GO_VERSION=${GO_VERSION:-1.26.2}
DLV_VERSION=${DLV_VERSION:-latest}
BAZELISK_VERSION=${BAZELISK_VERSION:-latest}
DEBUG_PORT=${DEBUG_PORT:-38697}
JOBS=${JOBS:-2}
BIN_DIR=$DEBUG_DIR/bin
HOST_KERNEL=${HOST_KERNEL:-$DEBUG_SOURCE_ROOT/containerization/kernel/vmlinux-arm64}
KATA_CONFIG=${KATA_CONFIG:-}
KATA_RUST_VERSION=${KATA_RUST_VERSION:-}
KATA_BUNDLE=${KATA_BUNDLE:-$WORKDIR/bundle}
KATA_AGENT_SERVER_ADDR=${KATA_AGENT_SERVER_ADDR:-unix://@/tmp/kata-debug-agent.socket}
export DEBUG_KIND DEBUG_DIR SOURCE_DIR WORKDIR TOOLS_DIR BIN_DIR GO_VERSION
export DLV_VERSION BAZELISK_VERSION JOBS KATA_CONFIG KATA_RUST_VERSION KATA_BUNDLE KATA_AGENT_SERVER_ADDR
export PATH="$TOOLS_DIR/bin:$TOOLS_DIR/go-$GO_VERSION/bin:$PATH"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need_source() {
    [[ -d "$SOURCE_DIR/.git" || -f "$SOURCE_DIR/.git" ]] || die "Clone the upstream repository, then run ./dev.sh bind /path/to/checkout (current: $SOURCE_DIR)"
}
linux_init() {
    [[ $(uname -s) == Linux ]] || die 'This operation runs on Linux; use dev.sh from macOS.'
    [[ $EUID == 0 ]] || die 'Run as root on Linux.'
    [[ "$WORKDIR" == /* && "$WORKDIR" != / ]] || die 'WORKDIR must be an absolute dedicated directory.'
    mkdir -p "$WORKDIR" "$TOOLS_DIR/bin" "$BIN_DIR"
    chmod 700 "$WORKDIR" "$TOOLS_DIR"
    export GOCACHE=$TOOLS_DIR/go-cache GOMODCACHE=$TOOLS_DIR/go-mod
}
remote() {
    if [[ $(uname -s) != Darwin ]]; then
        exec bash "$DEBUG_DIR/dev.sh" _linux "$@"
    fi
    local encoded opts=() key
    encoded=$(python3 -c 'import base64,json,sys;print(base64.b64encode(json.dumps(sys.argv[1:]).encode()).decode())' "$@")
    for key in SOURCE_DIR WORKDIR TOOLS_DIR GO_VERSION DLV_VERSION BAZELISK_VERSION DEBUG_PORT JOBS KATA_CONFIG KATA_RUST_VERSION KATA_BUNDLE KATA_AGENT_SERVER_ADDR; do
        opts+=(--env "$key=${!key}")
    done
    if [[ -t 0 && -t 1 ]]; then opts+=(-it); fi
    exec container machine run -n "$MACHINE" --root "${opts[@]}" --env "DEBUG_ARGS_BASE64=$encoded" -- \
        /bin/bash "$DEBUG_DIR/dev.sh" _linux
}
decode_args() {
    if [[ -n ${DEBUG_ARGS_BASE64:-} ]]; then
        mapfile -d '' -t DECODED_ARGS < <(python3 -c 'import base64,json,os,sys;sys.stdout.buffer.write(b"".join(a.encode()+b"\0" for a in json.loads(base64.b64decode(os.environ["DEBUG_ARGS_BASE64"]))))')
        (( ${#DECODED_ARGS[@]} > 0 )) || die 'Invalid or empty remote command.'
        unset DEBUG_ARGS_BASE64
    else DECODED_ARGS=("$@"); fi
}
setup_packages() {
    local packages=(ca-certificates curl python3 python3-yaml build-essential git pkg-config \
        clang libclang-dev libssl-dev libseccomp-dev gdb protobuf-compiler socat procps \
        iproute2 iptables busybox-static runc rsync zip unzip default-jdk-headless)
    if [[ "$DEBUG_KIND" == kata ]]; then packages+=(qemu-system-arm qemu-utils libelf-dev libudev-dev libdevmapper-dev libcap-dev libpci-dev); fi
    local missing=() package
    for package in "${packages[@]}"; do
        [[ $(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true) == installed ]] || missing+=("$package")
    done
    if (( ${#missing[@]} )); then
        export DEBIAN_FRONTEND=noninteractive
        local apt_options=(-o Acquire::Retries=3 -o Acquire::https::Timeout=20 -o DPkg::Lock::Timeout=300)
        if [[ -f /etc/apt/sources.list.d/ubuntu.sources ]]; then
            python3 - "$TOOLS_DIR/ubuntu.sources" <<'PY'
from pathlib import Path
import sys
text = Path('/etc/apt/sources.list.d/ubuntu.sources').read_text()
text = text.replace('http://ports.ubuntu.com/', 'https://ports.ubuntu.com/')
Path(sys.argv[1]).write_text(text)
PY
            apt_options+=(-o "Dir::Etc::sourcelist=$TOOLS_DIR/ubuntu.sources" -o Dir::Etc::sourceparts=-)
        fi
        apt-get "${apt_options[@]}" update
        apt-get "${apt_options[@]}" install -y --no-install-recommends "${missing[@]}"
    fi
}
setup_go() {
    python3 "$DEBUG_COMMON/tools.py" go "$GO_VERSION" "$TOOLS_DIR"
    if [[ ! -x "$TOOLS_DIR/bin/dlv" ]]; then
        GOBIN="$TOOLS_DIR/bin" go install "github.com/go-delve/delve/cmd/dlv@$DLV_VERSION"
    fi
    if [[ "$DEBUG_KIND" == gvisor && ! -x "$TOOLS_DIR/bin/bazelisk" ]]; then
        GOBIN="$TOOLS_DIR/bin" go install "github.com/bazelbuild/bazelisk@$BAZELISK_VERSION"
    fi
}
setup_rust() {
    export RUSTUP_HOME=$TOOLS_DIR/rustup CARGO_HOME=$TOOLS_DIR/cargo
    export PATH="$CARGO_HOME/bin:$PATH"
    if [[ ! -x "$CARGO_HOME/bin/rustup" ]]; then
        curl --fail --location --retry 3 https://sh.rustup.rs -o "$TOOLS_DIR/rustup-init.sh"
        sh "$TOOLS_DIR/rustup-init.sh" -y --no-modify-path --profile minimal --default-toolchain none
    fi
}
doctor() {
    printf 'Host: %s\nSource: %s\nWork: %s\n' "$(uname -sm)" "$SOURCE_DIR" "$WORKDIR"
    [[ -d "$SOURCE_DIR" ]] || die 'Source is not bound yet; run dev.sh bind PATH.'
    if [[ "$DEBUG_KIND" == gvisor ]]; then
        command -v bazelisk; command -v dlv
        [[ -f "$SOURCE_DIR/.bazelversion" ]] || die 'Not a gVisor checkout.'
    else
        command -v gdb
        [[ -f "$SOURCE_DIR/src/agent/Cargo.toml" ]] || die 'Not a Kata checkout.'
    fi
    printf 'Debugger transport and build prerequisites found.\n'
}
