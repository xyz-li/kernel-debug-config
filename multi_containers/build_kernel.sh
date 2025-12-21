#!/bin/bash
set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Linux 内核编译脚本${NC}"
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
JOBS=${JOBS:-$(nproc)}
OUTPUT_DIR=${OUTPUT_DIR:-/output}
ROOTFS_DIR=${ROOTFS_DIR:-/output/rootfs}
FORCE_RECONFIG=${FORCE_RECONFIG:-no}  # 设置为 yes 强制重新配置
COPY_DTB=${COPY_DTB:-no}  # 设置为 yes 才会复制 DTB 文件
DEBUG_BUILD=${DEBUG_BUILD:-yes}  # 设置为 yes 启用调试优化（-Og），方便单步调试

echo -e "${GREEN}编译配置:${NC}"
echo "  架构: $ARCH"
echo "  交叉编译工具: ${CROSS_COMPILE:-native}"
echo "  并行任务数: $JOBS"
echo "  输出目录: $OUTPUT_DIR"
echo "  Rootfs 目录: $ROOTFS_DIR"
echo "  强制重新配置: $FORCE_RECONFIG"
echo "  复制 DTB 文件: $COPY_DTB"
echo "  调试构建模式: $DEBUG_BUILD"
echo ""

# 设置调试编译标志
if [ "$DEBUG_BUILD" = "yes" ]; then
    # 注意: 不覆盖优化级别（保持内核默认 -O2），避免 BUILD_BUG_ON 编译错误
    # 只添加调试增强标志：
    # -g3: 包含宏定义等额外调试信息（在 -g 基础上增强）
    # -fno-inline-functions-called-once: 防止只调用一次的函数被内联
    # -fno-omit-frame-pointer: 保留帧指针（已在 CONFIG_FRAME_POINTER 启用）
    # -fno-optimize-sibling-calls: 防止尾调用优化，保持完整调用链
    DEBUG_CFLAGS="-g3 -fno-inline-functions-called-once -fno-optimize-sibling-calls"

    # 设置内核编译选项
    export KBUILD_CFLAGS_KERNEL="$DEBUG_CFLAGS"

    echo -e "${YELLOW}启用调试增强模式:${NC}"
    echo "  额外标志: $DEBUG_CFLAGS"
    echo -e "${YELLOW}注意: 保持 -O2 优化以确保编译通过，但增强调试信息${NC}"
    echo ""
else
    DEBUG_CFLAGS=""
fi

# 创建输出目录
mkdir -p "$OUTPUT_DIR"
mkdir -p "$ROOTFS_DIR"

