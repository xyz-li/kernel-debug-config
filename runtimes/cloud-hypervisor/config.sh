#!/usr/bin/env bash
# .env is trusted local shell configuration, shared by macOS and Linux.
CH_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
CH_SOURCE_ROOT=$(cd -- "$CH_DIR/../../.." && pwd)
[[ ! -f "$CH_DIR/../common/.env" ]] || source "$CH_DIR/../common/.env"
[[ ! -f "$CH_DIR/.env" ]] || source "$CH_DIR/.env"
GUEST_MODE=${CH_GUEST_MODE:-${GUEST_MODE:-serial}}
case "$GUEST_MODE" in serial|ssh) ;; *) echo 'GUEST_MODE must be serial or ssh.' >&2; return 1 ;; esac
MACHINE=${MACHINE:-fc-ubuntu}
CH_SOURCE=${CH_SOURCE:-$CH_SOURCE_ROOT/cloud-hypervisor}
CH_BIN=${CH_BIN:-$CH_DIR/bin/cloud-hypervisor-debug}
WORKDIR=${WORKDIR:-/var/tmp/ch-debug-config}
TOOLS_DIR=${TOOLS_DIR:-/var/tmp/sandbox-debug-tools}
CH_RUST_VERSION=${CH_RUST_VERSION:-stable}
JOBS=${JOBS:-2}
KERNEL=${KERNEL:-$WORKDIR/guest-Image}
# Only the immutable base filesystem is shared with FC; the kernel is CH-specific.
BASE_ROOTFS=${BASE_ROOTFS:-/var/tmp/fc-debug-config/rootfs.ext4}
KERNEL_URL=${KERNEL_URL:-https://github.com/cloud-hypervisor/linux/releases/download/ch-release-v7.2.8-20261009/Image-arm64}
KERNEL_SHA256=${KERNEL_SHA256:-8f8f3d5a983809f87a4e1e9a13053a3361fda47ef04e09c771a41c5e037cb6c2}
PREPARED_ROOTFS=$WORKDIR/rootfs-$GUEST_MODE.ext4
RUN_ROOTFS=$WORKDIR/rootfs-run.ext4
API_SOCKET=$WORKDIR/api.socket
GDB_SOCKET=$WORKDIR/gdb.socket
CONSOLE_SOCKET=$WORKDIR/console.socket
CONSOLE_TTY_FILE=$WORKDIR/console.tty
SSH_PORT=${SSH_PORT:-22}
SSH_IDENTITY=${SSH_IDENTITY:-$WORKDIR/ssh/id_ed25519}
SSH_HOST_KEY=$WORKDIR/ssh/guest_host_ed25519
SSH_KNOWN_HOSTS=$WORKDIR/ssh/known_hosts
TAP_DEV=${TAP_DEV:-ch-debug0}
HOST_IP=${HOST_IP:-172.16.52.1}
GUEST_IP=${GUEST_IP:-172.16.52.2}
PREFIX=${PREFIX:-30}
GUEST_MAC=${GUEST_MAC:-06:00:ac:10:34:02}
DNS_SERVER=${DNS_SERVER:-1.1.1.1}
DNS_SECONDARY=${DNS_SECONDARY:-8.8.8.8}
ENABLE_NETWORK=${ENABLE_NETWORK:-1}
ENABLE_NAT=${ENABLE_NAT:-1}
UPLINK_IF=${UPLINK_IF:-}
VCPUS=${VCPUS:-2}
MEMORY_MIB=${MEMORY_MIB:-512}
GUEST_DEBUG=${GUEST_DEBUG:-0}
VMLINUX=${VMLINUX:-}
SECCOMP=${SECCOMP:-false}
# Forward the same settings for CLI, GDB and the inferior's exec wrapper.
CH_ENV_KEYS=(CH_SOURCE CH_BIN WORKDIR TOOLS_DIR CH_RUST_VERSION JOBS KERNEL BASE_ROOTFS
    KERNEL_URL KERNEL_SHA256 SSH_PORT SSH_IDENTITY TAP_DEV HOST_IP GUEST_IP PREFIX
    GUEST_MAC DNS_SERVER DNS_SECONDARY ENABLE_NETWORK ENABLE_NAT UPLINK_IF VCPUS
    MEMORY_MIB GUEST_DEBUG VMLINUX SECCOMP)
export "${CH_ENV_KEYS[@]}" GUEST_MODE SSH_HOST_KEY SSH_KNOWN_HOSTS
export CH_GUEST_MODE=$GUEST_MODE
