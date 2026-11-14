# Cloud Hypervisor 源码调试与 Guest 实验环境

沿用 FC 的调试方式：macOS → Apple Container Ubuntu Host → KVM → Cloud Hypervisor → Ubuntu Guest。支持 **F5 自动构建、VMM main 断点、运行中进程 Attach、串口、SSH、Guest 内核 GDB**。当前支持 Linux ARM64；macOS 默认复用 `fc-ubuntu` Host。

## 快速开始

在本配置仓库根目录执行；上游源码可以放在任意 Host 可见的目录：

```bash
git clone https://github.com/cloud-hypervisor/cloud-hypervisor.git "$HOME/src/cloud-hypervisor"
./runtimes/ch/dev.sh bind "$HOME/src/cloud-hypervisor"
./runtimes/ch/dev.sh setup
./runtimes/ch/dev.sh build
./runtimes/ch/dev.sh run
```

默认直接复用已有 FC 环境的 `/var/tmp/fc-debug-config/rootfs.ext4` **基础文件系统**。这不是运行盘；CH 会离线注入自己的配置，再为每次运行复制独立磁盘。没有基础镜像时，先按 [FC 快速开始](../fc/README.md#快速开始)准备 Host 和基础镜像，或在 CH 的 `.env` 中指定已有 Ubuntu/systemd **裸 ext4 文件系统**的 `BASE_ROOTFS`。带分区表的 cloud image 和 qcow2 不能直接用于此注入脚本。

还没有 Host 时，先配置 `runtimes/common/.env` 中的 `HOST_KERNEL`，执行 `./runtimes/common/host/dev.sh create`。Host 由[共享入口](../common/host/README.md)管理，不会替换已有 machine 或修改全局默认 machine。Linux ARM64 原生主机跳过 Host 创建，在本目录以 root 执行相同命令。

默认内核是 CH 官方 Linux 发布中的 `Image-arm64`，首次准备时下载，并按上游 `scripts/test_assets.yaml` 中的 SHA256 校验。已有自编译内核可设置 `KERNEL=/path/to/Image`；原始 ARM64 Image 与调试符号 ELF `vmlinux` 要分开。

## VSCode：F5 构建并停在 main

1. 执行 `bind`、首次 `setup`，准备好上述基础 rootfs。
2. 在 VSCode 选择 **文件 → 从文件打开工作区**，打开 `runtimes/ch/output/debug.local.code-workspace`。
3. 配置目录显示为 `ch-debug`，源码目录显示为 `cloud-hypervisor-source`。安装建议的 C/C++ 扩展，在源码目录中设置断点。
4. 选择 `CH: Launch serial on Ubuntu Host (macOS)` 或 `CH: Launch ssh on Ubuntu Host (macOS)`，按 F5。

F5 依次执行 `CH: Build` → Linux 原生 Cargo 增量构建 → 准备独立 Guest 磁盘和网络 → Linux GDB → `cloud_hypervisor::main`。停在 main 时 Guest 还没有启动，按 F5 继续后再打开串口或 SSH。F10 单步跳过，F11 单步进入；修改源码后停止调试，再 F5 重新构建。构建失败时先修复错误，避免选择“仍然调试”使用旧二进制。

调试配置：

| 配置 | 用法 |
| --- | --- |
| `CH: Launch serial on Ubuntu Host (macOS)` | 明确选择串口模式，自动构建，停在 Rust main |
| `CH: Launch ssh on Ubuntu Host (macOS)` | 明确选择 SSH 模式，自动构建，停在 Rust main |
| `CH: Launch locally (Linux ARM64)` | Linux 原生 GDB 启动；模式取 `.env` |
| `CH: Remote attach to Ubuntu Host (macOS)` | 连接 `dev.sh run` 输出的 Linux CH PID，不重新构建；适配器限制见下文 |
| `CH: Attach locally (Linux ARM64)` | Linux 原生 Attach，不重新构建 |

默认采用同级上游目录布局时，也可直接打开 [`cloud-hypervisor.code-workspace`](cloud-hypervisor.code-workspace)。任意源码路径使用 `bind` 生成的工作区。源码由 Host 的 home-mount 共享，DWARF 使用固定前缀 `/src/cloud-hypervisor`；VSCode 和命令行 GDB 映射回绑定源码，因此仓库迁移不会让调试器继续查找旧目录。

GDB 通过 `gdb-pipe.sh` 使用 Apple Container 的 stdin/stdout，不需要 SSH 服务或 GDB TCP 端口。`gdb-host.sh` 在整个调试会话内持有磁盘锁和网络资源。`vm-exec.sh` 作为 GDB exec-wrapper 加入本次生成的 VM 参数，因此修改 `.env` 的 `WORKDIR`、内核、网络或 CPU/内存后无需修改 `launch.json`。串口使用独立 PTY/socket，Debug Console 保留给 GDB/MI。

构建是原生 `aarch64-unknown-linux-gnu`，`debug=2`、`opt-level=0`、不剥离符号，启用 `guest_debug` feature。Rust 工具链和 Cargo 缓存放在 Linux 的 `TOOLS_DIR`，构建目录放在 `WORKDIR/target`；不使用 macOS Cargo 缓存。默认使用已有 stable 工具链，没有时安装；源码要求更新 Rust 时可设置 `CH_RUST_VERSION` 后重新构建。

CH GNU 构建用 **SIG34 / glibc SIGRTMIN** 唤醒 vCPU，GDB 已配置为透传；不要照搬 FC musl 构建的 SIG35。开发配置默认 `SECCOMP=false`，可通过 `.env` 调整。

命令行同样可以调试已有构建：

```bash
cd runtimes/ch
./dev.sh debug
```

运行中的实例也可直接连接 Linux GDB，PID 使用 `dev.sh run` 的输出：

```bash
./dev.sh attach 12345
# GDB 内：bt、thread apply all bt、continue；detach 后 Guest 继续运行
```

`attach` 会校验 PID 及其 API socket 属于当前环境，不重新构建或准备磁盘。当前 macOS 安装的 C/C++ 扩展 1.35.6 在 VSCode Attach 后暂停时出现适配器 `AggregateException` 文件占用错误；Launch 的断点、单步通道和继续运行正常。该版本下，运行中进程推荐使用上述命令行 GDB Attach；VSCode Attach 配置保留供其他适配器版本使用。

## Guest 串口与 SSH

默认串口模式无需 Agent 或 SSH 二进制：

```bash
# 终端 1
./dev.sh --mode serial run
# 终端 2，或者使用 VSCode 任务 CH: Guest serial console
./dev.sh console
```

Guest 使用 `ttyAMA0` root 自动登录。按 **Ctrl+]** 断开串口，VM 继续运行；重新连接会回放日志。串口日志始终保存在 `WORKDIR/console.log`。