# 配置内核
if [ ! -f ".config" ] || [ "$FORCE_RECONFIG" = "yes" ]; then
    if [ -f ".config" ] && [ "$FORCE_RECONFIG" = "yes" ]; then
        echo -e "${YELLOW}强制重新配置内核（删除现有 .config）...${NC}"
        rm -f .config
    fi

    echo -e "${YELLOW}未找到 .config 文件，生成最小化调试配置...${NC}"

    # 检查是否存在最小化配置文件
    if [ -f "/scripts/minimal_debug.config" ]; then
        echo -e "${GREEN}使用最小化调试配置: minimal_debug.config${NC}"

        # 使用 defconfig 作为基础（而不是 allnoconfig）
        # 这确保了所有基础设施和依赖都被正确启用
        echo -e "${YELLOW}生成基础配置 (defconfig)...${NC}"
        make ARCH=$ARCH ${CROSS_COMPILE:+CROSS_COMPILE=$CROSS_COMPILE} defconfig

        # 应用 minimal_debug.config 中的所有配置
        echo -e "${YELLOW}应用 minimal_debug.config 中的配置...${NC}"

        # 使用内核提供的 merge_config.sh（如果可用）
        if [ -f "scripts/kconfig/merge_config.sh" ]; then
            echo "使用 merge_config.sh 合并配置..."
            ./scripts/kconfig/merge_config.sh -m .config /scripts/minimal_debug.config
        else
            # 备用方案：逐行读取并应用配置
            echo "逐行应用配置..."
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
            done < /scripts/minimal_debug.config
        fi

        # 使用 olddefconfig 解决所有依赖关系
        echo -e "${YELLOW}解决配置依赖关系...${NC}"
        make ARCH=$ARCH ${CROSS_COMPILE:+CROSS_COMPILE=$CROSS_COMPILE} olddefconfig

        echo -e "${GREEN}✓ 配置完成（使用 defconfig + minimal_debug.config）${NC}"
    else
        echo -e "${YELLOW}未找到 minimal_debug.config，使用 defconfig...${NC}"
        make ARCH=$ARCH ${CROSS_COMPILE:+CROSS_COMPILE=$CROSS_COMPILE} defconfig

        # 追加关键配置
        scripts/config --enable CONFIG_VIRTIO
        scripts/config --enable CONFIG_VIRTIO_PCI
        scripts/config --enable CONFIG_VIRTIO_BLK
        scripts/config --enable CONFIG_VIRTIO_NET
        scripts/config --enable CONFIG_INET
        scripts/config --enable CONFIG_DEBUG_INFO
        scripts/config --enable CONFIG_DEBUG_INFO_DWARF5
        scripts/config --enable CONFIG_GDB_SCRIPTS
        scripts/config --enable CONFIG_FRAME_POINTER
        scripts/config --enable CONFIG_KALLSYMS
        scripts/config --enable CONFIG_KALLSYMS_ALL

        make ARCH=$ARCH ${CROSS_COMPILE:+CROSS_COMPILE=$CROSS_COMPILE} olddefconfig
    fi

    echo -e "${GREEN}配置完成${NC}"
else
    echo -e "${GREEN}使用现有的 .config 文件${NC}"
fi

# 验证关键配置项
echo -e "${YELLOW}验证关键配置...${NC}"
MISSING_CONFIGS=""
WARNING_CONFIGS=""

# 必需的配置项
REQUIRED_CONFIGS="CONFIG_VIRTIO CONFIG_VIRTIO_BLK CONFIG_VIRTIO_NET CONFIG_INET CONFIG_DEBUG_INFO"

# Netfilter 相关配置（用于 iptables）
NETFILTER_CONFIGS="CONFIG_NETFILTER CONFIG_NF_TABLES CONFIG_IP_NF_IPTABLES CONFIG_NETFILTER_XTABLES"

# PL011 串口（ARM virt 机器必需）
if [ "$ARCH" = "arm64" ] || [ "$ARCH" = "arm" ]; then
    SERIAL_CONFIGS="CONFIG_SERIAL_AMBA_PL011 CONFIG_SERIAL_AMBA_PL011_CONSOLE"
fi

# 调试配置验证
DEBUG_CONFIGS="CONFIG_DEBUG_KERNEL CONFIG_KGDB CONFIG_KGDB_SERIAL_CONSOLE CONFIG_FTRACE CONFIG_KPROBES CONFIG_PERF_EVENTS"

for config in $REQUIRED_CONFIGS; do
    if ! grep -q "^${config}=y" .config 2>/dev/null; then
        MISSING_CONFIGS="${MISSING_CONFIGS} ${config}"
    fi
done

# 检查 Netfilter 配置
for config in $NETFILTER_CONFIGS; do
    if ! grep -q "^${config}=y" .config 2>/dev/null && ! grep -q "^${config}=m" .config 2>/dev/null; then
        WARNING_CONFIGS="${WARNING_CONFIGS} ${config}"
    fi
done

# 检查串口配置
if [ -n "$SERIAL_CONFIGS" ]; then
    for config in $SERIAL_CONFIGS; do
        if ! grep -q "^${config}=y" .config 2>/dev/null; then
            WARNING_CONFIGS="${WARNING_CONFIGS} ${config}"
        fi
    done
fi

