#!/bin/sh
# Build rootfs from the selected Alpine image, matching modules and user overlay.
set -eu
mkdir -p /cache /output
exec 9>/cache/rootfs.lock
flock -n 9 || { echo 'Another rootfs build is active.' >&2; exit 1; }
test -s /output/kernel.json || { echo 'Build the kernel before rootfs.' >&2; exit 1; }
busybox --list | grep -qx init || { echo 'The rootfs image needs the BusyBox init applet.' >&2; exit 1; }
fingerprint=$(python3 /scripts/kernel/manifest.py rootfs-fingerprint)
if [ "${ROOTFS_FORCE:-0}" != 1 ] && [ -s /output/initramfs.cpio.gz ] && \
   [ -f /output/rootfs.json ] && [ -f /output/rootfs.sha256 ] && [ "$(cat /output/rootfs.sha256)" = "$fingerprint" ]; then
    if python3 /scripts/kernel/manifest.py rootfs-check "$fingerprint" && gzip -t /output/initramfs.cpio.gz; then
        echo 'Rootfs unchanged; reusing initramfs.cpio.gz'
        exit 0
    fi
fi
stage=$(mktemp -d /cache/rootfs.XXXXXX)
trap 'rm -rf "$stage"' EXIT
mkdir "$stage/root"
# Select root entries explicitly: the archive itself lives in /cache and must
# never become part of its own input, regardless of tar's exclude semantics.
set --
for entry in /* /.[!.]* /..?*; do
    case "$entry" in
        /proc|/sys|/dev|/tmp|/run|/cache|/output|/overlay|/scripts|/work|/.dockerenv) continue ;;
    esac
    if [ -e "$entry" ] || [ -L "$entry" ]; then set -- "$@" "${entry#/}"; fi
done
tar -C / -cf "$stage/base.tar" "$@"
tar -C "$stage/root" -xf "$stage/base.tar"
rm "$stage/base.tar"
root="$stage/root"
rm -rf "$root/lib/modules"
mkdir -p "$root/dev" "$root/proc" "$root/sys" "$root/run" "$root/tmp" \
    "$root/etc/kernel-debug" "$root/root" "$root/lib/modules"
chmod 1777 "$root/tmp"
release=$(cat /output/kernel.release)
cp -a "/output/modules/$release" "$root/lib/modules/"
rm -f "$root/lib/modules/$release/build" "$root/lib/modules/$release/source"
cp /scripts/kernel/guest-init "$root/init"
cp /scripts/kernel/guest-rcS "$root/etc/kernel-debug/rcS"
cp /scripts/kernel/guest-udhcpc "$root/etc/kernel-debug/udhcpc"
chmod 755 "$root/init" "$root/etc/kernel-debug/rcS" "$root/etc/kernel-debug/udhcpc"
cat > "$root/etc/inittab" <<'EOF'
::sysinit:/etc/kernel-debug/rcS
ttyAMA0::respawn:/bin/sh -l
::ctrlaltdel:/bin/busybox reboot
::shutdown:/bin/busybox umount -a -r
EOF
printf 'kernel-debug\n' > "$root/etc/hostname"
printf 'nameserver 10.0.2.3\n' > "$root/etc/resolv.conf"
mknod -m 600 "$root/dev/console" c 5 1
mknod -m 666 "$root/dev/null" c 1 3
# Overlay is applied last, so users can customize /init, tools, configs or tests.
cp -a /overlay/. "$root/"
rm -f "$root/.gitkeep"
test -x "$root/init"
test -x "$root/bin/busybox"
find "$root" -exec touch -h -d '@0' {} +
(cd "$root"; find . -print0 | sort -z | cpio --null -o --format=newc --owner=0:0) > "$stage/initramfs.cpio"
gzip -n -1 -c "$stage/initramfs.cpio" > /output/initramfs.cpio.gz.part
gzip -t /output/initramfs.cpio.gz.part
mv /output/initramfs.cpio.gz.part /output/initramfs.cpio.gz
python3 /scripts/kernel/manifest.py rootfs-record "$fingerprint"
printf '%s\n' "$fingerprint" > /output/rootfs.sha256
echo "Rootfs ready: Alpine + $release modules + rootfs-overlay"
