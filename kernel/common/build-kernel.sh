#!/usr/bin/env bash
# Build on native Linux storage, without writing to the bound source tree.
set -Eeuo pipefail
[[ ${ARCH:-arm64} == arm64 ]] || { echo 'Automated workflow currently supports ARCH=arm64.' >&2; exit 2; }
mkdir -p /cache/source /cache/build /cache/modules /output
exec 9>/cache/workflow.lock
flock -n 9 || { echo 'Another build owns this kernel cache.' >&2; exit 1; }
[[ ! -e /cache/run/qemu.json ]] || { echo 'Stop the managed QEMU before rebuilding.' >&2; exit 1; }

# Old in-tree build artifacts must not contaminate the native source mirror.
rsync -a --checksum --delete --out-format='%i %n' --exclude=.git --exclude=.config --exclude='.config.*' \
    --exclude='*.o' --exclude='*.a' --exclude='*.ko' --exclude='*.cmd' \
    --exclude='*.mod' --exclude='*.mod.c' --exclude='*.d' --exclude=vmlinux \
    --exclude=System.map --exclude=Module.symvers --exclude=modules.order \
    --exclude=include/config --exclude=include/generated \
    --exclude='arch/*/include/generated' /kernel/ /cache/source/ > /cache/source-sync.log
# Tarballs and restored worktrees can retain old mtimes. Changed content must
# still be newer than cached objects, or make could silently reuse old code.
python3 - <<'PY'
import os
from pathlib import Path
for line in Path('/cache/source-sync.log').read_text().splitlines():
    item, _, name = line.partition(' ')
    if item.startswith('>f'):
        os.utime(Path('/cache/source') / name, None)
PY
python3 /scripts/kernel/debug_profile.py apply /cache/source "$@"
base=${KERNEL_BASE_CONFIG:-defconfig}
[[ "$base" =~ ^[a-zA-Z0-9_]+config$ ]] || { echo 'Invalid KERNEL_BASE_CONFIG.' >&2; exit 2; }
fragment=/cache/fragment.config
python3 /scripts/kernel/manifest.py normalize-config /output/kernel.fragment.config "$fragment"
stamp=$( { sha256sum "$fragment" /scripts/kernel/build-kernel.sh /kernel/Makefile; printf '%s\n' "$base" "${CROSS_COMPILE:-}"; } | sha256sum | cut -d' ' -f1)
make_args=(-C /cache/source O=/cache/build ARCH=arm64 KBUILD_ABS_SRCTREE=1)
if [[ $(uname -m) != aarch64 && -z ${CROSS_COMPILE:-} ]]; then CROSS_COMPILE=aarch64-linux-gnu-; fi
if [[ -n ${CROSS_COMPILE:-} ]]; then make_args+=(CROSS_COMPILE="$CROSS_COMPILE"); fi
if [[ ! -f /cache/build/.config || ! -f /cache/config.sha256 || $(cat /cache/config.sha256) != "$stamp" ]]; then
    make "${make_args[@]}" "$base"
    (cd /cache/source; ARCH=arm64 scripts/kconfig/merge_config.sh -m -O /cache/build /cache/build/.config "$fragment")
    printf '%s\n' "$stamp" > /cache/config.sha256
fi
make "${make_args[@]}" olddefconfig
python3 /scripts/kernel/manifest.py check-config /cache/build/.config
python3 /scripts/kernel/manifest.py check-network-config /cache/build/.config
python3 /scripts/kernel/manifest.py check-requested-config /cache/build/.config "$fragment"
make "${make_args[@]}" -j"${JOBS:-2}" Image modules
python3 /scripts/kernel/debug_profile.py record /cache/build /output "$@"
make "${make_args[@]}" scripts_gdb
release=$(make -s "${make_args[@]}" kernelrelease)
# Only this kernel's modules are exported; old releases never enter its initramfs.
rm -rf "/cache/modules/lib/modules/$release"
install_args=(INSTALL_MOD_PATH=/cache/modules)
if [[ ${KERNEL_STRIP_MODULES:-1} == 1 ]]; then install_args+=(INSTALL_MOD_STRIP=1); fi
make "${make_args[@]}" "${install_args[@]}" modules_install
mkdir -p "/output/modules/$release" /output/generated
rsync -a --checksum --delete "/cache/modules/lib/modules/$release/" "/output/modules/$release/"
for artifact in vmlinux System.map .config; do
    target=$artifact
    if [[ "$artifact" == .config ]]; then target=kernel.config; fi
    if ! cmp -s "/cache/build/$artifact" "/output/$target"; then
        cp "/cache/build/$artifact" "/output/$target.part"
        mv "/output/$target.part" "/output/$target"
    fi
done
if ! cmp -s /cache/build/arch/arm64/boot/Image /output/Image; then
    cp /cache/build/arch/arm64/boot/Image /output/Image.part
    mv /output/Image.part /output/Image
fi
printf '%s\n' "$release" > /output/kernel.release
rsync -a --delete /cache/build/include/ /output/generated/include/
mkdir -p /output/generated/arch/arm64/include
rsync -a --delete /cache/build/arch/arm64/include/ /output/generated/arch/arm64/include/
python3 /cache/source/scripts/clang-tools/gen_compile_commands.py -d /cache/build -o /output/compile_commands.linux.json
python3 /scripts/kernel/manifest.py kernel "$release"
echo "Kernel ready: $release (Image, vmlinux, matching modules)"
