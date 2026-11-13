#!/bin/bash
# 验证内核配置是否包含所需的最小功能
# 使用方法: ./verify_config.sh [path/to/.config]

CONFIG_FILE=${1:-.config}
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}错误: 配置文件不存在: $CONFIG_FILE${NC}"
    exit 1
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}内核配置验证${NC}"
echo -e "${GREEN}========================================${NC}"
echo "配置文件: $CONFIG_FILE"
echo ""

# 验证函数
check_config() {
    local config_name=$1
    local description=$2
    local required=${3:-yes}

    if grep -q "^${config_name}=y" "$CONFIG_FILE" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $description ($config_name)"
        return 0
    elif grep -q "^${config_name}=m" "$CONFIG_FILE" 2>/dev/null; then
        echo -e "${YELLOW}⚠${NC} $description ($config_name) - 作为模块"
        return 0
    else
        if [ "$required" = "yes" ]; then
            echo -e "${RED}✗${NC} $description ($config_name) - 缺失 [必需]"
            return 1
        else
            echo -e "${YELLOW}✗${NC} $description ($config_name) - 缺失 [可选]"
            return 0
        fi
    fi
}

FAILED=0

echo -e "${YELLOW}=== VirtIO 支持 (必需) ===${NC}"
check_config "CONFIG_VIRTIO" "VirtIO 核心" "yes" || FAILED=1
check_config "CONFIG_VIRTIO_PCI" "VirtIO PCI 总线" "yes" || FAILED=1
check_config "CONFIG_VIRTIO_BLK" "VirtIO 块设备" "yes" || FAILED=1
check_config "CONFIG_VIRTIO_NET" "VirtIO 网络设备" "yes" || FAILED=1
check_config "CONFIG_VIRTIO_RING" "VirtIO Ring" "no"
echo ""

echo -e "${YELLOW}=== 网络支持 (必需) ===${NC}"
check_config "CONFIG_NET" "网络子系统" "yes" || FAILED=1
check_config "CONFIG_INET" "TCP/IP 协议栈" "yes" || FAILED=1
check_config "CONFIG_PACKET" "Packet socket" "no"
check_config "CONFIG_UNIX" "Unix domain socket" "no"
check_config "CONFIG_NETDEVICES" "网络设备支持" "yes" || FAILED=1
echo ""

echo -e "${YELLOW}=== Netfilter/iptables 支持 (必需) ===${NC}"
check_config "CONFIG_NETFILTER" "Netfilter 核心" "yes" || FAILED=1
check_config "CONFIG_NF_TABLES" "nf_tables (现代 iptables)" "yes" || FAILED=1
check_config "CONFIG_NF_CONNTRACK" "连接跟踪" "yes" || FAILED=1
check_config "CONFIG_NF_NAT" "NAT 支持" "no"
check_config "CONFIG_IP_NF_IPTABLES" "IPv4 iptables" "yes" || FAILED=1
check_config "CONFIG_IP_NF_FILTER" "IPv4 包过滤" "yes" || FAILED=1
check_config "CONFIG_IP_NF_NAT" "IPv4 NAT" "no"
check_config "CONFIG_IP6_NF_IPTABLES" "IPv6 ip6tables" "no"
check_config "CONFIG_IP_SET" "IP Set 支持" "no"
check_config "CONFIG_NETFILTER_XTABLES" "Xtables 扩展" "yes" || FAILED=1
echo ""

echo -e "${YELLOW}=== 调试支持 (必需) ===${NC}"
check_config "CONFIG_DEBUG_INFO" "调试信息" "yes" || FAILED=1
check_config "CONFIG_DEBUG_INFO_DWARF5" "DWARF5 调试格式" "no"
check_config "CONFIG_GDB_SCRIPTS" "GDB 脚本" "no"
check_config "CONFIG_FRAME_POINTER" "帧指针" "no"
check_config "CONFIG_KALLSYMS" "内核符号表" "yes" || FAILED=1
check_config "CONFIG_KALLSYMS_ALL" "完整符号表" "no"
check_config "CONFIG_DEBUG_KERNEL" "内核调试" "no"
check_config "CONFIG_MAGIC_SYSRQ" "Magic SysRq 键" "no"
echo ""

echo -e "${YELLOW}=== 文件系统 (推荐) ===${NC}"
check_config "CONFIG_PROC_FS" "procfs" "no"
check_config "CONFIG_SYSFS" "sysfs" "no"
check_config "CONFIG_TMPFS" "tmpfs" "no"
check_config "CONFIG_DEVTMPFS" "devtmpfs" "no"
check_config "CONFIG_EXT4_FS" "ext4" "no"
echo ""

echo -e "${YELLOW}=== 块设备支持 ===${NC}"
check_config "CONFIG_BLK_DEV" "块设备支持" "no"
check_config "CONFIG_BLK_DEV_LOOP" "Loop 设备" "no"
echo ""

echo -e "${YELLOW}=== 模块支持 ===${NC}"
check_config "CONFIG_MODULES" "可加载模块" "no"
echo ""

echo -e "${GREEN}========================================${NC}"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ 配置验证通过！${NC}"
    echo -e "${GREEN}所有必需的功能都已启用${NC}"
    exit 0
else
    echo -e "${RED}✗ 配置验证失败！${NC}"
    echo -e "${RED}缺少必需的配置项${NC}"
    exit 1
fi
