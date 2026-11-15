# 轻量 Debian 持久化 Guest

基于 Debian 13 `trixie-slim` ARM64，沿用 Apple `container` 中的 QEMU/GDB 内核调试流程。Guest 使用 BusyBox init 和串口 root shell；保留 Debian 的 glibc、APT、curl、ping、iproute2、tcpdump、strace，不启动 systemd 或 SSH 服务。

默认分配 **1 CPU、256 MiB Guest 内存**，空闲启动实测约使用 29 MiB。外层构建容器为 2 CPU、1 GiB 内存上限，包含 QEMU 和构建工具的开销。使用 TCG，不依赖嵌套虚拟化。闲置时执行 `down` 释放外层容器的内存，下次启动保留磁盘与编译缓存。

## 当前机器直接使用

在仓库根目录执行：

```bash
./kernel/debian-container/dev.sh boot       # 使用现有产物，正常启动
./kernel/debian-container/dev.sh console    # 进入 Guest root shell
```

串口中按回车显示提示符，**Ctrl+]** 断开串口并保持 Guest 运行。在 Guest 内发送请求、安装软件：

```sh
ip -4 addr show eth0
ip route
ping -c 2 10.0.2.2
curl -I https://deb.debian.org/debian/
apt-get update
apt-get install -y --no-install-recommends netcat-openbsd
```

网络使用 QEMU user NAT，启动时自动 DHCP：Guest 通常为 `10.0.2.15`，网关 `10.0.2.2`，DNS `10.0.2.3`。支持向外发起 TCP/UDP 请求；默认没有配置入站端口转发。此处的网关位于外层容器的 QEMU 网络中。

用完后在 macOS 终端执行：

```bash
./kernel/debian-container/dev.sh stop       # 同步根盘、正常关闭 Guest
./kernel/debian-container/dev.sh down       # 同时停止外层构建容器，保留磁盘和缓存
```

## 持久化与磁盘占用

`output/rootfs.ext4` 是整个 `/` 的可写持久化磁盘，`/root`、`/etc`、APT 安装的软件和普通文件在重启后保留。`/run`、`/tmp`、`/dev/shm` 使用按需分配的 tmpfs，重启后清空。

根盘默认逻辑容量 **2 GiB**，采用稀疏文件；本机完成网络及软件安装测试并清理 APT 缓存后，实际占用约 **115 MiB**，随后随数据增长。约 1 MiB 的 `initramfs.cpio.gz` 仅负责挂载 ext4 根盘和更新匹配的内核模块；Debian 用户空间不复制到内存中。旧 Alpine 环境仍使用独立的 initramfs。

`stop` 通过专用 virtio 串口请求 Guest 同步并正常关机；若 Guest 无法确认同步，会报错并保留实例。调试器断开时先 detach，再由停止任务完成同步关机。请用这些入口关闭正在运行的实例。备份时先 `down`，保存 `rootfs.ext4`、`rootfs.uuid`、`rootfs.json` 及对应构建产物；复制稀疏盘时选择支持稀疏文件的备份方式。

清理 APT 下载、索引和已删除文件占用的磁盘块：

```sh
apt-get clean
rm -rf /var/lib/apt/lists/*
fstrim /
```

## 内核调试

用 VSCode 打开本目录的 `output/debug.local.code-workspace`，选择 **Kernel: Debug existing build** 后按 F5，进入 `start_kernel`。支持源码断点、变量和单步；运行中增加、删除断点使用 GDB 原生中断。停止调试会同步并关闭本环境 Guest。

修改内核源码或配置后，选择 **Kernel: Build and debug (automatic)**，或执行：

```bash
./kernel/debian-container/dev.sh build
./kernel/debian-container/dev.sh start      # 暂停启动，等待 GDB
# 也可使用 dev.sh gdb，直接进入命令行调试
```

新环境需要在首次构建前绑定大小写敏感文件系统上的 Linux 源码：

```bash
./kernel/debian-container/dev.sh bind /path/to/linux
./kernel/debian-container/dev.sh build
```

本环境的镜像、内核配置、编译缓存、rootfs 和运行状态均独立于 `apple-container`。内核额外启用 virtio 块设备、ext4、文件锁、控制串口和 RTC；RTC 为 HTTPS 证书校验提供启动时间，无需常驻校时进程。

## 配置与更新

`output/config.local.json` 可保存：

```json
{
  "source": "/path/to/linux",
  "jobs": 2,
  "builder_cpus": 2,
  "builder_memory": "1G",
  "cpus": 1,
  "memory": "256M",
  "rootfs_size_mib": 2048,
  "kernel_base_config": "tinyconfig"
}
```

`rootfs_size_mib` 仅影响首次创建根盘，已有根盘不会自动调整容量。其余设置支持与 Apple 环境相同的环境变量；首次根盘容量也可通过 `ROOTFS_SIZE_MIB` 指定。

`build` 更新内核、符号和匹配模块；已有根盘及用户修改保留。`rootfs`、`rootfs --force` 更新启动 initramfs 和模块元数据，**不会重新格式化根盘**。`rootfs-overlay/` 和 `Dockerfile.initramfs` 中的用户空间仅在首次创建根盘时应用；已有 Guest 中通过文件编辑和 APT 更新软件。删除 `output/` 会丢失根盘，请将其视为数据目录。

默认 1 GiB 外层内存已用于本机的 tinyconfig 构建；若扩大内核配置后编译内存不足，可提高 `builder_memory`，或把 `jobs` 降为 1。Guest 内存与构建容器上限分别配置。

## 验证

先停止本环境 Guest，再运行：

```bash
python3 kernel/common/tests/smoke_persistence.py
python3 kernel/common/tests/smoke_debug.py debian-container --existing
```

持久化检查覆盖 DHCP、DNS、外部 HTTPS、APT 安装、根目录文件、配置文件和软件包重启保留，以及干净关机。调试检查覆盖入口断点、源码映射、变量、单步、运行中修改断点、TCP 连接函数命中及退出清理。结果记录在本目录 `output/`。

2026-11-15 已在 macOS ARM64 / Apple container 上，使用 Linux 6.1.102、1 CPU / 256 MiB Guest 完成上述两组实测。空闲 Guest 的 `MemTotal` 为 248636 KiB，`MemAvailable` 为 218416 KiB；这些是 Guest 内部统计，macOS 的总占用还包含外层 Linux 容器和 QEMU。测试后可用 `down` 完全释放本环境的运行内存。
