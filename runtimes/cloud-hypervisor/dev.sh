#!/usr/bin/env bash
set -Eeuo pipefail
if [[ ${1:-} == --mode ]]; then
    export CH_GUEST_MODE=${2:?Usage: dev.sh --mode serial|ssh COMMAND}
    shift 2
fi
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"

remote() {
    if [[ $(uname -s) != Darwin ]]; then
        exec /bin/bash "$CH_DIR/run-cloud-hypervisor.sh" "$@"
    fi
    local encoded key opts=()
    for key in "${CH_ENV_KEYS[@]}" CH_GUEST_MODE; do opts+=(--env "$key=${!key}"); done
    encoded=$(python3 -c 'import base64,json,sys; print(base64.b64encode(json.dumps(sys.argv[1:]).encode()).decode())' "$@")
    if [[ -t 0 && -t 1 ]]; then opts+=(-it); fi
    exec container machine run -n "$MACHINE" --root "${opts[@]}" --env "CH_ARGS_BASE64=$encoded" -- \
        /bin/bash "$CH_DIR/run-cloud-hypervisor.sh"
}

case ${1:-help} in
    bind) python3 "$CH_DIR/../common/bind.py" cloud-hypervisor "${2:?Usage: dev.sh bind /path/to/cloud-hypervisor}" ;;
    setup|doctor|build|prepare|run|debug|attach|guest-debug|guest-gdb|console|ssh|exec|check|api|stop) remote "$@" ;;
    shell)
        if [[ $(uname -s) == Darwin ]]; then
            exec container machine run -n "$MACHINE" --root -it -- /bin/bash
        fi
        exec /bin/bash ;;
    help|-h|--help) cat <<'EOF'
Usage: ./dev.sh [--mode serial|ssh] COMMAND [arguments]
  bind PATH     Bind an upstream checkout; generate the local VSCode workspace
  setup         Install Ubuntu build/debug/guest preparation dependencies
  doctor        Check ARM64 Linux, KVM_CREATE_VM, source, tools and guest assets
  build         Build native GNU debug binaries with the guest_debug feature
  prepare       Download/verify CH kernel; prepare an independent Guest disk
  run           Run Cloud Hypervisor; Ctrl+C cleans up this instance
  debug         Launch GDB and break at cloud_hypervisor::main
  attach PID    Attach Linux GDB to this environment's running VMM
  guest-debug   Start one vCPU paused, waiting for Guest kernel GDB
  guest-gdb     Connect to Guest GDB using the matching VMLINUX ELF
  console       Open serial console; Ctrl+] disconnects without stopping the VM
  ssh [CMD...]  Open Guest SSH shell or run a command (SSH mode)
  exec CMD...   Run a command in the SSH Guest
  check         Check Guest, gateway, external connectivity and DNS (SSH mode)
  api METHOD /endpoint [JSON]   Call the CH Unix socket API
  stop          Stop only this environment's managed VMM
  shell         Open a Linux Host shell
macOS uses the existing Apple Container machine (default fc-ubuntu).
Linux ARM64 runs locally as root. See README.md for first-time Host/rootfs setup.
EOF
        ;;
    *) echo "Unknown command: $1 (see dev.sh help)" >&2; exit 2 ;;
esac
