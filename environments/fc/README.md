# Firecracker 源码调试与 Guest 实验环境

开发结构：macOS → Ubuntu Linux Host → KVM → Firecracker → Ubuntu Guest。Guest 通过 LiquidMetal Agent/vsock 执行命令，TAP/NAT 提供外网，普通 `/etc/resolv.conf` 提供 DNS。

默认 Host 是 **Ubuntu 24.04 ARM64**，Apple Container machine 名为 `fc-ubuntu`；Alpine Host 仍然兼容。Guest 当前要求 Ubuntu/systemd。Host 的 home-mount 必须允许访问此仓库。`doctor` 实际调用 `KVM_CREATE_VM`，检查嵌套虚拟化是否可用。

## 快速开始

```bash
cd kernel-debug-config/environments/fc
./dev.sh host-create      # 首次：构建 Ubuntu Host 镜像并创建 machine
./dev.sh import           # 设置 ARTIFACT_MACHINE 后导入已有基础 Guest 镜像；已有缓存可跳过
./dev.sh setup
./dev.sh build
./dev.sh run
```

另一个终端：

```bash
cd kernel-debug-config/environments/fc
./dev.sh check
./dev.sh exec uname -a
./dev.sh exec cat /etc/resolv.conf
./dev.sh exec sh -c 'echo hello; id'
./dev.sh api GET /machine-config
./dev.sh stop
```

在原启动终端按 Ctrl+C 也可以停止。运行镜像会在下次启动时重新复制；需要保留的 Guest 文件请先用 `vsock-connect get` 导出。

Linux 原生 Host 先安装 Bash，跳过 `host-create` / `import`，在本目录以 root 执行 `setup`、`build`、`run`。`setup` 分别使用 `apk` 和 `apt-get` 安装依赖。源码默认取同级的 `firecracker` 和 `guest-agent` 仓库；设置 `FC_SOURCE`、`AGENT_SOURCE` 可修改。

## Firecracker 源码断点

`build` 读取 Firecracker 源码中的 `rust-toolchain.toml`，构建 Linux ARM64 musl 静态二进制，开发配置保留完整调试符号、关闭优化，并启用 Guest GDB feature。Linux Rust 工具链和 Cargo 缓存放在 `WORKDIR`，不复用 macOS 的 `.cargo` 或 `target`。

```bash
./dev.sh debug
```

GDB 自动停在 `firecracker::main`。然后可以：

```gdb
bt
list
next
continue
```

用 VSCode 打开 `firecracker.code-workspace`（同时显示本目录和 Firecracker 源码），安装建议的 C/C++ 扩展。两种方式：

1. **从入口启动**：先完成 `./dev.sh build`，选择 `FC: Launch on Ubuntu Host (macOS)` 并按 F5。调试器自动准备磁盘、TAP/NAT，再启动 FC，停在 `firecracker::main`；继续后启动 Guest。停止调试会清理本次网络资源。
2. **连接运行中的实例**：先运行 `./dev.sh run`，选择 `FC: Remote attach to Ubuntu Host (macOS)`，输入启动输出中的 **Linux Firecracker PID**。Linux 原生环境使用 `FC: Attach locally (Linux)`。