SSH 模式要求基础 rootfs 已安装 `openssh-server`：

```bash
./dev.sh --mode ssh run
# 另一个终端
./dev.sh ssh
./dev.sh exec sh -c 'echo hello; uname -a; id'
./dev.sh check
./dev.sh api GET /api/v1/vm.info
./dev.sh stop
```

SSH 经过 Linux Host 的 TAP 直连 Guest。自动生成的专用客户端密钥、Guest 主机密钥和固定 `known_hosts` 保存在 `WORKDIR/ssh/`；不使用个人 SSH 配置或 SSH Agent。只把客户端公钥和 Guest 主机私钥注入运行镜像。`exec/check/ssh` 读取当前会话的模式和连接参数，另一终端不必重复指定 `--mode ssh`。

两种模式都没有 LiquidMetal Agent，串口模式的命令在串口 shell 输入。CH 不启动 FC 的 Agent/vsock 服务。Guest 的网络按 MAC 地址匹配，因此不依赖 virtio-pci 网卡的接口名称。

同一个 `WORKDIR` 同时只允许一个 run/prepare/debug，运行时拒绝替换磁盘和构建产物。停止调试、Ctrl+C 或 `dev.sh stop` 只清理本次创建的 TAP、带 `ch-debug-config` 标记的 NAT/转发规则与 Socket，不清空 Host 防火墙。正常停止后下次启动使用新的运行盘；要保留文件，请在停止前导出。

## Guest 内核 GDB

与 VMM 用户态源码调试是两个独立通道。提供同一次内核构建的 ARM64 raw `Image` 与未剥离符号的 ELF `vmlinux`：

```bash
# 终端 1
KERNEL=/path/to/arch/arm64/boot/Image ./dev.sh guest-debug
# 终端 2
VMLINUX=/path/to/vmlinux ./dev.sh guest-gdb
```

```gdb
hbreak start_kernel
continue
```

`guest-debug` 强制使用一个 vCPU，并通过 `--gdb path=...` 等待连接；默认 `nokaslr`。官方预编译 Image 没有随本环境提供匹配的 ELF，因此要打内核源码断点需自行提供 `vmlinux`。

