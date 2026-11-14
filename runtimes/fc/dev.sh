#!/usr/bin/env bash
set -Eeuo pipefail
if [[ ${1:-} == --mode ]]; then
    export FC_GUEST_MODE=${2:?Usage: dev.sh --mode liquidmetal|serial|ssh COMMAND}
    shift 2
fi
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"

usage() {
    cat <<'EOF'
Usage: ./dev.sh [--mode liquidmetal|serial|ssh] COMMAND [arguments]
  host-create   Build Ubuntu Host image and create its KVM-enabled machine
  host-build    Rebuild the reusable Ubuntu Host image
  bind PATH     Connect an existing Firecracker checkout and generate a workspace
  import        Import base guest artifacts from the existing Alpine machine
  doctor        Check Linux/KVM, dependencies and cached artifacts
  setup         Install Linux dependencies; import existing agent/release binaries
  build         Build Firecracker with Rust symbols and the guest GDB feature
  prepare       Prepare kernel, rootfs and JSON; does not start a VM
  run           Start an isolated microVM; Ctrl+C cleans its TAP/NAT rules
  debug         Launch Firecracker under GDB (break at main)
  guest-debug   Boot paused at guest entry, waiting for kernel GDB
  guest-gdb     Connect GDB to guest; set VMLINUX to the matching unstripped ELF
  console       Open the guest serial console; Ctrl+] disconnects
  ssh [CMD...]  Open a guest SSH shell or run a command (ssh mode)
  exec CMD...   Run through LiquidMetal vsock or SSH, according to active mode
  check         Verify guest, gateway, external IP and DNS
  api METHOD PATH [JSON]   Call Firecracker's Unix socket API
  stop          Stop only the microVM managed by this directory
  shell         Open a root shell on the configured Linux machine
On macOS commands use the Ubuntu Apple Container machine (default fc-ubuntu).
On Linux they run locally. Copy .env.example to .env to customize settings.
EOF
}

build_host() {
    MACHINE="$MACHINE" HOST_IMAGE="$HOST_IMAGE" HOST_KERNEL="$HOST_KERNEL" \
        bash "$FC_DIR/../common/host/dev.sh" build
}

create_host() {
    MACHINE="$MACHINE" HOST_IMAGE="$HOST_IMAGE" HOST_KERNEL="$HOST_KERNEL" \
        bash "$FC_DIR/../common/host/dev.sh" create
}

import_existing() {
    [[ -n "$ARTIFACT_MACHINE" ]] || { echo 'Set ARTIFACT_MACHINE to the machine to import from.' >&2; exit 1; }
    import_agents
    mkdir -p "$FC_DIR/output/import"
    local encoded
    encoded=$(python3 -c 'import base64,json; print(base64.b64encode(json.dumps(["export-artifacts"]).encode()).decode())')
    container machine run -n "$ARTIFACT_MACHINE" --root \
        --env "FC_ARGS_BASE64=$encoded" --env EXISTING_LAB=/root/fc-lab \
        -- /bin/bash "$FC_DIR/run-firecracker.sh"
}

import_agents() {
    local name candidate
    mkdir -p "$FC_DIR/bin"
    for name in guest-agent vsock-connect; do
        [[ -s "$FC_DIR/bin/$name" ]] && continue
        candidate="$AGENT_SOURCE/bin/$name-linux-arm64"
        if [[ -f "$candidate" ]]; then
            cp "$candidate" "$FC_DIR/bin/$name"
            chmod +x "$FC_DIR/bin/$name"
        fi
    done
}

linux() {
    if [[ $(uname -s) == Darwin ]]; then
        command -v container >/dev/null || { echo 'Apple Container CLI is required.' >&2; exit 1; }
        local opts=() key
        # Forward explicitly supplied overrides; .env is also read inside Linux.
        for key in WORKDIR EXISTING_LAB FC_SOURCE FC_BIN KERNEL BASE_ROOTFS AGENT_BIN VSOCK_CONNECT \
            TAP_DEV HOST_IP GUEST_IP PREFIX GUEST_MAC DNS_SERVER DNS_SECONDARY ENABLE_NETWORK \
            ENABLE_NAT UPLINK_IF AGENT_PORT VCPUS MEMORY_MIB ROOTFS_SIZE GUEST_DEBUG VMLINUX LOG_LEVEL \
            SSH_PORT SSH_IDENTITY; do
            opts+=(--env "$key=${!key}")
        done
        opts+=(--env "FC_GUEST_MODE=$GUEST_MODE")
        # machine run versions may join argv into a shell command. Transport
        # arguments as data so exec sh -c, spaces and quotes survive unchanged.
        local encoded
        encoded=$(python3 -c 'import base64,json,sys; print(base64.b64encode(json.dumps(sys.argv[1:]).encode()).decode())' "$@")
        opts+=(--env "FC_ARGS_BASE64=$encoded")
        if [[ -t 0 && -t 1 ]]; then opts+=(-it); fi
        exec container machine run -n "$MACHINE" --root "${opts[@]}" -- \
            /bin/bash "$FC_DIR/run-firecracker.sh"
    else
        exec /bin/bash "$FC_DIR/run-firecracker.sh" "$@"
    fi
}

case ${1:-help} in
    help|-h|--help) usage ;;
    bind) python3 "$FC_DIR/../common/bind.py" fc "${2:?Usage: dev.sh bind /path/to/firecracker}" ;;
    host-build) build_host ;;
    host-create) create_host ;;
    import) import_existing ;;
    setup) import_agents; linux setup ;;
    doctor|build|prepare|run|debug|guest-debug|guest-gdb|console|ssh|exec|check|api|stop) linux "$@" ;;
    shell)
        if [[ $(uname -s) == Darwin ]]; then
            exec container machine run -n "$MACHINE" --root -it -- /bin/bash
        fi
        exec /bin/bash ;;
    *) usage >&2; exit 2 ;;
esac
