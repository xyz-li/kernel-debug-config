#!/bin/sh
# Provision a writable Debian disk once; later builds only refresh the bootstrap.
set -eu
exec 9>/cache/rootfs.lock
flock -n 9
busybox --list | grep -qx init
busybox --list | grep -qx udhcpc
case ${ROOTFS_SIZE_MIB:-2048} in *[!0-9]*|'') echo 'ROOTFS_SIZE_MIB must be an integer' >&2; exit 2;; esac
[ "${ROOTFS_SIZE_MIB:-2048}" -ge 512 ] || { echo 'Root disk must be at least 512 MiB' >&2; exit 2; }
stage=$(mktemp -d /cache/debian-rootfs.XXXXXX)
trap 'rm -rf "$stage"' EXIT
if [ ! -e /output/rootfs.ext4 ]; then
    root=$stage/root
    mkdir "$root"
    set --
    for entry in /* /.[!.]* /..?*; do
        case "$entry" in /proc|/sys|/dev|/tmp|/run|/cache|/output|/scripts|/overlay|/work|/.dockerenv) continue;; esac
        if [ -e "$entry" ] || [ -L "$entry" ]; then set -- "$@" "${entry#/}"; fi
    done
    tar -C / -cf "$stage/base.tar" "$@"
    tar -C "$root" -xf "$stage/base.tar"
    rm "$stage/base.tar"
    mkdir -p "$root/dev" "$root/proc" "$root/sys" "$root/run" "$root/tmp" "$root/root" "$root/etc/kernel-debug"
    chmod 1777 "$root/tmp"
    cp /scripts/kernel/guest-init "$root/init"
    cp /scripts/kernel/guest-disk-rcS "$root/etc/kernel-debug/rcS"
    cp /scripts/kernel/guest-control "$root/etc/kernel-debug/control"
    cp /scripts/kernel/guest-udhcpc "$root/etc/kernel-debug/udhcpc"
    chmod 755 "$root/init" "$root/etc/kernel-debug/"*
    cat > "$root/etc/inittab" <<'EOF'
::sysinit:/etc/kernel-debug/rcS
ttyAMA0::respawn:/bin/sh -l
::respawn:/etc/kernel-debug/control
::ctrlaltdel:/bin/busybox reboot
::shutdown:/bin/busybox sync
::shutdown:/bin/busybox mount -o remount,ro /
EOF
    printf 'kernel-debian\n' > "$root/etc/hostname"
    printf 'nameserver 10.0.2.3\n' > "$root/etc/resolv.conf"
    rm -f "$root/etc/machine-id"
    cp -a /overlay/. "$root/"
    rm -f "$root/.gitkeep"
    truncate -s "${ROOTFS_SIZE_MIB:-2048}M" /output/rootfs.ext4.part
    mkfs.ext4 -F -q -m 0 -U "$ROOTFS_UUID" -L kernel-debian -O ^orphan_file \
        -E lazy_itable_init=0,lazy_journal_init=0 -d "$root" /output/rootfs.ext4.part
    mv /output/rootfs.ext4.part /output/rootfs.ext4
    echo 'Persistent Debian root disk initialized'
else
    echo 'Keeping existing persistent Debian root disk'
fi
boot=$stage/bootstrap
mkdir -p "$boot/bin" "$boot/dev" "$boot/proc" "$boot/sys" "$boot/newroot" "$boot/lib/modules"
cp /bin/busybox "$boot/bin/busybox"
cp /scripts/kernel/guest-bootstrap "$boot/init"
chmod 755 "$boot/init" "$boot/bin/busybox"
cp -a "/output/modules/$KERNEL_RELEASE" "$boot/lib/modules/"
rm -f "$boot/lib/modules/$KERNEL_RELEASE/build" "$boot/lib/modules/$KERNEL_RELEASE/source"
printf '%s\n' "$MODULES_HASH" > "$boot/modules.hash"
printf '%s\n' "$KERNEL_RELEASE" > "$boot/kernel.release"
mknod -m 600 "$boot/dev/console" c 5 1
(cd "$boot"; find . -print0 | sort -z | cpio --null -o --format=newc --owner=0:0) > "$stage/bootstrap.cpio"
gzip -n -1 -c "$stage/bootstrap.cpio" > /output/initramfs.cpio.gz.part
gzip -t /output/initramfs.cpio.gz.part
mv /output/initramfs.cpio.gz.part /output/initramfs.cpio.gz
echo 'Debian bootstrap ready; persistent disk and user changes preserved'