# 检查调试配置
for config in $DEBUG_CONFIGS; do
    if ! grep -q "^${config}=y" .config 2>/dev/null; then
        WARNING_CONFIGS="${WARNING_CONFIGS} ${config}"
    fi
done

if [ -n "$MISSING_CONFIGS" ]; then
    echo -e "${RED}错误: 以下必需配置未启用:${MISSING_CONFIGS}${NC}"
    echo -e "${YELLOW}编译可能失败或功能不完整${NC}"
    exit 1
elif [ -n "$WARNING_CONFIGS" ]; then
    echo -e "${YELLOW}警告: 以下推荐配置未启用:${WARNING_CONFIGS}${NC}"
    echo -e "${YELLOW}某些功能（如 iptables、CTRL+C 或调试功能）可能无法正常工作${NC}"
else
    echo -e "${GREEN}✓ 所有关键配置已启用${NC}"
fi

echo ""

# 编译内核
echo -e "${GREEN}开始编译内核...${NC}"
make ARCH=$ARCH ${CROSS_COMPILE:+CROSS_COMPILE=$CROSS_COMPILE} -j$JOBS

# 编译模块
echo -e "${GREEN}开始编译模块...${NC}"
make ARCH=$ARCH ${CROSS_COMPILE:+CROSS_COMPILE=$CROSS_COMPILE} modules -j$JOBS

# 检查是否有模块被编译
echo ""
echo -e "${YELLOW}检查编译的模块...${NC}"
BUILT_MODULES=$(find . -name "*.ko" 2>/dev/null | wc -l)
if [ "$BUILT_MODULES" -eq 0 ]; then
    echo -e "${YELLOW}⚠ 警告: 没有编译任何内核模块 (.ko 文件)${NC}"
    echo -e "${YELLOW}  所有驱动可能都被编译为内建 (=y)${NC}"
    echo -e "${YELLOW}  如果需要可加载模块，请修改 minimal_debug.config${NC}"
    echo -e "${YELLOW}  将某些 CONFIG_XXX=y 改为 CONFIG_XXX=m${NC}"
else
    echo -e "${GREEN}✓ 编译了 $BUILT_MODULES 个内核模块${NC}"
    echo "  示例模块:"
    find . -name "*.ko" 2>/dev/null | head -5
fi
echo ""

# 安装模块到 rootfs
echo -e "${GREEN}安装模块到 $ROOTFS_DIR...${NC}"

# 显示安装前的状态
if [ -d "$ROOTFS_DIR/lib/modules" ]; then
    PRE_INSTALL_COUNT=$(find "$ROOTFS_DIR/lib/modules" -name "*.ko" 2>/dev/null | wc -l)
    echo -e "${YELLOW}安装前已有 $PRE_INSTALL_COUNT 个模块${NC}"
fi

# 执行 modules_install
make ARCH=$ARCH ${CROSS_COMPILE:+CROSS_COMPILE=$CROSS_COMPILE} INSTALL_MOD_PATH="$ROOTFS_DIR" modules_install

# 验证安装结果
echo ""
if [ -d "$ROOTFS_DIR/lib/modules" ]; then
    POST_INSTALL_COUNT=$(find "$ROOTFS_DIR/lib/modules" -name "*.ko" 2>/dev/null | wc -l)
    echo -e "${GREEN}✓ 模块已安装到 $ROOTFS_DIR/lib/modules${NC}"
    echo -e "${GREEN}  安装后模块数量: $POST_INSTALL_COUNT${NC}"

    # 显示已安装的内核版本
    INSTALLED_VERSIONS=$(ls "$ROOTFS_DIR/lib/modules/" 2>/dev/null)
    if [ -n "$INSTALLED_VERSIONS" ]; then
        echo -e "${YELLOW}  已安装的内核版本:${NC}"
        for ver in $INSTALLED_VERSIONS; do
            MODULE_COUNT=$(find "$ROOTFS_DIR/lib/modules/$ver" -name "*.ko" 2>/dev/null | wc -l)
            echo "    - $ver ($MODULE_COUNT 个模块)"
        done
    fi

    # 如果没有模块被安装，显示警告
    if [ $POST_INSTALL_COUNT -eq 0 ]; then
        echo -e "${RED}✗ 警告: modules_install 执行了，但没有任何模块被安装！${NC}"
        echo -e "${YELLOW}  可能原因：${NC}"
        echo -e "${YELLOW}  1. 所有驱动都被编译为内建 (CONFIG_XXX=y)${NC}"
        echo -e "${YELLOW}  2. 没有编译任何模块 (make modules 没有生成 .ko 文件)${NC}"
    fi
