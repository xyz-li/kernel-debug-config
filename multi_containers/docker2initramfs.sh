#!/bin/bash
# 保存为 docker2initramfs.sh
#set -xe

IMAGE=${1:-"alpine:latest"}
OUTPUT=${2:-"initramfs.cpio.gz"}

PWD_DIR=$(pwd)
OUTPUT_ROOTFS="$PWD_DIR/output/rootfs"
echo "从Docker镜像创建initramfs: $IMAGE"
echo "输出目录: $OUTPUT_ROOTFS"

# 1. 创建临时工作目录
WORKDIR=$(mktemp -d)
echo "工作目录: $WORKDIR"
cd $WORKDIR

# 2. 创建并导出容器
CONTAINER_ID=$(docker create $IMAGE 2>/dev/null)
if [ $? -ne 0 ]; then
    echo "错误: 无法创建容器，请检查镜像名称"
    exit 1
fi

echo "容器ID: $CONTAINER_ID"

# 3. 导出容器文件系统到tar包
docker export $CONTAINER_ID > rootfs.tar
if [ $? -ne 0 ]; then
    echo "错误: 导出失败"
    docker rm $CONTAINER_ID >/dev/null 2>&1
    exit 1
fi

# 4. 创建 rootfs 目录并解压
mkdir rootfs
tar -xf rootfs.tar -C rootfs


# 5. 清理临时文件
rm -f rootfs.tar

# 6. 切换到 rootfs 目录进行配置
cd rootfs

# 7. 创建 init 脚本（关键！）
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
}
mkdir -p /dev/pts && mount -t devpts devpts /dev/pts 2>/dev/null
mount -t tmpfs tmpfs /tmp

# 2. 设置控制台
exec 0</dev/console
exec 1>/dev/console
exec 2>/dev/console

# 3. 设置主机名和环境
hostname docker-initramfs

# 4. 显示启动信息
echo "========================================="
echo "System initialized successfully"
echo "PID 1 (init) is running"
echo "========================================="
echo ""
cat /proc/version 2>/dev/null || echo "Linux kernel started"
echo ""
echo "System information:"
echo "  Hostname: $(hostname)"
echo "  Uptime: $(cat /proc/uptime | cut -d' ' -f1)s"
echo ""
echo "Init process will now wait indefinitely..."
echo "Press Ctrl+Alt+Del to reboot (if configured)"
echo ""

exec /bin/sh
EOF

chmod +x init

# 8. 打包为initramfs
echo "正在打包initramfs..."
find . | cpio -o -H newc 2>/dev/null | gzip -9 > ../$OUTPUT

# 9. 合并到 output/rootfs 目录
echo "正在合并 rootfs 到 $OUTPUT_ROOTFS ..."

# 确保 output 目录存在
mkdir -p "$OUTPUT_ROOTFS"

# 复制 Alpine rootfs 到目标目录，但跳过 lib 目录（保留现有的内核模块）
echo "复制 Alpine rootfs（保留现有的 lib 目录）..."
for item in *; do
    if [ "$item" != "lib" ]; then
        # 删除目标位置的旧文件/目录（除了 lib）
        [ -e "$OUTPUT_ROOTFS/$item" ] && rm -rf "$OUTPUT_ROOTFS/$item"
        # 复制新文件
        cp -a "$item" "$OUTPUT_ROOTFS/"
    else
        # 对于 lib 目录，只复制 Alpine 的库文件，不覆盖 modules
        if [ -d "lib" ]; then
            echo "合并 lib 目录（保留 modules 子目录）..."
            mkdir -p "$OUTPUT_ROOTFS/lib"
            # 复制 lib 下的所有内容，但不覆盖已存在的文件（如 modules/）
            cp -an lib/* "$OUTPUT_ROOTFS/lib/" 2>/dev/null || true
        fi
    fi
done

echo "✓ rootfs 合并完成"

# 10. 从 output/rootfs 重新打包 initramfs
echo "从 $OUTPUT_ROOTFS 重新打包 initramfs..."
cd "$OUTPUT_ROOTFS"
#find . | cpio -o -H newc 2>/dev/null | gzip -9 > "$WORKDIR/$OUTPUT"
find . | cpio -o -H newc 2>/dev/null | gzip  > "$WORKDIR/$OUTPUT"
cd "$WORKDIR"

# 11. 移动 initramfs 到 output 目录
echo "移动 initramfs 到 output 目录..."
OUTPUT_FILE="$PWD_DIR/output/$OUTPUT"
[ -e "$OUTPUT_FILE" ] && rm "$OUTPUT_FILE"
mv $OUTPUT "$PWD_DIR/output/"
cd "$PWD_DIR"

# 11. 清理临时容器和目录
docker rm $CONTAINER_ID >/dev/null 2>&1
rm -rf "$WORKDIR"

echo ""
echo "========================================="
echo "✅ 完成！"
echo "========================================="
echo "📦 initramfs: $PWD_DIR/output/$OUTPUT ($(du -h $PWD_DIR/output/$OUTPUT | cut -f1))"
echo "📁 rootfs: $OUTPUT_ROOTFS"
echo ""

# 显示 lib 目录信息
if [ -d "$OUTPUT_ROOTFS/lib/modules" ]; then
    MODULE_COUNT=$(find "$OUTPUT_ROOTFS/lib/modules" -name "*.ko" 2>/dev/null | wc -l)
    echo "ℹ️  lib/modules 目录包含 $MODULE_COUNT 个内核模块"
fi

echo ""
echo "ℹ️  此initramfs启动后只会运行PID 1进程，不会启动shell或其他服务"
echo ""
echo "目录结构:"
echo "  output/"
echo "  ├── $OUTPUT"
echo "  └── rootfs/"
echo "      ├── bin/"
echo "      ├── lib/        (包含内核模块)"
echo "      ├── init        (PID 1 进程)"
echo "      └── ..."
