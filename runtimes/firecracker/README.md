# Firecracker 源码调试与 Guest 实验环境

开发结构：macOS → Ubuntu Linux Host → KVM → Firecracker → Ubuntu Guest。Guest 支持 **LiquidMetal Agent、无 Agent 串口、无 Agent SSH** 三种控制方式，默认保留 LiquidMetal。TAP/NAT 提供外网，普通 `/etc/resolv.conf` 提供 DNS。

默认 Host 是 **Ubuntu 24.04 ARM64**，Apple Container machine 名为 `fc-ubuntu`；Alpine Host 仍然兼容。Guest 当前要求 Ubuntu/systemd。Host 的 home-mount 必须允许访问此仓库。`doctor` 实际调用 `KVM_CREATE_VM`，检查嵌套虚拟化是否可用。

## 快速开始

```bash
cd kernel-debug-config/runtimes/fc
./dev.sh host-create      # 首次：构建 Ubuntu Host 镜像并创建 machine
./dev.sh import           # 设置 ARTIFACT_MACHINE 后导入已有基础 Guest 镜像；已有缓存可跳过
./dev.sh setup
./dev.sh build
./dev.sh run
```

另一个终端：

```bash
cd kernel-debug-config/runtimes/fc
./dev.sh check
./dev.sh exec uname -a
./dev.sh exec cat /etc/resolv.conf
./dev.sh exec sh -c 'echo hello; id'
./dev.sh api GET /machine-config
./dev.sh stop
```

在原启动终端按 Ctrl+C 也可以停止。运行镜像会在下次启动时重新复制；需要保留的 Guest 文件请先用 `vsock-connect get` 导出。

Linux 原生 Host 先安装 Bash，跳过 `host-create` / `import`，在本目录以 root 执行 `setup`、`build`、`run`。`setup` 分别使用 `apk` 和 `apt-get` 安装依赖。源码默认取同级的 `firecracker` 和 `guest-agent` 仓库；设置 `FC_SOURCE`、`AGENT_SOURCE` 可修改。

## Guest 控制模式

模式可以写入 `.env` 的 `GUEST_MODE`，或在命令行使用 `--mode` 明确选择。默认 `liquidmetal`；三种模式使用同一套 FC 构建、KVM、网络与 VSCode GDB 通道。

| 模式 | Guest 中的配置 | 交互方式 | 需要 LiquidMetal 二进制 |
| --- | --- | --- | --- |
| `liquidmetal` | 启用 guest-agent 和 virtio-vsock | `dev.sh exec`、`dev.sh check` | 是 |
| `serial` | 启用 ARM64 串口 root 自动登录，不启用 Agent 或 vsock | `dev.sh console` | 否 |
| `ssh` | 独立 sshd 服务、专用密钥认证，不启用 Agent 或 vsock | `dev.sh ssh`、`dev.sh exec`、`dev.sh check` | 否 |

三种模式都支持 `dev.sh console` 查看启动日志。串口和 SSH 模式仍使用 Ubuntu/systemd rootfs；串口需要 `agetty` 与 `serial-getty@.service`，SSH 需要镜像内已安装 `openssh-server`。默认使用的 Firecracker CI Ubuntu 基础镜像包含这些组件；自定义镜像缺少组件时，准备阶段会明确报错。

### 无 Agent 串口

```bash
# 终端 1，在 runtimes/firecracker/ 中执行
./dev.sh --mode serial run

# 终端 2
./dev.sh console
```

启动器不等待 Agent，Guest 启动后自动进入 root shell。串口终端可直接执行 `uname -a`、`ip route` 等命令；按 **Ctrl+]** 断开串口，VM 继续运行。`dev.sh stop` 停止本环境实例。串口模式没有命令 RPC，`dev.sh exec/check` 会提示改用串口。

Firecracker 的 ARM64 UART 使用 `ttyS0`，启动参数和 getty 均绑定该设备。串口通过 Linux PTY 和本地 Unix socket 双向连接，启动日志始终保存在 `WORKDIR/console.log`；重新连接会回放最近的串口输出，一次连接一个终端。该自动登录配置用于本机开发镜像。

### 无 Agent SSH

```bash
./dev.sh setup                    # 已有 Host 也执行一次，以安装 openssh-client
./dev.sh --mode ssh run           # 保持此终端运行，等待 SSH 就绪

# 另一终端
./dev.sh ssh                      # 进入交互式 Guest shell
./dev.sh ssh uname -a
./dev.sh exec sh -c 'echo hello; id'
./dev.sh check
```

