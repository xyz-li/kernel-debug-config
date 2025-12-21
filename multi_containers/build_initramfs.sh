#!/bin/sh
# 在 initramfs-builder 容器中构建 initramfs
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

OUTPUT_DIR=${OUTPUT_DIR:-/output}
ROOTFS_DIR=${ROOTFS_DIR:-/output/rootfs}
INITRAMFS_FILE=${INITRAMFS_FILE:-initramfs.cpio.gz}

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}构建 initramfs${NC}"
echo -e "${GREEN}========================================${NC}"
echo "输出目录: $OUTPUT_DIR"
echo "Rootfs 目录: $ROOTFS_DIR"
echo "Initramfs 文件: $INITRAMFS_FILE"
echo ""

# 创建临时工作目录
WORKDIR=$(mktemp -d)
echo "临时工作目录: $WORKDIR"

# 1. 导出当前容器的文件系统到临时目录
echo -e "${YELLOW}导出 Alpine 文件系统...${NC}"
cd /
tar -cf "$WORKDIR/alpine-rootfs.tar" \
    --exclude='proc' \
    --exclude='sys' \
    --exclude='dev' \
    --exclude='tmp' \
    --exclude='run' \
    --exclude='output' \
    --exclude='work' \
    --exclude='scripts' \
    --exclude='var/empty' \
    .

# 2. 准备合并目录
echo -e "${YELLOW}准备合并 rootfs...${NC}"
MERGE_DIR="$WORKDIR/rootfs"
mkdir -p "$MERGE_DIR"

# 3. 解压 Alpine 文件系统
cd "$MERGE_DIR"
tar -xf "$WORKDIR/alpine-rootfs.tar"
rm "$WORKDIR/alpine-rootfs.tar"

# 移除可能导致问题的空目录，但保留 tmp 目录
rm -rf proc sys dev run var/empty 2>/dev/null || true
# 确保 tmp 目录存在
mkdir -p tmp

# 4. 如果存在现有的 rootfs（包含内核模块），合并进来
if [ -d "$ROOTFS_DIR" ]; then
    echo -e "${YELLOW}合并现有的 rootfs（保留内核模块）...${NC}"

    # 复制 lib/modules（如果存在）
    if [ -d "$ROOTFS_DIR/lib/modules" ]; then
        MODULE_COUNT=$(find "$ROOTFS_DIR/lib/modules" -name "*.ko" 2>/dev/null | wc -l)
        echo -e "${GREEN}✓ 发现 $MODULE_COUNT 个内核模块${NC}"

        # 显示内核版本
        KERNEL_VERSION=$(ls "$ROOTFS_DIR/lib/modules/" 2>/dev/null | head -1)
        if [ -n "$KERNEL_VERSION" ]; then
            echo -e "${GREEN}  内核版本: $KERNEL_VERSION${NC}"
        fi

        # 确保目标目录存在
        mkdir -p "$MERGE_DIR/lib/modules"

        # 复制整个 modules 目录
        echo -e "${YELLOW}  复制模块到合并目录...${NC}"
        cp -a "$ROOTFS_DIR/lib/modules/"* "$MERGE_DIR/lib/modules/" 2>&1 || {
            echo -e "${RED}✗ 模块复制失败${NC}"
            exit 1
        }

        # 验证复制是否成功
        COPIED_COUNT=$(find "$MERGE_DIR/lib/modules" -name "*.ko" 2>/dev/null | wc -l)
        echo -e "${GREEN}✓ 已复制 $COPIED_COUNT 个模块到合并目录${NC}"

        if [ "$COPIED_COUNT" -ne "$MODULE_COUNT" ]; then
            echo -e "${RED}✗ 警告: 复制的模块数量不匹配！${NC}"
            echo -e "${YELLOW}  原始: $MODULE_COUNT, 复制后: $COPIED_COUNT${NC}"
        fi
    else
        echo -e "${YELLOW}⚠ 未发现内核模块目录: $ROOTFS_DIR/lib/modules${NC}"
    fi

    # 复制其他可能存在的自定义文件
    # （这里可以根据需要添加其他目录的合并逻辑）
