#!/usr/bin/env bash
# Shared Apple Container Host; per-runtime host-create/host-build remain aliases.
set -Eeuo pipefail
HOST_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$HOST_DIR/../../.." && pwd)
source_root=$(dirname "$REPO_ROOT")
# An explicit caller setting takes precedence over the shared defaults.
caller_machine=${MACHINE:-}
caller_image=${HOST_IMAGE:-}
caller_kernel=${HOST_KERNEL:-}
[[ ! -f "$HOST_DIR/../.env" ]] || source "$HOST_DIR/../.env"
MACHINE=${caller_machine:-${MACHINE:-fc-ubuntu}}
HOST_IMAGE=${caller_image:-${HOST_IMAGE:-fc-debug-host:ubuntu24.04}}
HOST_KERNEL=${caller_kernel:-${HOST_KERNEL:-$source_root/containerization/kernel/vmlinux-arm64}}

build() {
    container build --platform linux/arm64 --progress plain --tag "$HOST_IMAGE" \
        --file "$HOST_DIR/Dockerfile" "$HOST_DIR"
}

case ${1:-help} in
    build) build ;;
    create)
        [[ $(uname -s) == Darwin ]] || { echo 'Host creation requires macOS Apple Container.' >&2; exit 1; }
        if container machine inspect "$MACHINE" >/dev/null 2>&1; then
            printf 'Machine %s already exists.\n' "$MACHINE"
            exit
        fi
        [[ -s "$HOST_KERNEL" ]] || { printf 'Missing KVM Host kernel: %s\n' "$HOST_KERNEL" >&2; exit 1; }
        build
        container machine create --name "$MACHINE" --cpus 4 --memory 6G --home-mount rw \
            --virtualization --kernel "$HOST_KERNEL" "$HOST_IMAGE" ;;
    shell) exec container machine run -n "$MACHINE" --root -it -- /bin/bash ;;
    help|-h|--help)
        cat <<'EOF'
Usage: ./dev.sh build|create|shell
Shared Ubuntu ARM64 KVM Host for Firecracker, Cloud Hypervisor, gVisor and Kata.
Settings: MACHINE, HOST_IMAGE, HOST_KERNEL; optional runtimes/common/.env.
Existing machines are reused. No global default machine is changed.
EOF
        ;;
    *) echo "Unknown Host command: $1" >&2; exit 2 ;;
esac
