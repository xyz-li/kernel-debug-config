#!/usr/bin/env bash
set -Eeuo pipefail
exec 9>/cache/workflow.lock
flock -n 9 || { echo 'Stop the active QEMU debugger before building.' >&2; exit 1; }
python3 /scripts/runtime/vm.py require-stopped
mkdir -p /cache/qemu-source /cache/qemu-build
rsync -a --delete --exclude /.git --exclude /build /src/qemu/ /cache/qemu-source/
cp /scripts/runtime/devices.mak /cache/qemu-source/configs/devices/aarch64-softmmu/kernel-debug.mak
stamp=$(sha256sum /scripts/runtime/build.sh /scripts/runtime/devices.mak /cache/qemu-source/configure /cache/qemu-source/VERSION)
cd /cache/qemu-build
if [[ ! -f .debug-config || $(cat .debug-config) != "$stamp" ]]; then
    /cache/qemu-source/configure --target-list=aarch64-softmmu \
        --without-default-features --without-default-devices --with-devices-aarch64=kernel-debug \
        --enable-tcg --enable-system --enable-slirp --enable-fdt=system --enable-debug --enable-debug-info \
        --disable-strip --disable-werror --disable-docs --disable-tools --disable-download \
        --extra-cflags='-g3 -fno-omit-frame-pointer'
    printf '%s\n' "$stamp" > .debug-config
fi
ninja -j"${JOBS:-2}" qemu-system-aarch64
python3 /scripts/runtime/vm.py record-build
./qemu-system-aarch64 --version | head -n 1