else
    echo -e "${YELLOW}⚠ 未发现现有 rootfs，将创建纯 Alpine 系统${NC}"
fi

# 5. 创建必要的目录结构
echo -e "${YELLOW}创建目录结构...${NC}"
mkdir -p bin sbin usr/bin usr/sbin
mkdir -p etc/init.d
mkdir -p proc sys dev tmp run var mnt root home

# 确保 tmp 目录存在（解决 mount 错误）
# 注意：第54行已经创建了tmp目录，这里不需要重复创建

# 6. 创建 init 脚本
echo -e "${YELLOW}创建 init 脚本...${NC}"
cat > init << 'EOF'
#!/bin/sh
export PATH=/usr/sbin:/usr/bin:/sbin:/bin:/usr/local/bin

# 1. 挂载基本文件系统
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev 2>/dev/null || {
    mount -t tmpfs tmpfs /dev
    mknod -m 666 /dev/console c 5 1
    mknod -m 666 /dev/null c 1 3
    mknod -m 666 /dev/zero c 1 5
    mknod -m 666 /dev/tty c 5 0
}
mkdir -p /dev/pts /dev/shm
mount -t devpts devpts /dev/pts 2>/dev/null
mount -t tmpfs tmpfs /dev/shm 2>/dev/null
mkdir -p /tmp
mount -t tmpfs tmpfs /tmp
mkdir -p /run
mount -t tmpfs tmpfs /run

# 2. 初始化时先设置输出到 console（用于显示启动消息）
exec 1>/dev/console
exec 2>/dev/console

# 3. 设置主机名和网络
hostname localhost
ip link set lo up

# 4. 加载内核模块
echo "========================================="
echo "Loading kernel modules..."
echo "========================================="

if [ -d /lib/modules ]; then
    KERNEL_VERSION=$(uname -r)
    MODULE_PATH="/lib/modules/$KERNEL_VERSION"

    if [ -d "$MODULE_PATH" ]; then
        echo "Kernel version: $KERNEL_VERSION"

        # 生成模块依赖（如果需要）
        if command -v depmod >/dev/null 2>&1; then
            if [ ! -f "$MODULE_PATH/modules.dep" ]; then
                echo "Generating module dependencies..."
                depmod -a
            fi
        fi

        # 加载 VirtIO 模块
        if command -v modprobe >/dev/null 2>&1; then
            echo "Loading VirtIO modules..."
            modprobe virtio_pci 2>/dev/null && echo "  ✓ virtio_pci"
            modprobe virtio_net 2>/dev/null && echo "  ✓ virtio_net"
            modprobe virtio_blk 2>/dev/null && echo "  ✓ virtio_blk"
        fi

        echo ""
        echo "Loaded modules:"
        lsmod 2>/dev/null | head -10
    fi
fi

echo ""

# 5. 初始化网络（等待网络设备）
echo "========================================="
echo "Network Initialization"
echo "========================================="

# 允许非特权用户发送 ping 请求, 否则 ping 会无法发送SOCK_DGRAM类型ping package, 只能发送SOCK_RAW类型的包
sysctl -w net.ipv4.ping_group_range="0 2147483647"

# 检查 VirtIO-Net 驱动状态
echo ""
echo "Checking VirtIO-Net driver..."
if [ -d /sys/bus/virtio/drivers/virtio_net ]; then
    echo "  ✓ VirtIO-Net driver is present"
    # 显示绑定的设备
    if ls /sys/bus/virtio/drivers/virtio_net/virtio* >/dev/null 2>&1; then
        echo "  ✓ VirtIO devices bound:"
        ls -1 /sys/bus/virtio/drivers/virtio_net/ | grep virtio
    fi
else
    echo "  ✗ VirtIO-Net driver NOT found!"
fi

echo ""
echo "Waiting for network devices..."
sleep 2  # 等待更长时间

# 显示所有检测到的网络接口（调试）
echo ""
echo "All detected network interfaces:"
ALL_IFACES=$(ls /sys/class/net/ 2>/dev/null)
if [ -z "$ALL_IFACES" ]; then
    echo "  ✗ No network interfaces found!"
