#!/usr/bin/env bash
# Shared configuration. Optional .env is trusted shell code and can override it.
FC_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
FC_REPO_ROOT=$(cd -- "$FC_DIR/../.." && pwd)
FC_SOURCE_ROOT=$(dirname "$FC_REPO_ROOT")
if [[ -f "$FC_DIR/.env" ]]; then
    # .env is a local, trusted shell configuration, never a downloaded file.
    source "$FC_DIR/.env"
fi
MACHINE=${MACHINE:-fc-ubuntu}
HOST_IMAGE=${HOST_IMAGE:-fc-debug-host:ubuntu24.04}
HOST_KERNEL=${HOST_KERNEL:-$FC_SOURCE_ROOT/containerization/kernel/vmlinux-arm64}
ARTIFACT_MACHINE=${ARTIFACT_MACHINE:-}
FC_SOURCE=${FC_SOURCE:-$FC_SOURCE_ROOT/firecracker}
AGENT_SOURCE=${AGENT_SOURCE:-$FC_SOURCE_ROOT/guest-agent}
WORKDIR=${WORKDIR:-/var/tmp/fc-debug-config}
EXISTING_LAB=${EXISTING_LAB:-$FC_DIR/output/import}
FC_BIN=${FC_BIN:-$FC_DIR/bin/firecracker-debug}
AGENT_BIN=${AGENT_BIN:-$FC_DIR/bin/guest-agent}
VSOCK_CONNECT=${VSOCK_CONNECT:-$FC_DIR/bin/vsock-connect}
KERNEL=${KERNEL:-$WORKDIR/guest-Image}
BASE_ROOTFS=${BASE_ROOTFS:-$WORKDIR/rootfs.ext4}
AGENT_ROOTFS=$WORKDIR/rootfs-agent.ext4
RUN_ROOTFS=$WORKDIR/rootfs-run.ext4
API_SOCKET=$WORKDIR/api.socket
VSOCK_UDS=$WORKDIR/vsock.socket
GDB_SOCKET=$WORKDIR/gdb.socket
TAP_DEV=${TAP_DEV:-fc-debug0}
HOST_IP=${HOST_IP:-172.16.51.1}
GUEST_IP=${GUEST_IP:-172.16.51.2}
PREFIX=${PREFIX:-30}
GUEST_MAC=${GUEST_MAC:-06:00:ac:10:33:02}
DNS_SERVER=${DNS_SERVER:-1.1.1.1}
DNS_SECONDARY=${DNS_SECONDARY:-8.8.8.8}
ENABLE_NETWORK=${ENABLE_NETWORK:-1}
ENABLE_NAT=${ENABLE_NAT:-1}
UPLINK_IF=${UPLINK_IF:-}
AGENT_PORT=${AGENT_PORT:-1024}
VCPUS=${VCPUS:-2}
MEMORY_MIB=${MEMORY_MIB:-512}
ROOTFS_SIZE=${ROOTFS_SIZE:-1G}
GUEST_DEBUG=${GUEST_DEBUG:-0}
VMLINUX=${VMLINUX:-}
LOG_LEVEL=${LOG_LEVEL:-Debug}
export FC_DIR WORKDIR AGENT_BIN AGENT_PORT GUEST_IP HOST_IP PREFIX GUEST_MAC
export DNS_SERVER DNS_SECONDARY ENABLE_NETWORK
