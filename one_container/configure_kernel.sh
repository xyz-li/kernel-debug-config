#!/bin/bash
set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Linux 内核配置脚本${NC}"
echo -e "${GREEN}========================================${NC}"

# 检查是否在内核源码目录
if [ ! -f "Makefile" ] || ! grep -q "VERSION" Makefile 2>/dev/null; then
    echo -e "${RED}错误: 未找到 Linux 内核源码的 Makefile${NC}"
    echo -e "${YELLOW}请确保将此脚本放在内核源码根目录下运行${NC}"
    exit 1
fi

# 配置变量
ARCH=${ARCH:-arm64}
CROSS_COMPILE=${CROSS_COMPILE:-}
CONFIG_FILE=${CONFIG_FILE:-minimal_debug.config}
FORCE_RECONFIG=${FORCE_RECONFIG:-no}

echo -e "${GREEN}配置参数:${NC}"
echo "  架构: $ARCH"
echo "  交叉编译工具: ${CROSS_COMPILE:-native}"
echo "  配置文件: $CONFIG_FILE"
echo "  强制重新配置: $FORCE_RECONFIG"
echo ""

# 检查是否需要重新配置
if [ -f ".config" ] && [ "$FORCE_RECONFIG" != "yes" ]; then
    echo -e "${YELLOW}已存在 .config 文件${NC}"
    echo -e "${YELLOW}是否删除并重新配置? (y/N)${NC}"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo -e "${GREEN}保留现有配置${NC}"
        exit 0
    fi
    rm -f .config
    echo -e "${YELLOW}已删除现有 .config${NC}"
elif [ "$FORCE_RECONFIG" = "yes" ] && [ -f ".config" ]; then
    echo -e "${YELLOW}强制重新配置，删除现有 .config${NC}"
    rm -f .config
fi

# 生成基础配置
echo -e "${GREEN}生成基础配置 (defconfig)...${NC}"
make ARCH=$ARCH ${CROSS_COMPILE:+CROSS_COMPILE=$CROSS_COMPILE} defconfig

# 检查配置文件是否存在
if [ -f "/scripts/$CONFIG_FILE" ]; then
    CONFIG_SOURCE="/scripts/$CONFIG_FILE"
elif [ -f "./$CONFIG_FILE" ]; then
    CONFIG_SOURCE="./$CONFIG_FILE"
else
    echo -e "${RED}错误: 配置文件不存在: $CONFIG_FILE${NC}"
    echo -e "${YELLOW}请提供有效的配置文件路径${NC}"
    exit 1
fi

echo -e "${GREEN}应用配置文件: $CONFIG_SOURCE${NC}"

# 使用 merge_config.sh 合并配置（如果可用）
if [ -f "scripts/kconfig/merge_config.sh" ]; then
    echo -e "${GREEN}使用 merge_config.sh 合并配置...${NC}"
    ./scripts/kconfig/merge_config.sh -m .config "$CONFIG_SOURCE"
else
    echo -e "${YELLOW}merge_config.sh 不可用，使用 scripts/config 工具...${NC}"

    # 逐行读取并应用配置
    while IFS= read -r line; do
        # 跳过注释和空行
        if [[ "$line" =~ ^#.*$ ]] || [[ -z "$line" ]]; then
            continue
        fi

        # 处理 CONFIG_XXX=y 格式
        if [[ "$line" =~ ^CONFIG_([A-Z0-9_]+)=y$ ]]; then
            config_name="${BASH_REMATCH[1]}"
            scripts/config --enable "CONFIG_$config_name"
        # 处理 CONFIG_XXX=m 格式
        elif [[ "$line" =~ ^CONFIG_([A-Z0-9_]+)=m$ ]]; then
            config_name="${BASH_REMATCH[1]}"
            scripts/config --module "CONFIG_$config_name"
        # 处理 # CONFIG_XXX is not set 格式
        elif [[ "$line" =~ ^#\ CONFIG_([A-Z0-9_]+)\ is\ not\ set$ ]]; then
            config_name="${BASH_REMATCH[1]}"
            scripts/config --disable "CONFIG_$config_name"
        # 处理 CONFIG_XXX=数字 或字符串
        elif [[ "$line" =~ ^CONFIG_([A-Z0-9_]+)=(.+)$ ]]; then
            config_name="${BASH_REMATCH[1]}"
            config_value="${BASH_REMATCH[2]}"
            scripts/config --set-val "CONFIG_$config_name" "$config_value"
        fi
    done < "$CONFIG_SOURCE"
fi

# 解决依赖关系
echo -e "${GREEN}解决配置依赖关系...${NC}"
make ARCH=$ARCH ${CROSS_COMPILE:+CROSS_COMPILE=$CROSS_COMPILE} olddefconfig

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}配置完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}配置文件已生成: .config${NC}"
echo ""
echo -e "${GREEN}后续步骤:${NC}"
echo -e "  1. 验证配置: ${YELLOW}./verify_config.sh${NC}"
echo -e "  2. 编译内核: ${YELLOW}./build_kernel.sh${NC}"
echo ""