else
    for iface in $ALL_IFACES; do
        echo "  - $iface"
    done
fi

# 禁用不需要的虚拟接口
echo ""
echo "Disabling unwanted virtual interfaces..."
DISABLED_COUNT=0
for iface in tunl0 sit0 ip6tnl0 ip6gre0 gre0; do
    if [ -e /sys/class/net/$iface ]; then
        echo "  Disabling $iface"
        ip link set $iface down 2>/dev/null || true
        DISABLED_COUNT=$((DISABLED_COUNT + 1))
    fi
done
if [ $DISABLED_COUNT -eq 0 ]; then
    echo "  (none found - good!)"
fi

# 配置网络接口
echo ""
echo "Configuring network interfaces..."

# 查找并配置所有非 lo、非虚拟的接口
CONFIGURED=0
for iface in $(ls /sys/class/net/ | grep -v lo); do
    # 跳过已禁用的虚拟接口
    case "$iface" in
        tunl0|sit0|ip6tnl0|ip6gre0|gre0)
            continue
            ;;
    esac

    echo "  Bringing up $iface..."
    ip link set $iface up

    # 显示接口详情
    if command -v ethtool >/dev/null 2>&1; then
        DRIVER=$(ethtool -i $iface 2>/dev/null | grep driver | cut -d: -f2 | xargs)
        if [ -n "$DRIVER" ]; then
            echo "    Driver: $DRIVER"
        fi
    fi

    # 尝试 DHCP（如果有 udhcpc）
    if command -v udhcpc >/dev/null 2>&1; then
        echo "    Attempting DHCP..."
        udhcpc -i $iface -n -q 2>/dev/null &
    fi

    CONFIGURED=$((CONFIGURED + 1))
done

if [ $CONFIGURED -eq 0 ]; then
    echo "  ✗ No network interfaces to configure!"
    echo ""
    echo "Debugging info:"
    echo "  Kernel messages about VirtIO:"
    dmesg | grep -i virtio | tail -20
fi

echo ""
echo "Final network interface status:"
ip link show

# 6. 初始化 nftables（创建默认规则）
if command -v nft >/dev/null 2>&1; then
    echo "Initializing nftables..."
    # 创建默认表
    nft add table ip filter
    nft add table ip nat
    nft add table ip mangle

    # 创建默认链并设置策略
    nft add chain ip filter INPUT { type filter hook input priority 0\; policy accept\; }
    nft add chain ip filter FORWARD { type filter hook forward priority 0\; policy accept\; }
    nft add chain ip filter OUTPUT { type filter hook output priority 0\; policy accept\; }

    echo "  ✓ nftables initialized"
fi

echo ""

# 7. 显示系统信息
echo "========================================="
echo "System initialized successfully"
echo "========================================="
echo ""
cat /proc/version 2>/dev/null || echo "Linux kernel started"
echo ""
echo "System information:"
echo "  Hostname: $(hostname)"
echo "  Uptime: $(cat /proc/uptime | cut -d' ' -f1)s"
echo ""
echo "Network interfaces:"
ip addr show 2>/dev/null || echo "  (ip command not available)"
echo ""
echo "Available commands:"
echo "  nft, ipset, ip, tc"
echo "  modprobe, lsmod, insmod, rmmod"
echo "  strace, tcpdump, curl, wget"
echo ""

# 8. 启动 shell
# 使用 setsid 创建新会话，并直接在 ttyAMA0 上运行 shell
# 这样可以确保 CTRL+C 等信号正确传递
if [ -e /dev/ttyAMA0 ]; then
    # ARM virt 机器使用 ttyAMA0
    exec setsid sh -c "exec sh <>/dev/ttyAMA0 >&0 2>&1"
elif [ -e /dev/console ]; then
    # 备用方案：使用 console
    exec setsid sh -c "exec sh <>/dev/console >&0 2>&1"
else
    # 最后的备用方案
    exec sh
fi
EOF

chmod +x init

