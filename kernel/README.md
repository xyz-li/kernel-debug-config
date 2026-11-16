# Linux 内核构建与调试

需要 Apple `container` 和宿主机 Python 3.12 或以上版本。统一入口是 `./kernel/dev.sh`，后端使用 macOS Apple `container`，默认 ARM64 QEMU `virt` + TCG，不要求嵌套虚拟化。

```text
kernel/
├── dev.sh                    # KERNEL_ROOTFS 选择用户空间
├── apple-container/          # Alpine initramfs 配置与本地运行产物
├── debian-container/         # Debian 持久化根盘配置与本地运行产物
├── common/
│   ├── images/               # 两套环境共用工具链；两种 rootfs 镜像
│   ├── configs/              # Netfilter、磁盘、可选 tracing/diagnostics
│   ├── vscode/               # 共用 VSCode 配置
│   ├── sources.py            # 精确版本下载与校验
│   └── ...                   # 构建、网络、QEMU、GDB、模块校验
└── output/                   # 共用源码登记、按版本下载、验证结果（不提交）
```

旧 `single-container`、`multi-container` 目录及重复 Docker 实现已删除。统一使用 `kernel/dev.sh`；Python 入口仍接受历史环境名称作为别名。两套有效环境共享同一工具链镜像，编译缓存和运行磁盘分开，避免不同配置和运行状态互相污染。`runtimes/qemu` 用于调试 QEMU 自身；这里调试 Guest Linux 内核。

## 内核版本与源码

```bash
# 使用当前已绑定的源码
./kernel/dev.sh build

# 指定一个精确的 kernel.org 正式版本
KERNEL_VERSION=6.1.102 ./kernel/dev.sh build

# 下载/选择源码并生成工作区；新版本会保存在独立目录
./kernel/dev.sh source 6.6.162
./kernel/dev.sh build

# 调试自己修改过的工作树
./kernel/dev.sh bind /absolute/path/to/linux
```

`KERNEL_VERSION` 优先于本地 JSON 中的 `kernel_version`。匹配版本的已绑定工作树会直接复用，保留用户修改；其他版本从 `https://cdn.kernel.org/pub/linux/kernel/v<major>.x/` 下载，核对同站点 SHA256 清单后解压。这里校验传输内容，不宣称做了 PGP 签名验证。使用精确版本，不自动跟随 latest 或 RC。

下载位于 `kernel/output/sources/<版本>/`，同一版本供两种 rootfs 复用。macOS 自动创建按需占用空间的 8 GiB APFS 大小写敏感映像；Linux 直接使用原生目录。首次下载需要网络，后续复用源码。不会覆盖已存在的源码目录。

`KERNEL_SOURCE=/path/to/linux` 显式指定工作树；同时指定 `KERNEL_VERSION` 时，两者必须匹配。版本由源码 Makefile 检查。切换源码或版本后重新打开生成的 `output/debug.local.code-workspace`，让 VSCode 的源码映射同步；旧工作区固定的 KERNEL_SOURCE 不会被悄悄替换。

当前本机修改过的 6.1.102 已迁移到 `kernel/output/sources/6.1.102/tree/linux-6.1.102/`，原有大小写敏感映像为 `kernel/output/sources/6.1.102/source.sparsebundle`，由 `kernel/output/source.local.json` 共用登记。迁移保留原工作树和映像，不重新解压或覆盖源码修改；这是有效源码数据，不属于可随意删除的编译缓存。旧的两个目录不再承担源码存储。

### macOS 源码目录的大小写敏感配置

大小写敏感是文件系统卷的属性，普通 APFS 目录没有独立的大小写敏感开关，也不能通过 `chmod` 设置。这里创建一个 **Case-sensitive APFS** 稀疏磁盘映像，再将它挂载到源码目录；宿主机原来的文件系统配置保持不变。

```text
kernel/output/sources/6.1.102/
├── source.sparsebundle       # 大小写敏感的 APFS 虚拟磁盘
└── tree/                     # 虚拟磁盘挂载点
    └── linux-6.1.102/        # 实际源码
```

`tree/` 外观看起来是普通目录，进入后访问的却是映像内的文件系统。`source.sparsebundle` 自身可以保存在大小写不敏感的宿主磁盘上，其内部文件名仍区分大小写。容器通过只读绑定挂载使用这份源码，继续保留这种语义；编译在容器的 Linux 缓存文件系统中进行。

创建和挂载逻辑见 [`common/sources.py`](common/sources.py) 的 `prepare()`，关键命令如下（参数由脚本填入）：

```bash
hdiutil create -size 8g -type SPARSEBUNDLE \
  -fs 'Case-sensitive APFS' -volname "kernel-$release" "$source_image"
hdiutil attach "$source_image" -mountpoint "$source_mount" -nobrowse
```

正常使用 `./kernel/dev.sh source <版本>` 或 `build` 即可，脚本负责准备、挂载和复用映像。当前迁移的 6.1.102 沿用原来约 4 GB 的映像；新建映像默认容量上限为 8 GiB，宿主磁盘空间按实际写入逐步占用，并非预先占满或分配相同大小的内存。

在仓库根目录可检查当前卷：

```bash
diskutil info "$PWD/kernel/output/sources/6.1.102/tree"
```

