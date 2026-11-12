# Linux 内核工作区

`one_container/` 与 `multi_containers/` 各有独立的 VSCode 工作区，同时打开调试配置和内核源码。构建、QEMU 和 GDB 都在 Docker Compose 容器中执行；本机 VSCode 使用 C/C++ 扩展连接容器 GDB，再由 GDB 连接同一容器中的 QEMU。

## 打开工作区

默认目录布局：

```text
kernel-debug-config/
├── linux-source/                    # 已 clone 的 Linux 内核源码
├── one_container/
│   └── one-container.code-workspace
└── multi_containers/
    └── multi-containers.code-workspace
```

在 VSCode 选择 **文件（File）→ 从文件打开工作区（Open Workspace from File…）**，打开以下文件之一：

- [`one_container/one-container.code-workspace`](../one_container/one-container.code-workspace)
- [`multi_containers/multi-containers.code-workspace`](../multi_containers/multi-containers.code-workspace)

左侧的 `kernel-config` 包含 Compose 配置、脚本和输出；`kernel-source` 是内核源码，断点设在其中。安装工作区推荐的 **C/C++** 扩展，确保本机 Docker Engine 正在运行且可使用 `docker compose`。

源码在其他位置时，在本仓库根目录执行：

```bash
python3 vscode/kernel_workspace.py one_container /path/to/linux
python3 vscode/kernel_workspace.py multi_containers /path/to/linux
```

脚本会检查 `Makefile` 和 `init/main.c`，分别生成 `one_container/output/debug.local.code-workspace`、`multi_containers/output/debug.local.code-workspace`，用上述菜单打开所需环境的生成文件即可。脚本只生成本地工作区；源码绝对路径保存在 Git 忽略的 `output/` 中，更换源码时重新生成。

工作区的构建任务通过环境变量 `KERNEL_SOURCE=${workspaceFolder:kernel-source}` 选择 Compose 挂载目录，GDB 管道也使用同一变量。使用工作区任务时无需另外编辑 Compose 的源码路径或复制 `.vscode` 到内核仓库。终端中自行调用 Compose 时，仍需设置 `KERNEL_SOURCE=/path/to/linux`。

## 构建和单步调试

两套工作区默认针对 **ARM64**。在 VSCode 选择 **终端 → 运行任务（Terminal → Run Task…）**：

1. 首次执行 `Kernel: Build Docker images`。`multi_containers` 的编译镜像已加入 GDB 和 QEMU，已有旧镜像也需重建一次。
2. 执行 `Kernel: Full build`，依次编译内核与模块、生成 initramfs。编译产物位于所选环境的 `output/`，容器内对应 `/output`。
3. 执行 `Kernel: Start QEMU`，保持该任务终端运行。QEMU 使用 `/output/Image` 和 `/output/initramfs.cpio.gz`，通过 `-S` 暂停，GDB stub 监听容器内 `127.0.0.1:1234`，启动参数包含 `nokaslr`。
4. 在“运行和调试”选择 `Kernel: Connect to QEMU (Docker GDB)`，按 **F5**。配置加载 `/output/vmlinux`，连接 QEMU，在 `start_kernel` 设置硬件断点并继续，命中后显示源码和调用栈。
5. 在 `kernel-source` 中按 F9 设置后续断点，F10/F11 单步，F5 继续。停止调试后，在 QEMU 串口终端用 Ctrl+A、X 退出；也可运行 `Kernel: Stop build container` 结束该容器中的 QEMU 和 GDB。

调试配置的 `preLaunchTask` 确保构建容器正在运行。F5 连接使用当前产物启动的 QEMU；修改源码后，先停止该 QEMU，再执行 `Full build`、`Start QEMU`，然后 F5，确保内核镜像和符号来自同一次构建。

| 任务 | 功能 |
| --- | --- |
| `Kernel: Build Docker images` | 构建编译环境和 initramfs 镜像 |
| `Kernel: Start build container` | 启动 `kernel-dev` 或 `kernel-builder` |
| `Kernel: Build kernel` | 编译内核与模块；自动启动构建容器 |
| `Kernel: Build initramfs` | 根据当前模块产物生成 initramfs |
| `Kernel: Full build` | 顺序执行 Build kernel、Build initramfs |
| `Kernel: Start QEMU` | 在构建容器中以前台串口、暂停模式启动 ARM64 QEMU |
| `Kernel: Stop build container` | 停止本环境的构建容器及其中的调试进程 |

`sourceFileMap` 将编译路径 `/kernel` 映射为工作区里的 `kernel-source`。`program` 使用带符号的 ELF `vmlinux`，QEMU 启动使用 raw `Image`；GDB 与 QEMU 在同一容器通信，无需安装 macOS GDB。连接方式使用 VSCode C/C++ 的 [Docker pipeTransport](https://code.visualstudio.com/docs/cpp/pipe-transport#docker-example)。

这些工作区加载各环境目录中的 `.vscode/`。本目录原有的 `launch.json`、`settings.json` 和 `c_cpp_properties.json` 仍是手工配置参考；新工作区不需要复制它们。

已检查工作区 JSON、任务依赖、GDB 源码映射，以及带空格、引号和 `$` 的源码路径在工作区与 Compose 中的解析。当前未绑定真实内核源码，也未构建这两套 Docker 镜像，完整内核编译、QEMU 启动和源码断点仍需准备源码后验证。