SSH 通过 Ubuntu Host 的 TAP 直连 Guest，默认端口 `22`，必须启用 `ENABLE_NETWORK=1`。不需要在 macOS 开放端口或安装 sshd。启动器在 Linux 的 `WORKDIR/ssh/` 创建客户端密钥和 Guest 主机密钥，只把客户端公钥与 Guest 主机密钥注入新镜像；客户端严格校验固定的 Guest 主机公钥，不读取个人 SSH 配置或 SSH Agent。Guest 的专用服务只允许 root 公钥登录，禁用密码和键盘交互认证。

可通过 `SSH_PORT` 调整端口，或用 `SSH_IDENTITY` 指定 Linux Host 可见的专用、无口令密钥。密钥、known_hosts 和镜像均属于本地运行产物，分享配置时不要打包它们。模式切换无需删除个人 `known_hosts`。

`exec/check/ssh` 会读取当前会话的模式、地址、端口和密钥路径，因此另一终端不需要重复输入 `--mode ssh`。同一 `WORKDIR` 一次运行一个模式；切换时先停止当前调试或 VM，再启动新模式。

### 保留 LiquidMetal

```bash
./dev.sh run                      # 默认仍是 liquidmetal，除非 .env 修改了模式
./dev.sh --mode liquidmetal run   # 明确选择原有 Agent/vsock 方式
./dev.sh exec uname -a
```

LiquidMetal 模式保留原有就绪探测、Guest 命令执行和网络检查；只有这一模式检查、注入和启动 `guest-agent`，并在 FC JSON 中配置 vsock。

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

### 在 VSCode 中“从文件打开工作区”

`.code-workspace` 文件记录需要一起打开的目录和工作区设置。通过“从文件打开工作区”加载后，VSCode 会同时显示调试配置与 Firecracker 源码，并加载配置目录中的调试选项。

先在本配置仓库根目录绑定已经 clone 的 Firecracker 源码：

```bash
./runtimes/firecracker/dev.sh bind /path/to/firecracker
```

然后在 VSCode 中操作：

1. 选择菜单 **文件（File）→ 从文件打开工作区（Open Workspace from File…）**。
2. 选择本仓库中的 `runtimes/firecracker/output/debug.local.code-workspace`。
3. 确认左侧资源管理器出现两个目录：`firecracker-debug` 是调试脚本和配置，`firecracker-source` 是绑定的 Firecracker 源码。断点设置在 `firecracker-source` 中。
4. 安装建议的 **C/C++** 扩展，在“运行和调试”中选择下方相应配置，再按 F5。

三种 Launch 配置均会先执行 `FC: Build`，在 Ubuntu Host 增量编译成功后启动调试，并停在 `firecracker::main`：

| VSCode 配置 | Guest 模式 |
| --- | --- |
| `FC: Launch on Ubuntu Host (macOS)` | 明确使用原有 LiquidMetal Agent 模式 |
| `FC: Serial without Agent (Ubuntu Host)` | 无 Agent 串口模式 |
| `FC: SSH without Agent (Ubuntu Host)` | 无 Agent SSH 模式 |

这些 Launch 项明确选择模式，优先于 `.env` 中的 `GUEST_MODE`。在 FC 入口断点处按 F5 继续，Guest 才会启动。串口模式随后运行任务 **FC: Guest serial console**；SSH 模式在 Guest 启动完成后运行 **FC: Guest SSH shell**，或在终端执行 `./dev.sh ssh`。Guest 串口输入输出放在独立终端，Debug Console 用于 GDB 调试。修改源码后停止当前会话，再 F5 重新构建。

macOS 也可以从本配置仓库根目录用终端打开同一个工作区：

```bash
open -a "Visual Studio Code" \
  runtimes/firecracker/output/debug.local.code-workspace
```

生成的工作区保存在被 Git 忽略的 `output/` 中；更换源码目录后重新执行 `bind`，再打开生成的工作区。若采用默认的同级源码目录布局，也可以通过上述菜单打开 `runtimes/firecracker/firecracker.code-workspace`。

两种调试方式：

1. **从入口启动**：完成首次 Host/Guest 准备和 `./dev.sh setup` 后，选择 `FC: Launch on Ubuntu Host (macOS)` 并按 F5。`preLaunchTask: "FC: Build"` 自动在 Ubuntu Host 编译 FC；成功后调试器准备磁盘、TAP/NAT，再启动 FC，停在 `firecracker::main`。继续后启动 Guest；停止调试会清理本次网络资源。
2. **连接运行中的实例**：先运行 `./dev.sh run`，选择 `FC: Remote attach to Ubuntu Host (macOS)`，输入启动输出中的 **Linux Firecracker PID**。Linux 原生环境使用 `FC: Attach locally (Linux)`。