`gdb-pipe.sh` 根据同一份 `config.sh` / `.env` 选择 machine，使用 Apple Container 的标准输入输出连接 Ubuntu GDB，不需要 SSH 服务、SSH Key 或 GDB TCP 监听端口。它实现 VSCode C/C++ 扩展的 [pipeTransport](https://code.visualstudio.com/docs/cpp/pipe-transport)。如果修改 `WORKDIR`，同步更新 Launch 配置中的两个 `/var/tmp/fc-debug-config` 路径。

配置明确指定 ARM64，并让 GDB 传递 musl 的 `SIGRTMIN`（`SIG35`）。Firecracker 用这个信号唤醒 vCPU；如果 GDB 报 `Real-time event 35` 并暂停，Guest 会一起停止运行。

调试器运行在 Linux 中，源文件通过相同绝对路径共享到 macOS。GDB 控制的是用户态 VMM 进程。当前上游源码的 debug 构建会嵌入空 seccomp policy，这套配置用于本机开发实验。当前源码还要求 libseccomp 2.6.1，`build` 会按官方发布的 SHA256 校验并编译它，避免 Ubuntu 24.04 自带 2.5.x 缺少接口的问题。

## Guest 内核断点

这是另一条调试路径，需要 `gdb` feature 的 Firecracker，以及同一次内核构建生成的原始 ARM64 `Image` 和未剥离符号的 ELF `vmlinux`。下载缓存中的 `guest-vmlinux` 实际上是 raw Image，不能当作 GDB 符号文件。

```bash
# 终端 1：KERNEL 必须是可启动的原始 Image
KERNEL=/path/to/output/Image ./dev.sh guest-debug

# 终端 2：VMLINUX 是与 Image 匹配的 ELF
VMLINUX=/path/to/output/vmlinux ./dev.sh guest-gdb
```

```gdb
hbreak start_kernel
continue
```

内核至少启用 `CONFIG_DEBUG_INFO=y`、`CONFIG_FRAME_POINTER=y`，网络/磁盘/vsock 驱动需内建，例如 `CONFIG_VIRTIO_MMIO=y`、`CONFIG_VIRTIO_BLK=y`、`CONFIG_VIRTIO_NET=y`、`CONFIG_VIRTIO_VSOCKETS=y`、`CONFIG_EXT4_FS=y`、`CONFIG_SERIAL_AMBA_PL011_CONSOLE=y`。默认 `nokaslr`，Guest 调试模式使用单 vCPU。入口处页表尚未建立时先用硬件断点。

## 配置与文件

复制 `.env.example` 为 `.env` 后修改。`.env` 是本地 Bash 配置，会在 macOS 和 Linux 两侧读取；使用 `KEY=${KEY:-default}` 形式可保留命令行环境变量优先级。未设置 `.env` 时可以直接通过环境变量覆盖。

| 配置 | 默认值 | 用途 |
| --- | --- | --- |
| `MACHINE` | `fc-ubuntu` | Ubuntu Apple Container machine |
| `HOST_IMAGE` | `fc-debug-host:ubuntu24.04` | `Dockerfile.host` 构建的 Host 镜像 |
| `WORKDIR` | `/var/tmp/fc-debug-config` | Linux 原生磁盘上的镜像、Socket、日志、编译缓存 |
| `EXISTING_LAB` | `environments/fc/output/import` 的绝对路径 | 由 `dev.sh import` 导入的基础产物 |
| `FC_BIN` | `environments/fc/bin/firecracker-debug` | 使用本次源码构建 |
| `TAP_DEV` | `fc-debug0` | 独立 TAP |
| `HOST_IP` / `GUEST_IP` | `172.16.51.1` / `172.16.51.2` | `/30` 子网，避开旧实例 `172.16.50.0/30` |
| `DNS_SERVER` / `DNS_SECONDARY` | `1.1.1.1` / `8.8.8.8` | 注入 Guest 的静态 DNS |
| `ENABLE_NETWORK` / `ENABLE_NAT` | `1` / `1` | TAP 网络与外网 NAT |
| `VCPUS` / `MEMORY_MIB` | `2` / `512` | Guest 资源 |

想先用已有 release 二进制启动，设置 `FC_BIN` 为 `environments/fc/bin/firecracker-release` 的绝对路径。该二进制由 `import` 从旧机导入，没有源码构建的调试符号，也不保证具备 Guest GDB feature。

```text
fc/
├── dev.sh                    # macOS/Linux 统一入口
├── Dockerfile.host           # Ubuntu 24.04 + systemd + GDB + 编译依赖
├── run-firecracker.sh        # 环境检查、构建、启动、调试、验证与清理
├── inject-fc-rootfs.sh        # 离线注入 Agent、systemd 服务、网络与 DNS
├── config.sh / .env.example  # 集中配置
├── artifacts.py              # 无本地缓存时下载官方 ARM64 CI 产物
├── .vscode/                  # GDB 连接配置与任务
├── gdb-pipe.sh / gdb-host.sh  # macOS → Ubuntu 的 GDB MI 管道
├── firecracker.code-workspace
└── bin/                      # 本机产物，Git 忽略
```

`dev.sh run` 的日志与 Guest 串口在 `WORKDIR/console.log`；VSCode Launch 的输出在 Debug Console，准备阶段日志在 `WORKDIR/launcher.log`。`config.json` 是本次实际启动配置。API Socket、vsock Socket、Guest GDB Socket 分别是 `api.socket`、`vsock.socket`、`gdb.socket`。

Ubuntu 官方基础镜像没有 `/sbin/init`，所以 `host-create` 使用 `Dockerfile.host` 安装 `systemd-sysv` 后再创建 machine，并通过 `--virtualization` 与 `HOST_KERNEL` 启用 KVM。默认 `HOST_KERNEL` 复用同级 `containerization/kernel/vmlinux-arm64`。新 machine 不替换已有 machine，也不改变 Apple Container 的全局默认 machine。

镜像流程：基础 `rootfs.ext4` → 缓存 `rootfs-agent.ext4` → 每次运行的 `rootfs-run.ext4`。缓存指纹包含基础镜像、Agent、注入脚本、网络与 DNS；更改 DNS 会自动重建。`debugfs` 写入后逐文件读回比较，并运行 `e2fsck`。替换旧的或悬空的 `resolv.conf` 符号链接，不依赖 systemd-resolved。

启动器使用 `flock`，拒绝重复启动和修改运行中的镜像。退出时只清理本次创建的 TAP、带注释的 iptables 规则及 Socket；不会清空防火墙，也不会关闭其他实例需要的全局 IPv4 forwarding。进程异常遭到 SIGKILL 时无法执行清理，先确认对应进程已退出，再处理 `WORKDIR` 的残留 Socket/TAP。

首次缺少缓存时，从 Firecracker 官方 S3 CI 下载，使用临时文件与长度检查，验证 ARM64 Image 魔数和 ext4 文件系统。这些检查不等于签名验证。Linux Host 没有现成 Agent 时，可以在 `guest-agent` 仓库执行 `make release`，再将 Linux ARM64 两个产物复制到 `environments/fc/bin/guest-agent` 与 `environments/fc/bin/vsock-connect`。

## 参考

已验证的功能：Ubuntu 24.04.5 ARM64 Host 的 KVM 创建、带符号的 Firecracker 源码构建、VSCode C/C++ 调试适配器远程命中 `firecracker::main`（`main.rs:108`）并读取调用栈；继续运行后 Guest Agent、网关、外网和 DNS 检查全部通过。停止调试后释放镜像锁并清理本次网络资源。Guest 内核 GDB 需要另行提供匹配的 `Image` / `vmlinux`，本次未验证内核源码断点。

- [Firecracker Getting Started](https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md)
- [Firecracker Guest GDB](https://github.com/firecracker-microvm/firecracker/blob/main/docs/gdb-debugging.md)
- [LiquidMetal Guest Agent](https://github.com/liquidmetal-dev/guest-agent)
