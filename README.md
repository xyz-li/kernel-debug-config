# Linux runtime 源码调试配置

本仓库集中管理 Firecracker、gVisor 和 Kata 的开发配置；上游源码保持独立。macOS 通过 Apple Container 的 Ubuntu Linux 主机编译和调试，Linux ARM64 原生主机也可直接使用。

三套环境及共用脚本集中在 [`environments/`](environments/README.md)，各环境的配置和运行产物分别保存在自己的子目录。

| 环境 | 上游源码 | 调试对象 | 构建方式 | VSCode 调试器 |
| --- | --- | --- | --- | --- |
| [Firecracker](environments/fc/README.md) | `firecracker-microvm/firecracker` | Rust VMM；可选 Guest 内核 | Cargo，带符号、关闭优化 | C/C++ 扩展 → Linux GDB |
| [gVisor](environments/gvisor/README.md) | `google/gvisor` | Go runsc、Sentry、Gofer | Bazel `//:release` 的 debug 构建，保留 sidecars | Go 扩展 → Linux Delve DAP |
| [Kata](environments/kata/README.md) | `kata-containers/kata-containers` | Rust runtime-rs、kata-agent、shim-ctl | 原生 Linux GNU Cargo debug 构建 | C/C++ 扩展 → Linux GDB |

## clone 后接入与单步调试

在本仓库根目录执行。源码可以在任意目录；macOS 下该路径必须对 Linux Host 可见，默认 home-mount 共享用户主目录。

```bash
mkdir -p "$HOME/src"
git clone https://github.com/firecracker-microvm/firecracker.git "$HOME/src/firecracker"
git clone https://github.com/google/gvisor.git "$HOME/src/gvisor"
git clone https://github.com/kata-containers/kata-containers.git "$HOME/src/kata-containers"

./environments/fc/dev.sh bind "$HOME/src/firecracker"
./environments/gvisor/dev.sh bind "$HOME/src/gvisor"
./environments/kata/dev.sh bind "$HOME/src/kata-containers"
```

`bind` 检查上游目录特征，保存 `FC_SOURCE` 或 `SOURCE_DIR` 到对应目录的 `.env`，生成 `output/debug.local.code-workspace`。它不修改上游源码，不复制上游仓库，也不覆盖其他本地设置。绝对路径和生成工作区均被 Git 忽略。

```bash
# 共用已有 Ubuntu Host；默认 machine 名为 fc-ubuntu。
# 若需要新建 Host，先配置 environments/fc/.env 中的 HOST_KERNEL，然后执行：
./environments/fc/dev.sh host-create

# 各环境首次使用时安装依赖；按需执行。
./environments/fc/dev.sh setup
./environments/gvisor/dev.sh setup
./environments/kata/dev.sh setup
```