F5 的执行链路：VSCode → `FC: Build` task → `./dev.sh build` → `container machine run -n fc-ubuntu` → Ubuntu 中的 Cargo → `bin/firecracker-debug` → Linux GDB。源码由 home-mount 共享，编译器与构建缓存位于 Ubuntu 的 `WORKDIR`，macOS 不运行 Cargo。machine 名可通过 `.env` 的 `MACHINE` 修改。

修改源码后保存文件，停止当前会话，再按 F5，任务会执行增量构建。构建输出见 VSCode 的任务终端；失败时先修复错误，避免选择“仍然调试”继续使用旧二进制。Attach 不执行构建，以保留运行中进程对应的符号。命令行的 `./dev.sh debug` 仍使用已有产物，需要时先手动执行 `./dev.sh build`。

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

内核至少启用 `CONFIG_DEBUG_INFO=y`、`CONFIG_FRAME_POINTER=y`，网络/磁盘/vsock 驱动需内建，例如 `CONFIG_VIRTIO_MMIO=y`、`CONFIG_VIRTIO_BLK=y`、`CONFIG_VIRTIO_NET=y`、`CONFIG_VIRTIO_VSOCKETS=y`、`CONFIG_EXT4_FS=y`、`CONFIG_SERIAL_8250=y`、`CONFIG_SERIAL_8250_CONSOLE=y`、`CONFIG_SERIAL_OF_PLATFORM=y`。默认 `nokaslr`，Guest 调试模式使用单 vCPU。入口处页表尚未建立时先用硬件断点。

## 配置与文件

复制 `.env.example` 为 `.env` 后修改。`.env` 是本地 Bash 配置，会在 macOS 和 Linux 两侧读取；使用 `KEY=${KEY:-default}` 形式可保留命令行环境变量优先级。未设置 `.env` 时可以直接通过环境变量覆盖。

| 配置 | 默认值 | 用途 |
| --- | --- | --- |
| `MACHINE` | `fc-ubuntu` | Ubuntu Apple Container machine |
| `HOST_IMAGE` | `fc-debug-host:ubuntu24.04` | 共享 `common/host/Dockerfile` 构建的 Host 镜像 |
| `WORKDIR` | `/var/tmp/fc-debug-config` | Linux 原生磁盘上的镜像、Socket、日志、编译缓存 |
| `GUEST_MODE` | `liquidmetal` | `liquidmetal`、`serial`、`ssh`；CLI `--mode` 可明确覆盖 |
| `SSH_PORT` | `22` | Guest 专用 SSH 服务端口 |
| `SSH_IDENTITY` | `WORKDIR/ssh/id_ed25519` | Linux Host 上的专用无口令客户端密钥 |
| `EXISTING_LAB` | `runtimes/firecracker/output/import` 的绝对路径 | 由 `dev.sh import` 导入的基础产物 |
| `FC_BIN` | `runtimes/firecracker/bin/firecracker-debug` | 使用本次源码构建 |
| `TAP_DEV` | `fc-debug0` | 独立 TAP |
| `HOST_IP` / `GUEST_IP` | `172.16.51.1` / `172.16.51.2` | `/30` 子网，避开旧实例 `172.16.50.0/30` |
| `DNS_SERVER` / `DNS_SECONDARY` | `1.1.1.1` / `8.8.8.8` | 注入 Guest 的静态 DNS |
| `ENABLE_NETWORK` / `ENABLE_NAT` | `1` / `1` | TAP 网络与外网 NAT |
| `VCPUS` / `MEMORY_MIB` | `2` / `512` | Guest 资源 |

想先用已有 release 二进制启动，设置 `FC_BIN` 为 `runtimes/firecracker/bin/firecracker-release` 的绝对路径。该二进制由 `import` 从旧机导入，没有源码构建的调试符号，也不保证具备 Guest GDB feature。

```text
firecracker/
├── dev.sh                    # macOS/Linux 统一入口
├── run-firecracker.sh        # 环境检查、构建、启动、调试、验证与清理
├── inject-fc-rootfs.sh        # 离线注入 Agent、systemd 服务、网络与 DNS
├── config.sh / .env.example  # 集中配置
├── artifacts.py              # 无本地缓存时下载官方 ARM64 CI 产物
├── .vscode/                  # GDB 连接配置与任务
├── gdb-pipe.sh / gdb-host.sh  # macOS → Ubuntu 的 GDB MI 管道
├── firecracker.code-workspace
└── bin/                      # 本机产物，Git 忽略
```

