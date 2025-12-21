#!/bin/bash
# 快速诊断 kernel modules 问题

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}========================================"
echo "Kernel Modules 诊断工具"
echo -e "========================================${NC}"
echo ""

# 1. 检查 output/rootfs/lib/modules 目录
echo -e "${YELLOW}[1] 检查 output/rootfs/lib/modules 目录${NC}"
if [ -d "output/rootfs/lib/modules" ]; then
    echo -e "${GREEN}✓ 目录存在${NC}"

    # 列出内核版本
    VERSIONS=$(ls output/rootfs/lib/modules/ 2>/dev/null)
    if [ -n "$VERSIONS" ]; then
        echo -e "${YELLOW}已安装的内核版本:${NC}"
        for ver in $VERSIONS; do
            echo "  - $ver"
        done

        # 统计模块数量
        MODULE_COUNT=$(find output/rootfs/lib/modules/ -name "*.ko" 2>/dev/null | wc -l)
        echo ""
        echo -e "${YELLOW}模块总数: ${GREEN}$MODULE_COUNT${NC}"

        if [ $MODULE_COUNT -eq 0 ]; then
            echo -e "${RED}✗ 没有找到任何 .ko 模块文件！${NC}"
        else
            echo ""
            echo -e "${YELLOW}前 10 个模块:${NC}"
            find output/rootfs/lib/modules/ -name "*.ko" 2>/dev/null | head -10
        fi
    else
        echo -e "${RED}✗ 没有内核版本目录${NC}"
    fi
else
    echo -e "${RED}✗ output/rootfs/lib/modules 目录不存在${NC}"
fi

echo ""
echo -e "${YELLOW}[2] 检查内核源码中编译的模块${NC}"

# 进入内核源码目录（假设是挂载的）
KERNEL_SOURCE="/Volumes/linux/linux-6.12.63"
if [ -d "$KERNEL_SOURCE" ]; then
    echo -e "${GREEN}✓ 找到内核源码: $KERNEL_SOURCE${NC}"

    cd "$KERNEL_SOURCE"

    # 检查是否有 .config 文件
    if [ -f ".config" ]; then
        echo -e "${GREEN}✓ 找到 .config 文件${NC}"

        # 检查模块配置
        MODULE_CONFIGS=$(grep "=m$" .config 2>/dev/null | wc -l)
        echo -e "${YELLOW}配置为模块的选项数量: ${GREEN}$MODULE_CONFIGS${NC}"

        if [ $MODULE_CONFIGS -gt 0 ]; then
            echo ""
            echo -e "${YELLOW}前 10 个模块配置:${NC}"
            grep "=m$" .config 2>/dev/null | head -10
        fi
    else
        echo -e "${RED}✗ 未找到 .config 文件${NC}"
    fi

    echo ""
    # 检查已编译的 .ko 文件
    BUILT_KO=$(find . -name "*.ko" 2>/dev/null | wc -l)
    echo -e "${YELLOW}已编译的 .ko 文件数量: ${GREEN}$BUILT_KO${NC}"

    if [ $BUILT_KO -eq 0 ]; then
        echo -e "${RED}✗ 内核源码目录中没有 .ko 文件！${NC}"
        echo -e "${YELLOW}  这意味着没有编译任何模块${NC}"
    else
        echo ""
        echo -e "${YELLOW}前 10 个已编译的模块:${NC}"
        find . -name "*.ko" 2>/dev/null | head -10
    fi

    cd - > /dev/null
else
    echo -e "${RED}✗ 未找到内核源码目录: $KERNEL_SOURCE${NC}"
    echo -e "${YELLOW}  请根据你的实际路径修改此脚本${NC}"
fi

echo ""
echo -e "${YELLOW}[3] 建议的诊断步骤${NC}"
echo ""
echo "如果没有模块被安装，请按以下步骤排查："
echo ""
echo "1. 检查 minimal_debug.config 中是否有 =m 的配置"
echo "   grep '=m' minimal_debug.config | wc -l"
echo ""
echo "2. 重新编译内核并查看输出"
echo "   docker-compose run --rm -e FORCE_RECONFIG=yes kernel-builder /scripts/build_kernel.sh"
echo ""
echo "   关键输出："
echo "   - '检查编译的模块...' 部分应该显示 > 0 个模块"
echo "   - '安装后模块数量' 应该 > 0"
echo ""
echo "3. 如果仍然没有模块，检查内核配置"
echo "   docker-compose run --rm kernel-builder bash"
echo "   grep '=m' /kernel/.config | head -20"
echo ""
echo -e "${GREEN}========================================"
echo "诊断完成"
echo -e "========================================${NC}"
