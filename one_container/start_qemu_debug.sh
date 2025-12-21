#!/bin/bash
set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}QEMU 内核调试启动脚本${NC}"
echo -e "${GREEN}========================================${NC}"

# 配置变量
ARCH=${ARCH:-arm64}
KERNEL_IMAGE=${KERNEL_IMAGE:-/output/Image}
INITRAMFS=${INITRAMFS:-/output/initramfs.cpio.gz}
GDB_PORT=${GDB_PORT:-1234}
MEMORY=${MEMORY:-2G}
CPUS=${CPUS:-2}
APPEND=${APPEND:-"console=ttyAMA0 debug earlyprintk=serial"}

echo -e "${GREEN}QEMU 配置:${NC}"
echo "  架构: $ARCH"
echo "  内核镜像: $KERNEL_IMAGE"
echo "  Initramfs: $INITRAMFS"
echo "  GDB 调试端口: $GDB_PORT"
echo "  内存: $MEMORY"
echo "  CPU 核心数: $CPUS"
echo "  内核启动参数: $APPEND"
echo ""

# 检查内核镜像是否存在
if [ ! -f "$KERNEL_IMAGE" ]; then
    echo -e "${RED}错误: 内核镜像不存在: $KERNEL_IMAGE${NC}"
    echo -e "${YELLOW}请先编译内核或检查 KERNEL_IMAGE 路径${NC}"
    exit 1
fi

# 检查 initramfs 是否存在（可选）
INITRAMFS_PARAM=""
if [ -f "$INITRAMFS" ]; then
    echo -e "${GREEN}✓ 找到 initramfs: $INITRAMFS${NC}"
    INITRAMFS_PARAM="-initrd $INITRAMFS"
else
    echo -e "${YELLOW}⚠ 未找到 initramfs: $INITRAMFS${NC}"
    echo -e "${YELLOW}  将不使用 initramfs 启动${NC}"
fi

echo ""

# 检测 KVM 支持（只在 Linux 主机上可用）
ACCEL_MODE="tcg"
if [ -e "/dev/kvm" ] && [ -r "/dev/kvm" ] && [ -w "/dev/kvm" ]; then
    echo -e "${GREEN}✓ 检测到 KVM 支持，将使用硬件加速${NC}"
    ACCEL_MODE="kvm"
else
    echo -e "${YELLOW}⚠ KVM 不可用（macOS 或其他非 Linux 主机），使用 TCG 软件模拟模式${NC}"
    echo -e "${YELLOW}  注意: 软件模拟性能较低，但功能完整${NC}"
fi
echo ""

# 根据架构选择 QEMU 命令
case "$ARCH" in
    arm64)
        QEMU_CMD="qemu-system-aarch64"
        MACHINE="virt"
        CPU="cortex-a57"
        QEMU_ARGS="-M $MACHINE,accel=$ACCEL_MODE -cpu $CPU"
        ;;
    arm)
        QEMU_CMD="qemu-system-arm"
        MACHINE="virt"
        CPU="cortex-a15"
        QEMU_ARGS="-M $MACHINE,accel=$ACCEL_MODE -cpu $CPU"
        ;;
    x86_64|x86)
        QEMU_CMD="qemu-system-x86_64"
        MACHINE="pc"
        QEMU_ARGS="-M $MACHINE,accel=$ACCEL_MODE"
        KERNEL_IMAGE=${KERNEL_IMAGE/Image/bzImage}  # x86 使用 bzImage
        ;;
    *)
        echo -e "${RED}错误: 不支持的架构: $ARCH${NC}"
        exit 1
        ;;
esac

# 检查 QEMU 是否安装
if ! command -v $QEMU_CMD &> /dev/null; then
    echo -e "${RED}错误: 未找到 $QEMU_CMD${NC}"
    echo -e "${YELLOW}请安装 QEMU: apt-get install qemu-system-arm qemu-system-aarch64 qemu-system-x86${NC}"
    exit 1
fi

# 构建 QEMU 命令
QEMU_FULL_CMD="$QEMU_CMD $QEMU_ARGS \
    -m $MEMORY \
    -smp $CPUS \
    -kernel $KERNEL_IMAGE \
    $INITRAMFS_PARAM \
    -append \"$APPEND\" \
    -nographic \
    -s -S"

echo -e "${GREEN}启动 QEMU 调试模式...${NC}"
echo -e "${BLUE}QEMU 命令:${NC}"
echo "$QEMU_FULL_CMD"
echo ""
echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}调试信息:${NC}"
echo -e "${YELLOW}========================================${NC}"
echo -e "${GREEN}QEMU 将在端口 $GDB_PORT 等待 GDB 连接${NC}"
echo ""
echo -e "${BLUE}使用以下命令连接 GDB:${NC}"
echo -e "  ${GREEN}gdb-multiarch /output/vmlinux${NC}"
echo -e "  ${GREEN}(gdb) target remote :$GDB_PORT${NC}"
echo ""
echo -e "${BLUE}或者使用 VSCode Remote Debugging：${NC}"
echo -e "  1. 在 VSCode 中打开项目"
echo -e "  2. 按 F5 启动调试"
echo -e "  3. 选择 'Kernel (Remote Debug)' 配置"
echo ""
echo -e "${YELLOW}========================================${NC}"
echo ""
echo -e "${YELLOW}提示:${NC}"
echo -e "  - QEMU 已启动并暂停在启动前 (-S 参数)"
echo -e "  - 连接 GDB 后使用 'continue' 命令开始执行"
echo -e "  - 使用 Ctrl+A X 退出 QEMU (非调试模式)"
echo -e "  - 使用 Ctrl+C 中断 QEMU 进程"
echo ""
echo -e "${GREEN}启动中...${NC}"
echo ""

# 执行 QEMU
exec $QEMU_FULL_CMD
