# Ubuntu 调试 Host

Firecracker、Cloud Hypervisor、gVisor 和 Kata 共用的 Ubuntu 24.04 ARM64 Host。镜像安装 systemd、GDB 和编译依赖，通过 Apple Container 的 KVM 嵌套虚拟化运行 Guest。

从仓库根目录执行：

```bash
# 首次创建：指定支持嵌套虚拟化的 ARM64 Host 内核
HOST_KERNEL=/path/to/vmlinux-arm64 ./runtimes/common/host/dev.sh create

./runtimes/common/host/dev.sh shell
# 需要更新 Host 镜像时：
./runtimes/common/host/dev.sh build
```

`MACHINE` 默认 `fc-ubuntu`，`HOST_IMAGE` 默认 `fc-debug-host:ubuntu24.04`，保留已有安装的名称。`HOST_KERNEL` 默认取本仓库同级的 `containerization/kernel/vmlinux-arm64`。可通过环境变量或 `runtimes/common/.env` 设置；显式环境变量优先。

已有 machine 直接复用；脚本不会替换它或修改全局默认 machine。Firecracker 的 `dev.sh host-create` / `host-build` 保留为本入口的兼容命令，继续读取其本地 `.env` 设置。
