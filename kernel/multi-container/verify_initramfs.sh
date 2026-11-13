#!/bin/bash
# 验证 initramfs 内容

set -e

INITRAMFS_FILE=${1:-output/initramfs.cpio.gz}

if [ ! -f "$INITRAMFS_FILE" ]; then
    echo "错误: 找不到 initramfs 文件: $INITRAMFS_FILE"
    echo "用法: $0 [initramfs文件路径]"
    exit 1
fi

echo "========================================"
echo "验证 initramfs: $INITRAMFS_FILE"
echo "========================================"
echo ""

# 创建临时目录
TMPDIR=$(mktemp -d)
echo "临时目录: $TMPDIR"
echo ""

# 解压 initramfs
echo "解压 initramfs..."
cd "$TMPDIR"
zcat "$OLDPWD/$INITRAMFS_FILE" | cpio -idm 2>/dev/null

echo "✓ 解压完成"
echo ""

# 检查基本结构
echo "=========================================="
echo "基本目录结构:"
echo "=========================================="
ls -lh "$TMPDIR/" | head -15
echo ""

# 检查 init 脚本
if [ -f "$TMPDIR/init" ]; then
    echo "✓ init 脚本存在"
    ls -lh "$TMPDIR/init"
else
    echo "✗ 警告: init 脚本不存在！"
fi
echo ""

# 检查 lib 目录
echo "=========================================="
echo "lib 目录内容:"
echo "=========================================="
if [ -d "$TMPDIR/lib" ]; then
    ls -lh "$TMPDIR/lib/" | head -10
    echo ""

    # 检查 lib/modules
    if [ -d "$TMPDIR/lib/modules" ]; then
        echo "✓ lib/modules 目录存在"
        echo ""
        echo "模块目录结构:"
        ls -lh "$TMPDIR/lib/modules/"
        echo ""

        # 统计模块数量
        MODULE_COUNT=$(find "$TMPDIR/lib/modules" -name "*.ko" 2>/dev/null | wc -l)
        echo "内核模块数量: $MODULE_COUNT"

        if [ $MODULE_COUNT -gt 0 ]; then
            echo ""
            echo "前 10 个模块:"
            find "$TMPDIR/lib/modules" -name "*.ko" 2>/dev/null | head -10
            echo ""

            # 检查模块依赖文件
            if [ -f "$TMPDIR/lib/modules/"*/modules.dep ]; then
                echo "✓ modules.dep 存在"
                DEP_FILE=$(find "$TMPDIR/lib/modules" -name "modules.dep" | head -1)
                echo "  依赖数量: $(wc -l < "$DEP_FILE")"
            else
                echo "✗ 警告: modules.dep 不存在"
            fi

            if [ -f "$TMPDIR/lib/modules/"*/modules.alias ]; then
                echo "✓ modules.alias 存在"
                ALIAS_FILE=$(find "$TMPDIR/lib/modules" -name "modules.alias" | head -1)
                echo "  别名数量: $(wc -l < "$ALIAS_FILE")"
            else
                echo "✗ 警告: modules.alias 不存在"
            fi
        else
            echo "✗ 警告: 没有找到任何 .ko 模块文件！"
        fi
    else
        echo "✗ 警告: lib/modules 目录不存在！"
    fi
else
    echo "✗ 警告: lib 目录不存在！"
fi
echo ""

# 检查网络工具
echo "=========================================="
echo "网络工具:"
echo "=========================================="
for tool in iptables ip6tables ipset ip tc modprobe lsmod; do
    FOUND=""
    for dir in sbin bin usr/sbin usr/bin; do
        if [ -f "$TMPDIR/$dir/$tool" ]; then
            FOUND="$dir/$tool"
            break
        fi
    done

    if [ -n "$FOUND" ]; then
        echo "✓ $tool: $FOUND"
    else
        echo "✗ $tool: 未找到"
    fi
done
echo ""

# 显示总大小
echo "=========================================="
echo "大小统计:"
echo "=========================================="
echo "initramfs 文件大小: $(du -h "$OLDPWD/$INITRAMFS_FILE" | cut -f1)"
echo "解压后总大小: $(du -sh "$TMPDIR" | cut -f1)"
if [ -d "$TMPDIR/lib/modules" ]; then
    echo "模块目录大小: $(du -sh "$TMPDIR/lib/modules" | cut -f1)"
fi
echo ""

# 清理
cd /
rm -rf "$TMPDIR"

echo "=========================================="
echo "验证完成"
echo "=========================================="