else
    echo -e "${RED}✗ 错误: $ROOTFS_DIR/lib/modules 目录不存在！${NC}"
    echo -e "${YELLOW}  modules_install 可能执行失败${NC}"
fi
echo ""

# 生成模块依赖关系
echo -e "${GREEN}生成模块依赖关系...${NC}"
KERNEL_VERSION=$(make -s kernelrelease)
echo -e "${YELLOW}内核版本: $KERNEL_VERSION${NC}"

if [ -d "$ROOTFS_DIR/lib/modules/$KERNEL_VERSION" ]; then
    # 优先使用系统的 depmod（更可靠）
    if command -v depmod >/dev/null 2>&1; then
        echo "使用系统 depmod 生成模块依赖..."
        depmod -b "$ROOTFS_DIR" "$KERNEL_VERSION"
        DEPMOD_STATUS=$?
    # 备用：使用内核源码树中的 depmod.sh
    elif [ -f "scripts/depmod.sh" ]; then
        echo "使用内核源码的 depmod.sh 生成模块依赖..."
        ./scripts/depmod.sh "$ROOTFS_DIR" "$KERNEL_VERSION"
        DEPMOD_STATUS=$?
    else
        echo -e "${RED}错误: depmod 和 depmod.sh 都不可用${NC}"
        echo -e "${YELLOW}提示: modprobe 可能无法工作，需要手动使用 insmod${NC}"
        DEPMOD_STATUS=1
    fi

    # 验证依赖文件是否生成
    if [ $DEPMOD_STATUS -eq 0 ] && [ -f "$ROOTFS_DIR/lib/modules/$KERNEL_VERSION/modules.dep" ]; then
        echo -e "${GREEN}✓ 模块依赖文件已生成${NC}"
        DEP_COUNT=$(wc -l < "$ROOTFS_DIR/lib/modules/$KERNEL_VERSION/modules.dep")
        ALIAS_COUNT=$(wc -l < "$ROOTFS_DIR/lib/modules/$KERNEL_VERSION/modules.alias" 2>/dev/null || echo 0)
        echo "  - modules.dep: $DEP_COUNT 条依赖"
        echo "  - modules.alias: $ALIAS_COUNT 个别名"
    else
        echo -e "${YELLOW}⚠ 警告: modules.dep 未生成或生成失败${NC}"
        echo -e "${YELLOW}  modprobe 可能无法自动加载模块依赖${NC}"
        echo -e "${YELLOW}  你可以使用 insmod 手动加载模块${NC}"
    fi
else
    echo -e "${YELLOW}⚠ 警告: 模块目录不存在: $ROOTFS_DIR/lib/modules/$KERNEL_VERSION${NC}"
fi

echo ""

# 复制内核镜像到输出目录
echo -e "${GREEN}复制内核镜像到 $OUTPUT_DIR...${NC}"

# 查找并复制内核镜像（支持多种架构）
if [ "$ARCH" = "arm64" ]; then
    KERNEL_IMAGE="arch/arm64/boot/Image"
    if [ -f "arch/arm64/boot/Image.gz" ]; then
        cp arch/arm64/boot/Image.gz "$OUTPUT_DIR/"
        echo -e "${GREEN}已复制: Image.gz${NC}"
    fi
    if [ -f "arch/arm64/boot/Image" ]; then
        cp arch/arm64/boot/Image "$OUTPUT_DIR/"
        echo -e "${GREEN}已复制: Image${NC}"
    fi
