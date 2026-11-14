#!/usr/bin/env bash
# VSCode MI pipe: no TTY, no banners or stdout logging before GDB starts.
set -Eeuo pipefail
if [[ ${1:-} == --guest-mode ]]; then
    export FC_GUEST_MODE=${2:?Missing Guest mode}
    shift 2
fi
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"
source "$FC_DIR/../common/mi-pipe.sh"
prepare_mi_pipe "$@"
case "$GUEST_MODE" in liquidmetal|serial|ssh) ;; *) echo 'Invalid Guest mode' >&2; exit 2 ;; esac
opts=(--env "FC_GUEST_MODE=$GUEST_MODE")
for key in WORKDIR EXISTING_LAB FC_SOURCE FC_BIN KERNEL BASE_ROOTFS AGENT_BIN VSOCK_CONNECT \
    TAP_DEV HOST_IP GUEST_IP PREFIX GUEST_MAC DNS_SERVER DNS_SECONDARY ENABLE_NETWORK \
    ENABLE_NAT UPLINK_IF AGENT_PORT VCPUS MEMORY_MIB ROOTFS_SIZE GUEST_DEBUG VMLINUX LOG_LEVEL \
    SSH_PORT SSH_IDENTITY; do
    opts+=(--env "$key=${!key}")
done
exec /usr/local/bin/container machine run -n "$MACHINE" --root "${MI_PIPE_FLAGS[@]}" "${opts[@]}" -- "$@"
