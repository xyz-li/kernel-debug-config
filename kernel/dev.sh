#!/usr/bin/env bash
set -Eeuo pipefail
directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
case ${KERNEL_ROOTFS:-initramfs} in
    initramfs|alpine) profile=apple-container ;;
    debian|disk) profile=debian-container ;;
    *) echo 'KERNEL_ROOTFS must be initramfs or debian' >&2; exit 2 ;;
esac
exec "$directory/$profile/dev.sh" "$@"
