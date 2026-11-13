# Linux 内核 Docker 编译环境使用指南

## VSCode 工作区快速开始

本目录提供独立的 [`multi-containers.code-workspace`](multi-containers.code-workspace)，同时打开配置与默认的 `linux-source/`。推荐使用自动化入口；源码在其他位置时，从本仓库根目录执行：

```bash
./kernel/multi-container/dev.sh bind /path/to/linux
```

在 VSCode 选择 **文件 → 从文件打开工作区**，打开生成的 `kernel/multi-container/output/debug.local.code-workspace`。安装 C/C++ 扩展，选择 **Kernel: Build and debug (automatic)** 并按 F5：按需构建 Docker 镜像、增量编译内核和模块、自动创建或复用 rootfs、暂停启动 QEMU，再连接 GDB。停止调试会自动清理本环境的 QEMU。

内核编译、QEMU 和 GDB 在 `kernel-builder` 中运行，initramfs 在 `initramfs-builder` 中生成。源码同步到本环境的原生 Docker 缓存后编译，自动化流程不写入绑定源码。`dev.sh build` 一次生成匹配的内核、模块和 initramfs；`dev.sh start` 直接启动已有产物，VSCode 的 **Kernel: Debug existing build** 同样可跳过构建。

把自定义 Guest 文件放入 `rootfs-overlay/`，执行 `dev.sh rootfs` 即可按内容更新镜像；`dev.sh console` 打开串口，`dev.sh stop` 停止实例。断点设在 `kernel-source`，入口自动停在 `start_kernel`。完整步骤和缓存说明见 [Linux 内核自动化指南](../README.md)。原有独立脚本流程保留在 [legacy.md](legacy.md)。
