# 单容器 Linux 内核自动构建与调试

在本仓库根目录绑定源码：

```bash
./one_container/dev.sh bind /path/to/linux
```

VSCode 选择 **文件 → 从文件打开工作区**，打开生成的 `one_container/output/debug.local.code-workspace`。安装 C/C++ 扩展，选择 **Kernel: Build and debug (automatic)**，按 F5 即可按需构建 Docker 镜像、增量编译内核和模块、自动打包 rootfs、启动暂停的 QEMU，并停在 `start_kernel`。停止调试自动停止本环境的 QEMU。

手工入口：

```bash
cd one_container
./dev.sh build       # 一次生成内核、模块和 initramfs
./dev.sh start       # 直接启动已有产物，暂停等待调试器
./dev.sh console     # 另一终端打开串口，Ctrl+] 断开
./dev.sh stop
```

在 `rootfs-overlay/` 放入自定义文件，再执行 `dev.sh rootfs` 即可更新 Guest。rootfs 按内容缓存，未改变时复用。内核通过独立 Docker volume 编译，自动流程不写入绑定的源码树。

已有产物可选择 **Kernel: Debug existing build** 跳过构建。默认同级布局也可打开 [`one-container.code-workspace`](one-container.code-workspace)。完整说明见 [自动化工作区指南](../vscode/README.md)，原有手工流程保留在 [READEMD.md](READEMD.md)。