# 7. 验证必要的工具
echo -e "${YELLOW}验证必要的工具...${NC}"
for tool in nft ipset ip modprobe sh; do
    FOUND=0
    for dir in /bin /sbin /usr/bin /usr/sbin; do
        if [ -x "$dir/$tool" ]; then
            echo -e "  ${GREEN}✓${NC} $tool"
            FOUND=1
            break
        fi
    done
    if [ $FOUND -eq 0 ]; then
        echo -e "  ${YELLOW}⚠${NC} $tool (未找到)"
    fi
done

echo ""

# 8. 清理并重建 output/rootfs
echo -e "${YELLOW}更新 $ROOTFS_DIR...${NC}"

# 完全删除旧的 rootfs（确保清理干净）
if [ -d "$ROOTFS_DIR" ]; then
    # 先卸载可能的挂载点
    umount "$ROOTFS_DIR/proc" 2>/dev/null || true
    umount "$ROOTFS_DIR/sys" 2>/dev/null || true
    umount "$ROOTFS_DIR/dev" 2>/dev/null || true
    # 删除目录
    rm -rf "$ROOTFS_DIR"
fi

# 创建空的 rootfs 目录
mkdir -p "$ROOTFS_DIR"

# 复制合并后的文件系统
echo -e "${YELLOW}复制文件系统到 $ROOTFS_DIR...${NC}"
# 使用 tar 来避免权限问题
cd "$MERGE_DIR"
tar -cf - . | (cd "$ROOTFS_DIR" && tar -xf -)

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ rootfs 更新完成${NC}"

    # 验证模块是否在最终的 rootfs 中
    if [ -d "$ROOTFS_DIR/lib/modules" ]; then
        FINAL_MODULE_COUNT=$(find "$ROOTFS_DIR/lib/modules" -name "*.ko" 2>/dev/null | wc -l)
        echo -e "${GREEN}✓ 最终 rootfs 包含 $FINAL_MODULE_COUNT 个模块${NC}"

        # 显示模块目录结构
        echo -e "${YELLOW}  模块目录:${NC}"
        ls -lh "$ROOTFS_DIR/lib/modules/" 2>/dev/null | head -5
    else
        echo -e "${RED}✗ 警告: 最终 rootfs 中没有 lib/modules 目录！${NC}"
    fi
else
    echo -e "${RED}✗ rootfs 复制失败${NC}"
    rm -rf "$WORKDIR"
    exit 1
fi

# 9. 打包 initramfs
echo -e "${YELLOW}打包 initramfs...${NC}"

# 打包前再次验证模块
if [ -d "$ROOTFS_DIR/lib/modules" ]; then
    PRE_PACK_COUNT=$(find "$ROOTFS_DIR/lib/modules" -name "*.ko" 2>/dev/null | wc -l)
    echo -e "${GREEN}打包前模块数量: $PRE_PACK_COUNT${NC}"
else
    echo -e "${RED}✗ 警告: 打包前 lib/modules 目录不存在！${NC}"
fi

cd "$ROOTFS_DIR"
find . | cpio -o -H newc 2>/dev/null | gzip > "$OUTPUT_DIR/$INITRAMFS_FILE"

# 10. 清理临时目录
cd /
rm -rf "$WORKDIR"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ initramfs 创建成功${NC}"
    echo ""
    echo "========================================="
    echo "构建完成！"
    echo "========================================="
    echo "文件: $OUTPUT_DIR/$INITRAMFS_FILE"
    echo "大小: $(du -h $OUTPUT_DIR/$INITRAMFS_FILE | cut -f1)"
    echo ""

    # 显示包含的软件
    echo "包含的软件:"
    echo "  - nftables (现代防火墙)"
    echo "  - iproute2 (网络配置)"
    echo "  - kmod (模块管理)"
    echo "  - busybox (基础工具)"
    echo "  - 调试工具 (strace, tcpdump, curl)"

    if [ -d "$ROOTFS_DIR/lib/modules" ]; then
        MODULE_COUNT=$(find "$ROOTFS_DIR/lib/modules" -name "*.ko" 2>/dev/null | wc -l)
        echo "  - 内核模块 ($MODULE_COUNT 个)"
    fi

    echo ""
    echo "Rootfs 已更新: $ROOTFS_DIR"
else
    echo -e "${RED}✗ initramfs 创建失败${NC}"
    exit 1
fi