应看到 `File System Personality: Case-sensitive APFS`。当前源码的 `include/uapi/linux/netfilter/xt_MARK.h` 和 `xt_mark.h` 已验证为不同 inode 的两个文件；绑定工作区时也会检查它们是否被折叠成同一文件。源码应始终保存在大小写敏感卷内，复制到大小写不敏感的目录可能造成这类同名文件冲突。

## 精简配置、模块和调试选项

默认基于 `tinyconfig`，保留 GDB/DWARF、符号表、帧指针、串口、proc/sysfs、IPv4/IPv6、virtio 网卡、网络命名空间、模块加载和 RTC。默认 Guest 1 CPU / 256 MiB，外层构建容器 2 CPU / 1 GiB。扩大配置后可提高 `BUILDER_MEMORY` 或降低 `JOBS`。

iptables legacy、iptables-nft 和 nftables 的过滤、连接跟踪、IPv4/IPv6、NAT/MASQUERADE 支持默认保留，多数作为模块，按使用加载。控制台、启动必需设备和根盘驱动内建。Alpine 用户空间包含 `iptables/ip6tables/nft`；新建 Debian 根盘也包含这些工具。已有 Debian 根盘不被重置，首次可在 Guest 执行 `apt-get update && apt-get install -y iptables nftables` 补齐工具。

```bash
# 增加 Kconfig 模块符号，不是 modprobe 使用的 .ko 名称
KERNEL_MODULES="DUMMY TUN" ./kernel/dev.sh build

# 按需增加较重的调试能力
KERNEL_FEATURES="tracing" ./kernel/dev.sh build
KERNEL_FEATURES="diagnostics network-lab" ./kernel/dev.sh build

# 使用自己的额外配置片段（多个路径需按 shell 规则引用）
KERNEL_CONFIG_FRAGMENTS="/absolute/path/extra.config" ./kernel/dev.sh build
```

也可在环境 `output/config.local.json` 保存列表，避免每次输入：

```json
{
  "kernel_version": "6.1.102",
  "modules": ["DUMMY", "TUN"],
  "features": [],
  "config_fragments": [],
  "debug_sources": ["net/ipv4/ping.c"]
}
```

内核完成 Kconfig 依赖解析后，会检查防火墙功能和请求的模块是否实际生效。不存在、依赖不足或被强制内建的模块请求会报错，避免静默缺失。不同内核版本的 Kconfig 符号可能变化，需要相应调整额外片段。

编译缓存保留模块完整符号；导出到 Guest 的 `.ko` 默认仅去掉调试段，减小 initramfs 和磁盘占用。需要把模块 DWARF 一起打入 Guest 时，使用 `KERNEL_STRIP_MODULES=0`。选定源码使用 `-Og` 的规则见 [Alpine 环境说明](apple-container/README.md)。

修改版本、配置片段、模块列表或调试 flags 后，需要重新构建；`start/boot` 会拒绝不匹配的旧构建。临时环境变量需要在后续启动时保持一致，或将设置保存到本地 JSON。单纯增加模块后仍需重启到新内核/匹配模块集。

## 选择 rootfs

| 场景 | 选择 | 行为 |
| --- | --- | --- |
| 内核启动、协议栈、Netfilter、重复复现 | 默认 initramfs | 启动状态可重复，文件修改重启丢失，根文件系统占用 Guest 内存 |
| APT、长期测试程序、保存日志和文件 | Debian ext4 根盘 | 文件和软件重启保留，按需缓存磁盘内容，关闭时需同步 |

仅做内核调试，默认 initramfs 更方便。需要持久保存测试数据或安装较多软件时用 Debian；大用户空间放在磁盘中，通常更节省 Guest 内存。两者都支持完整内核断点和网络测试。

```bash
# 默认 initramfs
./kernel/dev.sh build
./kernel/dev.sh boot
./kernel/dev.sh console
./kernel/dev.sh stop

# Debian 持久化根盘；后续命令同样带 KERNEL_ROOTFS
KERNEL_ROOTFS=debian ./kernel/dev.sh build
KERNEL_ROOTFS=debian ./kernel/dev.sh boot
KERNEL_ROOTFS=debian ./kernel/dev.sh console
KERNEL_ROOTFS=debian ./kernel/dev.sh down
```

也可使用 `kernel/apple-container/dev.sh`、`kernel/debian-container/dev.sh` 固定入口。`boot` 正常启动已有构建，`start` 暂停等待 GDB，`debug` 构建并暂停启动，`gdb` 进入命令行内核调试，`console` 进入 Guest，`shell` 进入外层构建容器，`down` 关闭运行环境并保留缓存和持久盘。

## VSCode 与验证

打开对应环境 `output/debug.local.code-workspace`，选择 **Kernel: Build and debug (automatic)**。已有匹配构建使用 **Kernel: Debug existing build**。入口停在 `start_kernel`，支持运行中设置断点、变量和单步；停止调试后按 rootfs 类型关闭 Guest。

```bash
python3 -m unittest discover -s kernel/common/tests -v
python3 kernel/common/tests/smoke_debug.py debian-container --existing
python3 kernel/common/tests/smoke_netfilter.py --artifacts /absolute/path/to/artifacts
```

Netfilter 检查会创建隔离测试容器，验证规则丢包和计数、两种 iptables 后端、IPv6、模块加载，以及通过 veth/netns 发起的真实 NAT 请求。测试 Debian 磁盘时使用独立副本，原盘需要先正常关闭。
