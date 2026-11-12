# 单容器 Linux 内核调试

本目录支持独立 VSCode 工作区 [`one-container.code-workspace`](one-container.code-workspace)，同时加载构建任务、Docker GDB 配置与内核源码。

源码默认放在本仓库的 `linux-source/`。源码位于其他位置时，从本仓库根目录执行：

```bash
python3 vscode/kernel_workspace.py one_container /path/to/linux
```

在 VSCode 选择 **文件 → 从文件打开工作区**，打开 `one_container/output/debug.local.code-workspace`。安装 C/C++ 扩展，依次运行任务 **Kernel: Build Docker images → Kernel: Full build → Kernel: Start QEMU**，再选择 `Kernel: Connect to QEMU (Docker GDB)` 并按 F5。

编译、QEMU 和 GDB 在 `kernel-dev` 中运行；initramfs 由独立的 `initramfs-builder` 构建。断点设置在 `kernel-source` 中，GDB 自动停在 `start_kernel`。

完整工作区说明见 [Linux 内核工作区指南](../vscode/README.md)。原有容器环境和命令行说明保留在 [READEMD.md](READEMD.md)。