Guest 内核需要内建 `CONFIG_PCI`、`CONFIG_PCI_HOST_GENERIC`、`CONFIG_VIRTIO_PCI`、`CONFIG_VIRTIO_BLK`、`CONFIG_VIRTIO_NET`、`CONFIG_EXT4_FS`、`CONFIG_SERIAL_AMBA_PL011` 和 `CONFIG_SERIAL_AMBA_PL011_CONSOLE`。源码调试还需 `CONFIG_DEBUG_INFO`。FC 的 `pci=off`、virtio-mmio 和 `ttyS0` 配置不能直接照搬。

## 配置与文件

可复制 `.env.example` 为 `.env` 再运行 `bind`，也可直接设置环境变量。`.env` 是本地可信 Bash 配置，`KEY=${KEY:-default}` 写法保留命令行变量优先级；`--mode` 明确覆盖模式。所有绝对路径、密钥、源码 checkout、镜像、二进制和构建缓存都不提交。

| 配置 | 默认值 |
| --- | --- |
| `MACHINE` | `fc-ubuntu` |
| `CH_SOURCE` | 本配置仓库同级的 `cloud-hypervisor` |
| `CH_BIN` | 本环境 `bin/cloud-hypervisor-debug`；VSCode program 同步使用默认位置 |
| `WORKDIR` | `/var/tmp/ch-debug-config` |
| `TOOLS_DIR` | `/var/tmp/sandbox-debug-tools` |
| `BASE_ROOTFS` | `/var/tmp/fc-debug-config/rootfs.ext4` |
| `KERNEL` | `WORKDIR/guest-Image` |
| `GUEST_MODE` | `serial`；可改为 `ssh` |
| `TAP_DEV` | `ch-debug0` |
| `HOST_IP` / `GUEST_IP` | `172.16.52.1` / `172.16.52.2`，`/30` 子网 |
| `VCPUS` / `MEMORY_MIB` | `2` / `512` |
| `SECCOMP` | `false` |

运行参数写入 `WORKDIR/args.json`，会话写入 `session.json`，准备日志写入 `launcher.log`，Guest 输出写入 `console.log`。CH HTTP API 使用 `/api/v1/*` 路径。`bin/cloud-hypervisor-debug.commit` 记录编译对应的上游提交。

串口和 SSH 来自[共享 Guest 工具](../common/README.md)；CH 的配置、镜像注入、构建与网络生命周期独立，不读取其他运行时的 `.env`。

## 验证

配置、源码绑定、参数验证、下载校验和 GDB exec-wrapper 参数保留测试：

```bash
python3 -m unittest discover -s runtimes/common/tests -v
python3 -m unittest discover -s runtimes/ch/tests -v
```

已在现有 Ubuntu 24.04 ARM64 Host（`fc-ubuntu`）实测 Cloud Hypervisor v55.0.0、上游提交 `10658971adc3`：

- `KVM_CREATE_VM`、原生 GNU debug 构建和 CH 官方 7.2.8 ARM64 内核校验通过。
- VSCode C/C++ 调试适配器分别启动串口/SSH 配置，命中 `cloud_hypervisor::main`（`main.rs:1130`），读取调用栈，继续运行后 Guest 可交互。
- 串口 root 自动登录、双向命令、Guest SSH、网关、外网和 DNS 检查通过。
- 命令行 GDB Attach、Rust 调用栈、Detach 后 Guest 继续运行、带空格/空参数/换行的 SSH 命令参数，以及 `/api/v1/vm.info` API 验证通过。
- Guest GDB 暂停启动、单 vCPU 参数、远程握手和 PC 寄存器读取通过；尚未用匹配的 ELF 验证内核源码断点。
- 停止 VM 或断开 Launch 调试后，CH 进程、串口进程、Socket、会话文件、TAP 与本环境 NAT/转发规则已清理。

配置及传输测试共 16 项通过（共用配置与 Guest 工具 10 项、CH 5 项、FC 模式选择 1 项）。Linux 原生 VSCode 界面未另行操作；本次实际 GDB 运行于上述 Linux Host。

参考：[上游构建指南](https://github.com/cloud-hypervisor/cloud-hypervisor/blob/main/docs/building.md)、[ARM64 启动](https://github.com/cloud-hypervisor/cloud-hypervisor#custom-kernel-and-disk-image)、[Guest GDB](https://github.com/cloud-hypervisor/cloud-hypervisor/blob/main/docs/gdb.md)、[设备模型](https://github.com/cloud-hypervisor/cloud-hypervisor/blob/main/docs/device_model.md)。
