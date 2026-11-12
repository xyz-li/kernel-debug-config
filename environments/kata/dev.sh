#!/usr/bin/env bash
set -Eeuo pipefail
DEBUG_KIND=kata
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/common/config.sh"

build() {
    need_source
    setup_rust
    local channel target
    channel=${KATA_RUST_VERSION:-$(python3 - "$SOURCE_DIR/rust-toolchain.toml" <<'PY'
import sys, tomllib
with open(sys.argv[1], 'rb') as f:
    print(tomllib.load(f)['toolchain']['channel'])
PY
)}
    target=$(uname -m)-unknown-linux-gnu
    rustup toolchain install "$channel" --profile minimal
    export CARGO_TARGET_DIR=$WORKDIR/target
    export CARGO_PROFILE_DEV_DEBUG=2 CARGO_PROFILE_DEV_OPT_LEVEL=0 CARGO_PROFILE_DEV_STRIP=none
    export CARGO_BUILD_JOBS=$JOBS
    export CARGO_ENCODED_RUSTFLAGS="--remap-path-prefix=$SOURCE_DIR=/src/kata-containers"$'\x1f''-Cforce-frame-pointers=yes'
    cd "$SOURCE_DIR"
    local selection=${1:-all}
    if [[ "$selection" == all || "$selection" == runtime ]]; then
        rustup run "$channel" cargo build --locked --target "$target" \
            --manifest-path src/runtime-rs/Cargo.toml --bin containerd-shim-kata-v2 --bin shim-ctl
        cp "$WORKDIR/target/$target/debug/containerd-shim-kata-v2" "$BIN_DIR/containerd-shim-kata-v2-debug"
        cp "$WORKDIR/target/$target/debug/shim-ctl" "$BIN_DIR/shim-ctl-debug"
    fi
    if [[ "$selection" == all || "$selection" == agent ]]; then
        rustup run "$channel" cargo build --locked --target "$target" --manifest-path src/agent/Cargo.toml
        rustup run "$channel" cargo build --locked --target "$target" --manifest-path src/tools/agent-ctl/Cargo.toml
        cp "$WORKDIR/target/$target/debug/kata-agent" "$BIN_DIR/kata-agent-debug"
        cp "$WORKDIR/target/$target/debug/kata-agent-ctl" "$BIN_DIR/kata-agent-ctl"
    fi
    [[ "$selection" == all || "$selection" == runtime || "$selection" == agent ]] || die 'build accepts all, runtime or agent.'
    git rev-parse HEAD > "$BIN_DIR/source.commit"
}

if [[ ${1:-} == _linux ]]; then
    shift
    decode_args "$@"
    set -- "${DECODED_ARGS[@]}"
    linux_init
    command=${1:-help}; shift || true
    case "$command" in
        setup)
            exec 9> "$TOOLS_DIR/setup.lock"
            flock 9
            setup_packages; setup_rust ;;
        doctor) doctor ;;
        build) build "$@" ;;
        bundle) python3 "$DEBUG_COMMON/bundle.py" "$KATA_BUNDLE" ;;
        vm-check)
            [[ -f "$KATA_CONFIG" ]] || die 'Set KATA_CONFIG to a complete upstream configuration.toml.'
            python3 "$DEBUG_COMMON/check_kata_vm.py" "$KATA_CONFIG" ;;
        agent-check)
            [[ -f "$KATA_BUNDLE/config.json" ]] || die 'Run dev.sh bundle first.'
            exec "$BIN_DIR/kata-agent-ctl" connect --server-address "$KATA_AGENT_SERVER_ADDR" \
                --bundle-dir "$KATA_BUNDLE" -c Check -c GetGuestDetails ;;
        vm)
            [[ -f "$KATA_CONFIG" ]] || die 'Set KATA_CONFIG to a complete upstream configuration.toml with real VM assets.'
            python3 "$DEBUG_COMMON/check_kata_vm.py" "$KATA_CONFIG"
            [[ -f "$KATA_BUNDLE/config.json" ]] || die 'Run dev.sh bundle first.'
            export KATA_CONF_FILE=$KATA_CONFIG
            cd "$KATA_BUNDLE"
            exec "$BIN_DIR/shim-ctl-debug" "$@" ;;
        *) die 'Unknown Linux command.' ;;
    esac
    exit
fi
case ${1:-help} in
    bind) python3 "$DEBUG_COMMON/bind.py" kata "${2:?Usage: dev.sh bind /path/to/kata-containers}" ;;
    setup|doctor|build|bundle|agent-check|vm-check|vm) remote "$@" ;;
    *) cat <<'EOF'
Usage: ./dev.sh COMMAND
  bind PATH          Bind a kata-containers checkout and generate local workspace
  setup              Install Ubuntu build dependencies and Rustup
  doctor             Check source and tools
  build [all|runtime|agent]  Build unoptimized GNU debug binaries from your checkout
  bundle             Create a minimal local OCI bundle using Ubuntu busybox-static
  agent-check        Call Check / GetGuestDetails on the standalone debug Agent
  vm-check           Validate real VM assets, KVM and selected vsock backend
  vm                 Run shim-ctl with KATA_CONFIG and KATA_BUNDLE
VSCode supports entry debugging of the Rust shim, shim-ctl and Agent.
EOF
    ;;
esac
