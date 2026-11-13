#!/bin/bash
# 快速配置内核 - 最小化可调试配置
# 使用方法: ./configure_kernel.sh [架构]

set -e

ARCH=${1:-arm64}
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}配置最小化可调试内核${NC}"
echo -e "${GREEN}========================================${NC}"
echo "架构: $ARCH"
echo ""

# 1. 生成默认配置
echo -e "${YELLOW}生成基础配置...${NC}"
make ARCH=$ARCH defconfig

# 2. 禁用不需要的大型功能
echo -e "${YELLOW}禁用不需要的功能...${NC}"
scripts/config --disable CONFIG_DRM
scripts/config --disable CONFIG_SOUND
scripts/config --disable CONFIG_SND
scripts/config --disable CONFIG_WIRELESS
scripts/config --disable CONFIG_WLAN
scripts/config --disable CONFIG_BT
scripts/config --disable CONFIG_INPUT_TOUCHSCREEN
scripts/config --disable CONFIG_INPUT_TABLET
scripts/config --disable CONFIG_INPUT_JOYSTICK
scripts/config --disable CONFIG_USB_SUPPORT

# 3. 启用 VirtIO 支持（必需）
echo -e "${YELLOW}启用 VirtIO 支持...${NC}"
scripts/config --enable CONFIG_VIRTIO
scripts/config --enable CONFIG_VIRTIO_PCI
scripts/config --enable CONFIG_VIRTIO_PCI_LEGACY
scripts/config --enable CONFIG_VIRTIO_MMIO
scripts/config --enable CONFIG_VIRTIO_RING

# 块设备支持
scripts/config --enable CONFIG_BLK_DEV
scripts/config --enable CONFIG_VIRTIO_BLK

# 网络设备
scripts/config --enable CONFIG_VIRTIO_NET

# 控制台
scripts/config --enable CONFIG_VIRTIO_CONSOLE
scripts/config --enable CONFIG_HVC_DRIVER

# 4. 启用网络支持（必需）
echo -e "${YELLOW}启用网络支持...${NC}"
scripts/config --enable CONFIG_NET
scripts/config --enable CONFIG_INET
scripts/config --enable CONFIG_NETDEVICES
scripts/config --enable CONFIG_ETHERNET
scripts/config --enable CONFIG_PACKET
scripts/config --enable CONFIG_UNIX

# 5. 启用调试支持（必需）
echo -e "${YELLOW}启用调试支持...${NC}"
scripts/config --enable CONFIG_DEBUG_INFO
scripts/config --enable CONFIG_DEBUG_INFO_DWARF5
scripts/config --disable CONFIG_DEBUG_INFO_REDUCED
scripts/config --enable CONFIG_DEBUG_INFO_COMPRESSED_NONE
scripts/config --enable CONFIG_GDB_SCRIPTS
scripts/config --enable CONFIG_DEBUG_KERNEL
scripts/config --enable CONFIG_FRAME_POINTER
scripts/config --enable CONFIG_KALLSYMS
scripts/config --enable CONFIG_KALLSYMS_ALL
scripts/config --enable CONFIG_MAGIC_SYSRQ

# 6. 启用基本文件系统
echo -e "${YELLOW}启用基本文件系统...${NC}"
scripts/config --enable CONFIG_PROC_FS
scripts/config --enable CONFIG_PROC_KCORE
scripts/config --enable CONFIG_SYSFS
scripts/config --enable CONFIG_TMPFS
scripts/config --enable CONFIG_DEVTMPFS
scripts/config --enable CONFIG_DEVTMPFS_MOUNT
scripts/config --enable CONFIG_EXT4_FS

# initramfs 支持
scripts/config --enable CONFIG_BLK_DEV_INITRD
scripts/config --enable CONFIG_RD_GZIP
scripts/config --enable CONFIG_RD_XZ

# 7. 启用模块支持
echo -e "${YELLOW}启用模块支持...${NC}"
scripts/config --enable CONFIG_MODULES
scripts/config --enable CONFIG_MODULE_UNLOAD

# 8. 其他有用的配置
scripts/config --enable CONFIG_TTY
scripts/config --enable CONFIG_UNIX98_PTYS
scripts/config --enable CONFIG_SERIAL_8250
scripts/config --enable CONFIG_SERIAL_8250_CONSOLE
scripts/config --enable CONFIG_PRINTK
scripts/config --enable CONFIG_PRINTK_TIME

# 9. 解决所有依赖关系
echo -e "${YELLOW}解决配置依赖...${NC}"
make ARCH=$ARCH olddefconfig

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}配置完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 验证关键配置
echo -e "${YELLOW}验证关键配置...${NC}"
MISSING=""
for cfg in CONFIG_VIRTIO CONFIG_VIRTIO_BLK CONFIG_VIRTIO_NET CONFIG_INET CONFIG_DEBUG_INFO; do
    if grep -q "^${cfg}=y" .config; then
        echo -e "${GREEN}✓${NC} $cfg"
    else
        echo -e "\033[0;31m✗${NC} $cfg - 缺失"
        MISSING="yes"
    fi
done

echo ""
if [ -z "$MISSING" ]; then
    echo -e "${GREEN}所有关键配置已启用！可以开始编译。${NC}"
    exit 0
else
    echo -e "\033[0;31m警告: 某些关键配置缺失，编译可能失败${NC}"
    exit 1
fi