Host 镜像和创建脚本位于 [`../common/host/`](../common/host/README.md)，串口和 SSH 工具位于 [`../common/guest/`](../common/README.md)。`dev.sh host-create` / `host-build` 委托共享 Host 入口执行。

CLI 和 VSCode Launch 的 Guest 串口均保存在 `WORKDIR/console.log`，通过 `dev.sh console` 交互；GDB 输出在 Debug Console，准备阶段日志在 `WORKDIR/launcher.log`。`config.json` 是本次实际启动配置，`session.json` 记录当前 Guest 控制方式及连接参数。API Socket、LiquidMetal vsock Socket、Guest GDB Socket 和串口 Socket 分别是 `api.socket`、`vsock.socket`、`gdb.socket`、`console.socket`。

Ubuntu 官方基础镜像没有 `/sbin/init`，所以共享 Host 镜像通过 `common/host/Dockerfile` 安装 `systemd-sysv`，创建时通过 `--virtualization` 与 `HOST_KERNEL` 启用 KVM。默认 `HOST_KERNEL` 复用同级 `containerization/kernel/vmlinux-arm64`。新 machine 不替换已有 machine，也不改变 Apple Container 的全局默认 machine。

镜像流程：基础 `rootfs.ext4` → 按模式缓存的 `rootfs-liquidmetal.ext4` / `rootfs-serial.ext4` / `rootfs-ssh.ext4` → 每次运行的 `rootfs-run.ext4`。缓存指纹包含模式、基础镜像、注入脚本、网络与 DNS；LiquidMetal 还包含 Agent，SSH 还包含端口和密钥。模式镜像始终从基础镜像生成，不会在运行盘上反复修改。`debugfs` 写入后逐文件读回比较，并运行 `e2fsck`。替换旧的或悬空的 `resolv.conf` 符号链接，不依赖 systemd-resolved。

启动器使用 `flock`，拒绝重复启动和修改运行中的镜像。退出时只清理本次创建的 TAP、带注释的 iptables 规则及 Socket；不会清空防火墙，也不会关闭其他实例需要的全局 IPv4 forwarding。进程异常遭到 SIGKILL 时无法执行清理，先确认对应进程已退出，再处理 `WORKDIR` 的残留 Socket/TAP。

首次缺少缓存时，从 Firecracker 官方 S3 CI 下载，使用临时文件与长度检查，验证 ARM64 Image 魔数和 ext4 文件系统。这些检查不等于签名验证。Linux Host 没有现成 Agent 时，可以在 `guest-agent` 仓库执行 `make release`，再将 Linux ARM64 两个产物复制到 `runtimes/firecracker/bin/guest-agent` 与 `runtimes/firecracker/bin/vsock-connect`。

## 参考

已验证的功能：Ubuntu 24.04.5 ARM64 Host 的 KVM 创建、带符号的 Firecracker 源码构建、VSCode C/C++ 调试适配器远程命中 `firecracker::main`（`main.rs:108`）并读取调用栈；继续运行后 Guest Agent、网关、外网和 DNS 检查全部通过。停止调试后释放镜像锁并清理本次网络资源。Guest 内核 GDB 需要另行提供匹配的 `Image` / `vmlinux`，本次未验证内核源码断点。

新增模式已验证：不提供 Agent 二进制也能启动串口和 SSH Guest；串口 root 自动登录、双向命令与重连回放、SSH 专用密钥认证和命令参数保留均通过。VSCode C/C++ 调试适配器已分别启动两种新模式、命中 FC main 并读取调用栈，继续后串口命令可执行，SSH 的网关、外网和 DNS 检查通过，断开后清理调试进程、串口与网络资源。LiquidMetal 模式的 Guest 启动、vsock 命令和网络检查也已回归验证。

从仓库根目录运行配置及传输测试（串口测试需要允许创建本地 Unix socket）：

```bash
python3 -m unittest discover -s runtimes/common/tests -v
python3 -m unittest discover -s runtimes/firecracker/tests -v
```

- [Firecracker Getting Started](https://github.com/firecracker-microvm/firecracker/blob/main/docs/getting-started.md)
- [Firecracker Guest GDB](https://github.com/firecracker-microvm/firecracker/blob/main/docs/gdb-debugging.md)
- [LiquidMetal Guest Agent](https://github.com/liquidmetal-dev/guest-agent)