FC 还需要准备 Guest kernel/rootfs，首次导入或下载方式见 [FC 快速开始](environments/fc/README.md#快速开始)。`setup` 是首次安装依赖，日常 F5 不会重复执行它。

分别在 VSCode 打开 `environments/fc/output/debug.local.code-workspace`、`environments/gvisor/output/debug.local.code-workspace` 或 `environments/kata/output/debug.local.code-workspace`。工作区同时显示配置目录和真正的源码目录，断点应设置在 `*-source` 文件夹下。

打开方式是 **文件（File）→ 从文件打开工作区（Open Workspace from File…）**，然后选择对应的 `.code-workspace` 文件。该文件描述需要一起打开的目录和工作区设置，VSCode 会据此载入配置目录、源码目录以及调试选项。FC 的菜单操作、目录说明和 macOS 终端打开命令见 [FC README](environments/fc/README.md#在-vscode-中从文件打开工作区)。

1. 选择相应的 Launch 配置，F5 自动在 Ubuntu Host 编译，成功后启动调试；Kata / FC 的入口配置自动设置 Rust main 断点，gVisor 使用 `stopOnEntry`。
2. 在源码中按 F9 设置业务断点，F5 继续；F10 单步跳过，F11 单步进入，Shift+F11 返回调用者。
3. 修改源码后保存文件、停止调试，再按 F5；启动前任务会重新进行增量构建。构建失败时先修复错误，再启动调试，避免选择“仍然调试”使用旧产物。

| 调试配置 | F5 自动执行的启动前任务 |
| --- | --- |
| FC Launch | `FC: Build` → Linux GDB 启动 FC |
| gVisor Launch / Run sandbox | Bazel debug 构建 → 启动 Delve 和 macOS 转发 → 等待 Linux Delve 就绪 |
| Kata Rust shim entry | 编译 runtime-rs / shim-ctl → Linux GDB |
| Kata Agent entry | 编译 Agent / agent-ctl → Linux GDB |
| Kata Standalone Agent RPC | 编译 Agent → 创建 OCI bundle → Linux GDB |
| Kata shim-ctl real VM | 编译 runtime → 创建 OCI bundle → 检查 VM 资产和设备 → Linux GDB |

Attach 配置连接已经运行的进程，保留与该进程匹配的二进制；gVisor Attach 会自动启动 Delve 通道。手工构建仍可运行各环境的 `dev.sh build`。

源码采用默认的同级目录布局时，也可以直接用“文件 → 从文件打开工作区”选择这些公开模板：

| 环境 | workspace | 默认源码目录（相对本仓库） |
| --- | --- | --- |
| FC | [`environments/fc/firecracker.code-workspace`](environments/fc/firecracker.code-workspace) | `../firecracker` |
| gVisor | [`environments/gvisor/gvisor.code-workspace`](environments/gvisor/gvisor.code-workspace) | `../gvisor` |
| Kata | [`environments/kata/kata.code-workspace`](environments/kata/kata.code-workspace) | `../kata-containers` |

源码在其他位置时使用 `bind` 生成的本地 workspace。每个 workspace 包含 `*-debug` 配置目录和 `*-source` 源码目录，任务始终在对应配置目录执行。不要只打开上游源码目录，否则不会加载本仓库的 F5 配置。

连接关系是：源码目录 → 本仓库构建脚本 → `bin/` 中的带符号二进制 → Linux GDB/Delve → VSCode 的源码路径映射。无需在上游仓库增加本仓库的依赖，也无需改系统默认 container runtime。

## 配置与隐私

公开文件使用相对路径、环境变量和通用示例。机器名、源码路径等个人配置放在 Git 忽略的 `.env`；日志、二进制、镜像、构建缓存和生成工作区也不提交。调试二进制的 DWARF 和日志可能包含本机路径，分享时只分享配置源文件，不打包 `bin/`、`output/` 或 `.env`。

现有 `one_container/`、`multi_containers/` 是 Linux 内核构建配置，使用 `KERNEL_SOURCE` 选择源码目录；`net/` 中的地址属于实验拓扑示例。

## Linux 内核 workspace

`one_container/` 和 `multi_containers/` 也支持“文件 → 从文件打开工作区”：

| 环境 | workspace | 用途 |
| --- | --- | --- |
| one_container | [`one-container.code-workspace`](one_container/one-container.code-workspace) | 在 `kernel-dev` 中编译、运行 QEMU 和 GDB |
| multi_containers | [`multi-containers.code-workspace`](multi_containers/multi-containers.code-workspace) | 分别构建内核和 initramfs，在 `kernel-builder` 中运行 QEMU 和 GDB |

默认源码是本仓库下的 `linux-source/`。源码在其他目录时，从本仓库根目录生成专用工作区：

```bash
python3 vscode/kernel_workspace.py one_container /path/to/linux
python3 vscode/kernel_workspace.py multi_containers /path/to/linux
```

然后打开对应目录的 `output/debug.local.code-workspace`。工作区同时显示 `kernel-config` 和 `kernel-source`，构建任务和 GDB 自动使用同一源码路径。操作顺序为 **Build Docker images → Full build → Start QEMU → F5**；选择 `Kernel: Connect to QEMU (Docker GDB)` 后自动连接容器内 QEMU，停在 `start_kernel`。详细步骤见 [Linux 内核工作区指南](vscode/README.md)。

## 验证范围

Firecracker 的 Ubuntu KVM、VSCode 入口断点、Guest 网络和 DNS 已验证。gVisor、Kata 的上游仓库由使用者 clone / bind 后再进行实际构建；配置和调试通道的验证情况见各自 README。Guest 内核、Sentry 和 Kata VM 内 Agent 分属不同进程或机器，不能用 Host 进程的 main 断点代替相应内部代码的调试。