elif [ "$ARCH" = "arm" ]; then
    KERNEL_IMAGE="arch/arm/boot/zImage"
elif [ "$ARCH" = "x86_64" ] || [ "$ARCH" = "x86" ]; then
    KERNEL_IMAGE="arch/x86/boot/bzImage"
else
    KERNEL_IMAGE="vmlinux"
fi

if [ -f "$KERNEL_IMAGE" ]; then
    cp "$KERNEL_IMAGE" "$OUTPUT_DIR/"
    echo -e "${GREEN}已复制: $(basename $KERNEL_IMAGE)${NC}"
fi

# 复制带调试符号的 vmlinux (用于 GDB 调试)
if [ -f "vmlinux" ]; then
    cp vmlinux "$OUTPUT_DIR/"
    echo -e "${GREEN}已复制: vmlinux (带调试符号)${NC}"
fi

# 复制设备树文件（如果启用）
if [ "$COPY_DTB" = "yes" ]; then
    if [ "$ARCH" = "arm64" ] && [ -d "arch/arm64/boot/dts" ]; then
        echo -e "${GREEN}复制设备树文件...${NC}"
        DTB_COUNT=$(find arch/arm64/boot/dts -name "*.dtb" 2>/dev/null | wc -l)
        if [ "$DTB_COUNT" -gt 0 ]; then
            find arch/arm64/boot/dts -name "*.dtb" -exec cp {} "$OUTPUT_DIR/" \; 2>/dev/null || true
            echo -e "${GREEN}已复制 $DTB_COUNT 个 DTB 文件${NC}"
        fi
    fi

    if [ "$ARCH" = "arm" ] && [ -d "arch/arm/boot/dts" ]; then
        echo -e "${GREEN}复制设备树文件...${NC}"
        DTB_COUNT=$(find arch/arm/boot/dts -name "*.dtb" 2>/dev/null | wc -l)
        if [ "$DTB_COUNT" -gt 0 ]; then
            find arch/arm/boot/dts -name "*.dtb" -exec cp {} "$OUTPUT_DIR/" \; 2>/dev/null || true
            echo -e "${GREEN}已复制 $DTB_COUNT 个 DTB 文件${NC}"
        fi
    fi
else
    echo -e "${YELLOW}跳过复制 DTB 文件（COPY_DTB=$COPY_DTB）${NC}"
fi

# 复制配置文件
cp .config "$OUTPUT_DIR/kernel.config"

# 显示总结
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}编译完成！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "📁 ${GREEN}输出目录结构:${NC}"
echo -e "  内核镜像: ${GREEN}$OUTPUT_DIR${NC}"
echo -e "  内核模块: ${GREEN}$ROOTFS_DIR/lib/modules${NC}"
echo ""
echo -e "${YELLOW}输出文件列表:${NC}"
ls -lh "$OUTPUT_DIR" | grep -v "^d" | awk '{print "  " $9 " (" $5 ")"}'
echo ""
if [ -d "$ROOTFS_DIR/lib/modules" ]; then
    MODULE_VERSION=$(ls "$ROOTFS_DIR/lib/modules/" 2>/dev/null | head -1)
    if [ -n "$MODULE_VERSION" ]; then
        echo -e "${YELLOW}模块版本:${NC} $MODULE_VERSION"
        MODULE_COUNT=$(find "$ROOTFS_DIR/lib/modules/$MODULE_VERSION" -name "*.ko" 2>/dev/null | wc -l)
        echo -e "${YELLOW}模块数量:${NC} $MODULE_COUNT"
    fi
fi
echo ""
echo -e "${GREEN}✓ 所有文件已输出到 $OUTPUT_DIR${NC}"
echo -e "${GREEN}✓ 模块已输出到 $ROOTFS_DIR${NC}"
