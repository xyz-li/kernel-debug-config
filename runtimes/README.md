# 运行时源码调试

本仓库集中管理 Firecracker、Cloud Hypervisor、QEMU、gVisor 和 Kata 的开发配置；上游源码保持独立。QEMU 直接使用 Apple `container` 的独立 Ubuntu 容器；其余环境使用共享 Ubuntu Host，也支持 Linux ARM64 原生主机。

五套环境分别保留自己的配置和运行产物，共享 Host、Guest 交互和调试通道位于 [`common/`](common/README.md)。

```text
runtimes/
├── fc/                    # Firecracker 调试配置
├── ch/                    # Cloud Hypervisor 调试配置
├── qemu/                  # QEMU C 源码调试；独立 Debian 持久化 Guest
├── gv/                    # gVisor 调试配置
├── kata/                  # tools/ 中保留 Kata 专属检查和 OCI bundle 工具
└── common/
    ├── host/              # Ubuntu Host 镜像及创建入口
    ├── guest/             # 串口、SSH
    └── tests/
```

| 环境 | 上游源码 | 调试对象 | 构建方式 | VSCode 调试器 |
| --- | --- | --- | --- | --- |
| [Firecracker](fc/README.md) | `firecracker-microvm/firecracker` | Rust VMM；可选 Guest 内核 | Cargo，带符号、关闭优化 | C/C++ 扩展 → Linux GDB |
| [Cloud Hypervisor](ch/README.md) | `cloud-hypervisor/cloud-hypervisor` | Rust VMM；可选 Guest 内核 | 原生 GNU Cargo debug，启用 `guest_debug` | C/C++ 扩展 → Linux GDB |
| [QEMU](qemu/README.md) | `qemu-project/qemu` | QEMU 用户态进程的 C 源码 | ARM64 virt、关闭优化、保留符号 | C/C++ 扩展 → 容器内 GDB |
| [gVisor](gv/README.md) | `google/gvisor` | Go runsc、Sentry、Gofer | Bazel `//:release` 的 debug 构建，保留 sidecars | Go 扩展 → Linux Delve DAP |
| [Kata](kata/README.md) | `kata-containers/kata-containers` | Rust runtime-rs、kata-agent、shim-ctl | 原生 Linux GNU Cargo debug 构建 | C/C++ 扩展 → Linux GDB |

## clone 后接入与单步调试

当前 Apple `container` 环境新增 QEMU 时，直接按 [QEMU 指南](qemu/README.md)执行 `bind/build`，无需创建 machine。它复制已完成的 Debian Guest 根盘，默认 1 CPU / 256 MiB，支持网络和持久化。下面的共享 `fc-ubuntu` Host 创建步骤适用于原有四套环境。

在本仓库根目录执行。源码可以在任意目录；macOS 下该路径必须对 Linux Host 可见，默认 home-mount 共享用户主目录。

```bash
mkdir -p "$HOME/src"
git clone https://github.com/firecracker-microvm/firecracker.git "$HOME/src/firecracker"
git clone https://github.com/cloud-hypervisor/cloud-hypervisor.git "$HOME/src/cloud-hypervisor"
git clone https://github.com/google/gvisor.git "$HOME/src/gvisor"
git clone https://github.com/kata-containers/kata-containers.git "$HOME/src/kata-containers"

./runtimes/fc/dev.sh bind "$HOME/src/firecracker"
./runtimes/ch/dev.sh bind "$HOME/src/cloud-hypervisor"
./runtimes/gv/dev.sh bind "$HOME/src/gvisor"
./runtimes/kata/dev.sh bind "$HOME/src/kata-containers"
```

`bind` 检查上游目录特征，保存 `FC_SOURCE`、`CH_SOURCE` 或 `SOURCE_DIR` 到对应目录的 `.env`，生成 `output/debug.local.code-workspace`。它不修改上游源码，不复制上游仓库，也不覆盖其他本地设置。绝对路径和生成工作区均被 Git 忽略。

```bash
# 共用已有 Ubuntu Host；默认 machine 名为 fc-ubuntu。
# 若需要新建 Host，先配置 runtimes/common/.env 中的 HOST_KERNEL，然后执行：
./runtimes/common/host/dev.sh create

# 各环境首次使用时安装依赖；按需执行。
./runtimes/fc/dev.sh setup
./runtimes/ch/dev.sh setup
./runtimes/gv/dev.sh setup
./runtimes/kata/dev.sh setup
```

