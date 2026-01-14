# Linux 内核 Docker 编译环境使用指南

## 目录

- [项目概述](#项目概述)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [准备工作](#准备工作)
- [两个构建服务](#两个构建服务)
- [详细构建步骤](#详细构建步骤)
  - [方式一：使用 Docker Compose（推荐）](#方式一使用-docker-compose推荐)
  - [方式二：使用 Docker 命令](#方式二使用-docker-命令)
- [Initramfs 构建指南](#initramfs-构建指南)
- [配置选项](#配置选项)
- [自定义内核配置](#自定义内核配置)
- [编译输出](#编译输出)
- [启动测试](#启动测试)
- [重新编译指南](#重新编译指南)
- [CTRL+C 信号传递修复](#ctrlc-信号传递修复)
- [常见问题](#常见问题)
- [高级用法](#高级用法)
- [参考资料](#参考资料)

## 项目概述

使用 Docker Compose 构建完整的 Linux 内核开发环境，包含：
- 内核编译（支持 ARM64/ARM/x86_64）
- 增强版 initramfs（包含 iptables、网络工具、调试工具）
- 内核模块管理
- QEMU 测试环境

## 目录结构

```
.
├── Dockerfile                  # 内核编译环境
├── Dockerfile.initramfs        # Initramfs 构建环境
├── docker-compose.yml          # Docker Compose 配置
├── build_kernel.sh             # 内核编译脚本
├── build_initramfs.sh          # Initramfs 构建脚本
├── configure_kernel.sh         # 内核配置脚本
├── verify_config.sh            # 配置验证脚本
├── minimal_debug.config        # 最小化调试配置
├── docker2initramfs.sh         # Alpine rootfs 生成脚本（遗留）
└── output/                     # 所有编译产物输出目录
    ├── Image                   # 内核镜像
    ├── Image.gz                # 压缩的内核镜像
    ├── vmlinux                 # 带调试符号的内核
    ├── initramfs.cpio.gz       # 完整的 initramfs
    ├── kernel.config           # 内核配置
    └── rootfs/                 # rootfs 源目录
        ├── bin/, sbin/         # 系统工具
        ├── lib/
        │   ├── modules/        # 内核模块
        │   └── *.so            # 共享库
        └── init                # Init 脚本
```

## 快速开始

### 完整构建流程（内核 + Initramfs）

```bash
# 1. 构建 Docker 镜像
docker-compose build

# 2. 编译内核和模块
# 2.1 使用现有 config
docker-compose run --rm kernel-builder /scripts/build_kernel.sh
# 2.2 强制重新 config
docker-compose run --rm -e FORCE_RECONFIG=yes kernel-builder /scripts/build_kernel.sh

# 3. 构建 initramfs（包含 nft、网络工具等）
docker-compose run --rm initramfs-builder /scripts/build_initramfs.sh

# 在 M1 上面使用 hvf 时，gdb 调试无法断点
# 4. 启动测试
qemu-system-aarch64 \
  -machine virt \
  -cpu max \
  -smp 4 \
  -m 2G \
  -kernel output/Image \
  -initrd output/initramfs.cpio.gz \
  -append "console=ttyAMA0 earlycon nokaslr init=/init" \
  -device virtio-net-device,netdev=net0 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -nographic \
  -serial mon:stdio -s -S

# 退出 QEMU: 按 CTRL+A 然后按 X
# CTRL+C 可以中断虚拟机内的程序（如 ping）
```

## 准备工作

### 1. 获取 Linux 内核源码

将 Linux 内核源码放到 `linux-source` 目录或其它目录，修改 docker-compose.yaml 中的挂载点：

```bash
# 方法一：下载官方源码
wget https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.6.tar.xz
tar -xf linux-6.6.tar.xz
mv linux-6.6 linux-source

# 方法二：克隆 Git 仓库
git clone --depth=1 https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git linux-source

# 方法三：使用已有源码
cp -r /path/to/your/kernel/source linux-source
```

### 2. 确保 output 目录存在

```bash
mkdir -p output/rootfs
```

## 两个构建服务

### 1. kernel-builder
编译 Linux 内核和模块

**功能**:
- 编译内核镜像（Image, Image.gz, vmlinux）
- 编译内核模块（.ko 文件）
- 生成模块依赖关系（modules.dep）
- 输出到 `output/` 目录

**使用**:
```bash
docker-compose run --rm kernel-builder /scripts/build_kernel.sh
```

### 2. initramfs-builder
构建增强版 initramfs

**功能**:
- 创建完整的 rootfs 文件系统
- 预装网络工具（iptables, iproute2, ipset）
- 预装调试工具（strace, tcpdump, curl, wget）
- 预装模块管理工具（kmod）
- 自动生成 init 脚本（加载模块、配置网络、初始化防火墙）
- 打包为 initramfs.cpio.gz

**使用**:
```bash
docker-compose run --rm initramfs-builder /scripts/build_initramfs.sh
```

**包含的软件**:
- iptables/ip6tables - 防火墙
- iproute2 - 网络配置（ip, tc, ss）
- ipset - IP 集合管理
- kmod - 模块管理（modprobe, lsmod）
- strace - 系统调用跟踪
- tcpdump - 网络抓包
- curl/wget - HTTP 客户端

## 详细构建步骤

### 方式一：使用 Docker Compose（推荐）

#### 1. 构建 Docker 镜像

```bash
docker-compose build
```

#### 2. 启动容器并进入交互式终端

```bash
docker-compose run --rm kernel-builder
```

#### 3. 在容器内编译内核

```bash
# 在容器内执行
/scripts/build_kernel.sh
```

或者一条命令完成：

```bash
docker-compose run --rm kernel-builder /scripts/build_kernel.sh
```

### 方式二：使用 Docker 命令

#### 1. 构建镜像

```bash
docker build -t linux-kernel-builder .
```

#### 2. 运行编译

```bash
docker run --rm \
  -v $(pwd)/linux-source:/kernel:rw \
  -v $(pwd):/output:rw \
  -v $(pwd)/rootfs:/output/rootfs:rw \
  -v $(pwd)/build_kernel.sh:/build_kernel.sh:ro \
  -e ARCH=arm64 \
  -e JOBS=8 \
  -e OUTPUT_DIR=/output \
  -e ROOTFS_DIR=/output/rootfs \
  -w /kernel \
  linux-kernel-builder \
  /build_kernel.sh
```

## Initramfs 构建指南

### 包含的软件

#### 网络工具
- **iptables** - IPv4 防火墙
- **ip6tables** - IPv6 防火墙
- **ipset** - IP 集合管理
- **iproute2** - 高级网络配置 (ip, tc, ss)
- **bridge-utils** - 网桥管理

#### 系统工具
- **busybox** - 基础 Unix 工具集
- **kmod** - 内核模块管理 (modprobe, lsmod, insmod, rmmod)
- **util-linux** - 系统工具 (mount, umount, etc)

#### 调试工具
- **strace** - 系统调用跟踪
- **tcpdump** - 网络抓包
- **curl/wget** - HTTP 客户端
- **htop** - 进程监控

#### 文件系统工具
- **e2fsprogs** - ext2/3/4 文件系统工具
- **dosfstools** - FAT 文件系统工具

### 自定义 initramfs

#### 添加额外的软件包

编辑 `Dockerfile.initramfs`：

```dockerfile
RUN apk add --no-cache \
    iptables \
    # 添加你需要的软件包
    your-package \
    another-package
```

然后重新构建：

```bash
docker-compose build initramfs-builder
docker-compose run --rm initramfs-builder /scripts/build_initramfs.sh
```

#### 修改 init 脚本

编辑 `build_initramfs.sh` 中的 init 脚本部分，或者直接编辑 `output/rootfs/init`。

修改后重新打包：

```bash
docker-compose run --rm initramfs-builder /scripts/build_initramfs.sh
```

### 验证 initramfs 内容

```bash
# 解压查看内容
mkdir -p /tmp/initramfs-test
cd /tmp/initramfs-test
zcat /path/to/output/initramfs.cpio.gz | cpio -idmv

# 查看包含的工具
ls -lh sbin/iptables
ls -lh bin/ip
ls -lh lib/modules/

# 查看 init 脚本
cat init
```

## 配置选项

在 `docker-compose.yml` 或 Docker 命令中可以设置以下环境变量：

- `ARCH`: 目标架构
  - `arm64` (默认)
  - `arm`
  - `x86_64`
  - `x86`

- `CROSS_COMPILE`: 交叉编译工具链前缀
  - ARM64: `aarch64-linux-gnu-`
  - ARM: `arm-linux-gnueabi-`
  - 留空表示本地编译

- `JOBS`: 并行编译任务数（默认为 CPU 核心数）

- `OUTPUT_DIR`: 内核镜像输出目录（默认 `/output`）

- `ROOTFS_DIR`: 模块输出目录（默认 `/output/rootfs`）

- `FORCE_RECONFIG`: 强制重新配置内核
  - `no` (默认): 使用现有 .config 文件
  - `yes`: 删除现有 .config 并重新应用 minimal_debug.config

- `COPY_DTB`: 是否复制设备树文件到 output 目录
  - `no` (默认): 不复制 .dtb 文件
  - `yes`: 复制所有 .dtb 文件到 output 目录

**示例**：

```bash
# 强制重新配置并编译
docker-compose run --rm -e FORCE_RECONFIG=yes kernel-builder /scripts/build_kernel.sh

# 编译并复制 DTB 文件
docker-compose run --rm -e COPY_DTB=yes kernel-builder /scripts/build_kernel.sh

# 组合多个环境变量
docker-compose run --rm -e FORCE_RECONFIG=yes -e COPY_DTB=yes kernel-builder /scripts/build_kernel.sh
```

## 自定义内核配置

### 方法一：在容器内使用 menuconfig

```bash
# 启动容器
docker-compose run --rm kernel-builder

# 在容器内配置
make ARCH=arm64 menuconfig

# 编译
/build_kernel.sh
```

### 方法二：使用已有配置文件

```bash
# 将配置文件复制到源码目录
cp your_config linux-source/.config

# 然后编译
docker-compose run --rm kernel-builder /build_kernel.sh
```

## 编译输出

编译完成后，所有文件输出到 `output/` 目录：

### 内核文件

- **Image** - ARM64 未压缩内核镜像
- **Image.gz** - ARM64 压缩内核镜像
- **vmlinux** - 带完整调试符号的内核（用于 GDB 调试）
- **kernel.config** - 编译使用的内核配置
- **\*.dtb** - 设备树文件（ARM 架构）

### Initramfs 文件

- **initramfs.cpio.gz** - 完整的 initramfs，包含：
  - Alpine 基础系统
  - 网络工具（iptables, iproute2）
  - 调试工具（strace, tcpdump）
  - 内核模块
  - 自定义 init 脚本

### Rootfs 目录

```
output/rootfs/
├── bin/, sbin/              # 基础命令
├── usr/bin/, usr/sbin/      # 用户命令
├── lib/
│   ├── modules/             # 内核模块
│   │   └── 6.12.63/
│   │       ├── kernel/      # 驱动模块
│   │       ├── modules.dep  # 模块依赖
│   │       └── modules.alias
│   └── *.so                 # 共享库
├── etc/                     # 配置文件
├── init                     # Init 脚本
└── ...
```

## 启动测试

### 使用 QEMU 启动

```bash
qemu-system-aarch64 \
  -machine virt,accel=hvf \
  -cpu host \
  -smp 4 \
  -m 2G \
  -kernel output/Image \
  -initrd output/initramfs.cpio.gz \
  -append "console=ttyAMA0 earlycon init=/init" \
  -device virtio-net-device,netdev=net0 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -nographic \
  -serial mon:stdio

# 退出 QEMU: 按 CTRL+A 然后按 X
# CTRL+C 可以中断虚拟机内的程序（如 ping）
```

### QEMU 控制快捷键

使用 `-nographic` 模式时，QEMU 有特殊的控制快捷键：

| 快捷键 | 功能 |
|--------|------|
| **CTRL+A X** | 退出 QEMU（最常用） |
| **CTRL+A H** | 显示帮助信息 |
| **CTRL+A C** | 切换到 QEMU monitor |
| **CTRL+A S** | 向虚拟机发送 BREAK 信号 |
| **CTRL+C** | 中断虚拟机内的程序（如 ping） |

**注意事项：**
- **退出 QEMU**: 使用 **CTRL+A** 然后按 **X**
- **中断虚拟机内程序**: 直接使用 **CTRL+C**（添加 `-serial mon:stdio` 后）
- 或者在另一个终端使用 `killall qemu-system-aarch64`

### 启动后可用的命令

系统启动后，initramfs 会自动：
1. **挂载文件系统** - proc, sys, dev, tmp
2. **加载内核模块** - virtio_pci, virtio_net, virtio_blk
3. **配置网络** - 启动网卡，尝试 DHCP
4. **初始化 iptables** - 清空规则，设置默认策略
5. **启动 Shell** - 进入交互式环境

你可以使用：

```bash
# 网络配置
ip addr show
ip link show
ip route show

# 防火墙规则
iptables -L -v -n
iptables -t nat -L -v -n

# 添加防火墙规则示例
iptables -A INPUT -p tcp --dport 80 -j ACCEPT
iptables -A INPUT -p tcp --dport 443 -j ACCEPT

# 模块管理
lsmod
modprobe <module_name>
modinfo <module_name>

# 网络调试
tcpdump -i eth0
ss -tuln
netstat -tuln

# 进程调试
strace <command>
htop
```

## 重新编译指南

### 问题说明

如果之前已经编译过内核，内核源码目录中会存在 `.config` 文件。`build_kernel.sh` 脚本会直接使用现有的 `.config` 文件，**不会自动应用** `minimal_debug.config` 中的新配置。

### 解决方案

#### 方法 1：使用 FORCE_RECONFIG 环境变量（推荐）

使用 `FORCE_RECONFIG=yes` 强制重新配置并应用 `minimal_debug.config` 中的所有配置：

```bash
docker-compose run --rm -e FORCE_RECONFIG=yes kernel-builder /scripts/build_kernel.sh
```

这会：
1. 删除现有的 `.config` 文件
2. 从 `defconfig` 开始
3. 应用 `minimal_debug.config` 中的所有配置（包括新添加的 Netfilter/iptables 和 PL011 串口配置）
4. 编译内核

#### 方法 2：手动删除 .config（备选）

进入容器手动删除配置文件：

```bash
# 1. 进入容器
docker-compose run --rm kernel-builder bash

# 2. 删除现有配置
rm -f /kernel/.config

# 3. 运行编译脚本
/scripts/build_kernel.sh
```

#### 方法 3：修改 docker-compose.yml（永久设置）

如果希望每次都重新配置，可以在 `docker-compose.yml` 中取消注释：

```yaml
environment:
  - FORCE_RECONFIG=yes  # 取消注释这一行
```

然后正常运行：
```bash
docker-compose run --rm kernel-builder /scripts/build_kernel.sh
```

### 完整的重新编译流程

为了应用所有最新的修复（Netfilter、PL011 串口、CTRL+C 支持），请按照以下步骤操作：

#### 1. 强制重新编译内核

```bash
docker-compose run --rm -e FORCE_RECONFIG=yes kernel-builder /scripts/build_kernel.sh
```

**验证要点**：
- 配置验证部分应该显示 "✓ 所有关键配置已启用"
- 如果有警告，检查是否缺少 Netfilter 或 PL011 配置

#### 2. 重新构建 initramfs

```bash
docker-compose run --rm initramfs-builder /scripts/build_initramfs.sh
```

**验证要点**：
- 应该看到 "✓ initramfs 创建成功"
- 包含的软件列表中应该有 iptables、iproute2、kmod 等

#### 3. 启动 QEMU 测试

```bash
qemu-system-aarch64 \
  -machine virt,accel=hvf \
  -cpu host \
  -smp 4 \
  -m 2G \
  -kernel output/Image \
  -initrd output/initramfs.cpio.gz \
  -append "console=ttyAMA0 earlycon init=/init" \
  -device virtio-net-device,netdev=net0 \
  -netdev user,id=net0,hostfwd=tcp::2222-:22 \
  -nographic \
  -serial mon:stdio
```

#### 4. 测试功能

启动后，测试以下功能：

##### a) 检查 TTY 设备
```bash
tty
# 应该显示: /dev/ttyAMA0
```

##### b) 测试 CTRL+C 信号
```bash
ping 8.8.8.8
# 按 CTRL+C，ping 应该立即停止
```

##### c) 测试 iptables
```bash
iptables -L -v -n
# 应该正常显示防火墙规则，不应该有 "Protocol not supported" 错误
```

##### d) 添加 iptables 规则测试
```bash
iptables -A INPUT -p tcp --dport 22 -j ACCEPT
iptables -L INPUT -n
# 应该看到新添加的规则
```

## CTRL+C 信号传递修复

### 问题描述
在 QEMU 虚拟机内运行的程序（如 ping）无法使用 CTRL+C 中断。

### 根本原因
1. **缺少 ARM PL011 串口驱动**：ARM virt 机器使用的是 PL011 UART (ttyAMA0)，不是 8250
2. **init 脚本中 shell 启动方式不正确**：使用 `exec 0</dev/console` 重定向 stdin 会导致信号无法传递

### 修复方案

#### 1. 内核配置修改
在 `minimal_debug.config` 中添加了 ARM PL011 串口支持：
```
CONFIG_SERIAL_AMBA_PL011=y
CONFIG_SERIAL_AMBA_PL011_CONSOLE=y
```

#### 2. Init 脚本修改
- **移除**：`exec 0</dev/console`（不重定向 stdin）
- **保留**：`exec 1>/dev/console` 和 `exec 2>/dev/console`（保持输出可见）
- **修改 shell 启动方式**：
  ```bash
  exec setsid sh -c "exec sh <>/dev/ttyAMA0 >&0 2>&1"
  ```

**关键点**：
- `<>/dev/ttyAMA0`：以读写模式打开 ttyAMA0，作为 shell 的 stdin
- `setsid`：创建新会话，使 shell 成为会话领导进程
- `>&0 2>&1`：将 stdout 和 stderr 重定向到 stdin（ttyAMA0）

### 验证要点

✓ **正确行为**：
- ping 运行时按 CTRL+C → ping 立即停止
- shell 提示符立即返回
- 可以继续输入其他命令

✗ **错误行为**（修复前）：
- 按 CTRL+C → ping 继续运行
- 或者 shell 没有响应

### 技术细节

#### 为什么需要 ttyAMA0 而不是 console？
- `/dev/console` 是内核控制台的抽象接口
- `/dev/ttyAMA0` 是实际的硬件串口设备
- 信号处理需要 shell 直接连接到真实的 TTY 设备

#### 为什么使用 `<>` 而不是 `<` 和 `>`？
- `<>` 以读写模式打开设备
- 这对于 TTY 设备是必需的，因为它需要同时支持输入和输出
- 单独的 `<` 或 `>` 会以只读或只写模式打开

#### setsid 的作用
- 创建新的会话（session）
- 使 shell 成为会话的领导进程（session leader）
- 这样 shell 可以正确地管理前台进程组，从而传递 CTRL+C 信号

### 如果仍然不工作

#### 调试步骤

1. **检查 ttyAMA0 是否存在**
   ```bash
   ls -l /dev/ttyAMA0
   ```

2. **检查当前 TTY**
   ```bash
   tty
   ```
   应该显示：`/dev/ttyAMA0`

3. **检查进程组**
   ```bash
   ps -o pid,pgid,sid,tty,comm
   ```
   shell 应该是会话领导进程

4. **手动测试**
   如果自动启动不工作，可以手动运行：
   ```bash
   setsid sh -c "exec sh <>/dev/ttyAMA0 >&0 2>&1"
   ```

## 常见问题

### 问题 1: Initramfs 太大

```bash
# 查看大小
du -h output/initramfs.cpio.gz

# 减小大小的方法：
# 1. 移除不需要的软件包（编辑 Dockerfile.initramfs）
# 2. 禁用某些内核模块
# 3. 使用 xz 压缩（更小但解压慢）
```

### 问题 2: iptables 不工作

```bash
# 检查内核配置
grep NETFILTER output/kernel.config
grep IPTABLES output/kernel.config

# 需要启用：
CONFIG_NETFILTER=y
CONFIG_IP_NF_IPTABLES=y
CONFIG_NETFILTER_XTABLES=y
```

**原因**：内核配置未正确应用

**解决**：
1. 确认使用了 `FORCE_RECONFIG=yes`
2. 检查配置验证输出，确保没有警告
3. 手动检查 `.config` 文件中的 Netfilter 配置

### 问题 3: 模块加载失败

```bash
# 检查模块依赖
cat output/rootfs/lib/modules/*/modules.dep

# 手动生成依赖
docker-compose run --rm initramfs-builder sh -c "
  cd /output/rootfs &&
  depmod -b . \$(ls lib/modules/)
"
```

### 问题 4: 网络设备未出现

```bash
# 确保 QEMU 正确配置了网络设备
# 并且内核包含 VirtIO 网络驱动

# 在 initramfs 中检查
ls /sys/class/net/
dmesg | grep virtio
```

### 问题 5: CTRL+C 仍然无法中断 ping

**原因**：
- PL011 串口驱动未启用
- init 脚本未更新

**解决**：
1. 重新编译内核（使用 `FORCE_RECONFIG=yes`）
2. 重新构建 initramfs
3. 确保 QEMU 启动命令包含 `-serial mon:stdio`

### 问题 6: 启动时看不到 /dev/ttyAMA0

**原因**：PL011 驱动未编译

**解决**：
```bash
# 检查内核配置
docker-compose run --rm kernel-builder bash
grep CONFIG_SERIAL_AMBA_PL011 /kernel/.config

# 如果没有或是 "is not set"，重新编译
docker-compose run --rm -e FORCE_RECONFIG=yes kernel-builder /scripts/build_kernel.sh
```

## 高级用法

### 使用 GDB 调试内核

```bash
# 启动 QEMU 并等待 GDB 连接
qemu-system-aarch64 \
  -machine virt \
  -cpu cortex-a57 \
  -m 2G \
  -kernel output/Image \
  -initrd output/initramfs.cpio.gz \
  -append "console=ttyAMA0 nokaslr" \
  -s -S \
  -nographic

# 在另一个终端使用 GDB
gdb-multiarch output/vmlinux
(gdb) target remote :1234
(gdb) break start_kernel
(gdb) continue
```

### 清理构建产物

```bash
# 清理所有输出
rm -rf output/*

# 清理内核构建
docker-compose run --rm kernel-builder make clean

# 深度清理（删除配置）
docker-compose run --rm kernel-builder make mrproper
```

### 查看 Initramfs 内容

```bash
# 解压查看
mkdir -p /tmp/initramfs-test
cd /tmp/initramfs-test
zcat /path/to/output/initramfs.cpio.gz | cpio -idmv

# 查看包含的工具
ls -lh sbin/iptables
ls -lh bin/ip
ls -lh lib/modules/
```

### 创建最小化 initramfs

如果只需要基础功能，可以创建更小的版本：

```bash
# 编辑 Dockerfile.initramfs，只保留必要的包
RUN apk add --no-cache \
    busybox \
    kmod \
    iptables

# 重新构建
docker-compose build initramfs-builder
docker-compose run --rm initramfs-builder /scripts/build_initramfs.sh
```

### 添加自定义脚本

在 `build_initramfs.sh` 中添加：

```bash
# 创建自定义脚本
cat > etc/init.d/my-script << 'EOF'
#!/bin/sh
echo "Running custom script..."
# 你的代码
EOF
chmod +x etc/init.d/my-script
```

## 其它
### 生成compile_commands.json
compile_commands.json 是一个标准化的数据库文件，记录了项目中每个源文件的编译命令。
```
# 生成方式
python3 scripts/clang-tools/gen_compile_commands.py
```
### 生成 .clangd
```
---
# clangd 配置文件 - 针对 Linux 内核优化

CompileFlags:
  # 移除 clangd 不支持的 GCC 编译选项
  Remove:
    # GCC 特定的栈和分支选项
    - -mpreferred-stack-boundary=*
    - -mindirect-branch=*
    - -mindirect-branch-register
    - -maccumulate-outgoing-args
    - -mrecord-mcount
    - -mfentry
    - -mstack-protector-guard=*
    - -mstack-protector-guard-reg=*
    - -mstack-protector-guard-offset=*

    # GCC 优化选项 clangd 不识别的
    - -fconserve-stack
    - -fno-allow-store-data-races
    - -fno-reorder-blocks
    - -fno-ipa-cp-clone
    - -fno-partial-inlining
    - -fno-stack-check
    - -fno-builtin-wcslen
    - -ftrivial-auto-var-init=*
    - -fpatchable-function-entry=*
    - -falign-functions=*

    # 移除 ARM64 特定选项
    - -mgeneral-regs-only
    - -mabi=*
    - -mbranch-protection=*
    - -Wa,-march=*

    # 移除参数选项
    - --param=*

    # 移除部分警告选项以减少干扰
    - -Wframe-larger-than=*
    - -Wimplicit-fallthrough=*
    - -Wno-dangling-pointer
    - -Wno-alloc-size-larger-than
    - -Wno-stringop-overflow
    - -Wno-array-bounds
    - -Wno-format-overflow
    - -Wno-format-truncation
    - -Wno-stringop-truncation
    - -Wno-maybe-uninitialized

  # 添加 clangd 需要的选项
  Add:
    - -Wno-unknown-warning-option
    - -Wno-unused-command-line-argument
    - -ferror-limit=0
    # 指定目标架构为 ARM64
    - --target=aarch64-linux-gnu

Index:
  # 启用后台索引
  Background: Build

  # 索引标准库
  StandardLibrary: No

Diagnostics:
  # 禁用 clang-tidy 以提高性能
  ClangTidy:
    Remove: '*'

  # 减少不必要的诊断信息
  UnusedIncludes: None
  MissingIncludes: None

  # 抑制某些警告
  Suppress:
    - -Wunused-*
    - -Wmissing-*

Hover:
  ShowAKA: Yes

InlayHints:
  Enabled: No
  ParameterNames: No
  DeducedTypes: No

Completion:
  AllScopes: Yes
```


## 参考资料

- Linux 内核官方文档: https://www.kernel.org/doc/html/latest/
- 内核编译指南: https://www.kernel.org/doc/html/latest/admin-guide/README.html
- initramfs 格式: https://www.kernel.org/doc/Documentation/filesystems/ramfs-rootfs-initramfs.txt
- iptables 文档: https://netfilter.org/documentation/
- Alpine Linux 包: https://pkgs.alpinelinux.org/packages
- Linux TTY 子系统：https://www.kernel.org/doc/html/latest/driver-api/tty/index.html
- QEMU 串口文档：https://www.qemu.org/docs/master/system/device-emulation.html#serial-port
- ARM PL011 UART 驱动：https://www.kernel.org/doc/html/latest/driver-api/serial/amba-pl011.html