FC 还需要准备 Guest kernel/rootfs，首次导入或下载方式见 [FC 快速开始](fc/README.md#快速开始)。`setup` 是首次安装依赖，日常 F5 不会重复执行它。

Cloud Hypervisor 使用同一个 Ubuntu Host，默认只复用 FC 的基础 Ubuntu rootfs，自动下载并校验 CH 官方 ARM64 内核；独立运行盘、TAP 和子网位于 `runtimes/ch/` 对应的配置中。串口、SSH、VMM/Guest 内核调试及完整启动步骤见 [CH 指南](ch/README.md)。

分别在 VSCode 打开所选环境的 `runtimes/<环境>/output/debug.local.code-workspace`（例如 `runtimes/ch/output/debug.local.code-workspace`）。工作区同时显示配置目录和真正的源码目录，断点应设置在 `*-source` 文件夹下。

打开方式是 **文件（File）→ 从文件打开工作区（Open Workspace from File…）**，然后选择对应的 `.code-workspace` 文件。该文件描述需要一起打开的目录和工作区设置，VSCode 会据此载入配置目录、源码目录以及调试选项。FC 的菜单操作、目录说明和 macOS 终端打开命令见 [FC README](fc/README.md#在-vscode-中从文件打开工作区)。

1. 选择相应的 Launch 配置，F5 自动在 Ubuntu Host 编译，成功后启动调试；Kata / FC / CH 的入口配置自动设置 Rust main 断点，gVisor 使用 `stopOnEntry`。
2. 在源码中按 F9 设置业务断点，F5 继续；F10 单步跳过，F11 单步进入，Shift+F11 返回调用者。
3. 修改源码后保存文件、停止调试，再按 F5；启动前任务会重新进行增量构建。构建失败时先修复错误，再启动调试，避免选择“仍然调试”使用旧产物。

| 调试配置 | F5 自动执行的启动前任务 |
| --- | --- |
| FC Launch | `FC: Build` → Linux GDB 启动 FC |
| CH Launch（串口 / SSH / Linux 本地） | `CH: Build` → 准备独立 Guest 磁盘和网络 → Linux GDB 停在 `cloud_hypervisor::main` |
| QEMU Build and debug | QEMU C 源码增量构建 → 独立 Debian Guest → GDB 在 `main` 暂停 |
| gVisor Launch / Run sandbox | Bazel debug 构建 → 启动 Delve 和 macOS 转发 → 等待 Linux Delve 就绪 |
| Kata Rust shim entry | 编译 runtime-rs / shim-ctl → Linux GDB |
| Kata Agent entry | 编译 Agent / agent-ctl → Linux GDB |
| Kata Standalone Agent RPC | 编译 Agent → 创建 OCI bundle → Linux GDB |
| Kata shim-ctl real VM | 编译 runtime → 创建 OCI bundle → 检查 VM 资产和设备 → Linux GDB |

Attach 配置连接已经运行的进程，保留与该进程匹配的二进制；gVisor Attach 会自动启动 Delve 通道。手工构建仍可运行各环境的 `dev.sh build`。

FC 现在提供 LiquidMetal、无 Agent 串口、无 Agent SSH 三种 Launch 配置，都支持 F5 自动构建。在命令行使用 `./runtimes/fc/dev.sh --mode serial run` 或 `--mode ssh run`；原有 LiquidMetal 仍为默认。三种模式的 Guest 交互、密钥管理和 VSCode 用法见 [FC Guest 控制模式](fc/README.md#guest-控制模式)。

源码采用默认的同级目录布局时，FC、CH、Kata 可以直接用“文件 → 从文件打开工作区”选择公开模板。gVisor 请使用 `bind` 生成的工作区，以加载本机 Linux 包驱动路径：

| 环境 | workspace | 默认源码目录（相对本仓库） |
| --- | --- | --- |
| FC | [`runtimes/fc/firecracker.code-workspace`](fc/firecracker.code-workspace) | `../firecracker` |
| Cloud Hypervisor | [`runtimes/ch/cloud-hypervisor.code-workspace`](ch/cloud-hypervisor.code-workspace) | `../cloud-hypervisor` |
| QEMU | [`runtimes/qemu/qemu.code-workspace`](qemu/qemu.code-workspace) | `../qemu` |
| gVisor | `runtimes/gv/output/debug.local.code-workspace`（由 `bind` 生成） | `../gvisor` |
| Kata | [`runtimes/kata/kata.code-workspace`](kata/kata.code-workspace) | `../kata-containers` |

源码在其他位置时使用 `bind` 生成的本地 workspace。FC、CH 和 gVisor 的配置目录分别显示为 `fc-debug`、`ch-debug`、`gv-debug`，源码目录显示为 `firecracker-source`、`cloud-hypervisor-source`、`gvisor-source`。每个 workspace 包含 `*-debug` 配置目录和 `*-source` 源码目录，任务始终在对应配置目录执行。不要只打开上游源码目录，否则不会加载本仓库的 F5 配置。

连接关系是：源码目录 → 本仓库构建脚本 → `bin/` 中的带符号二进制 → Linux GDB/Delve → VSCode 的源码路径映射。无需在上游仓库增加本仓库的依赖，也无需改系统默认 container runtime。

## 配置与隐私

公开文件使用相对路径、环境变量和通用示例。机器名、源码路径等个人配置放在 Git 忽略的 `.env`；日志、二进制、镜像、构建缓存和生成工作区也不提交。调试二进制的 DWARF 和日志可能包含本机路径，分享时只分享配置源文件，不打包 `bin/`、`output/` 或 `.env`。

## 验证范围

Cloud Hypervisor 已在同一 Ubuntu ARM64 Host 验证源码构建、VSCode C/C++ 调试适配器 main 断点与调用栈、串口/SSH Guest、网关/外网/DNS，以及 Guest GDB 握手和退出清理；内核源码断点仍需提供匹配的 `Image` / `vmlinux`。具体版本和步骤见 [CH 验证记录](ch/README.md#验证)。

Firecracker 的 Ubuntu KVM、VSCode 入口断点、Guest 网络和 DNS 已验证。gVisor 已验证完整 release 构建、真实 sandbox、runsc 入口断点及 Sentry syscall 源码断点、参数读取和单步，详见 [gVisor 验证记录](gv/README.md)。Kata 的上游仓库由使用者 clone / bind 后再进行实际构建；配置和调试通道的验证情况见其 README。Guest 内核、Sentry 和 Kata VM 内 Agent 分属不同进程或机器，不能用 Host 进程的 main 断点代替相应内部代码的调试。
