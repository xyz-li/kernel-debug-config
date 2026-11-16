# Alpine initramfs 内核调试

这是统一 `kernel/dev.sh` 的默认配置，直接使用 Apple `container`。外层 Ubuntu 容器运行编译器、QEMU 和 GDB；Guest 使用 Alpine initramfs。构建和启动规则、内核版本、模块、资源设置见 [公共指南](../README.md)。

```bash
./kernel/apple-container/dev.sh build
./kernel/apple-container/dev.sh boot
./kernel/apple-container/dev.sh console
./kernel/apple-container/dev.sh down
```

使用 `output/debug.local.code-workspace` 打开 VSCode。Guest 文件修改重启后清空；自定义测试文件放到 `rootfs-overlay/`，执行 `dev.sh rootfs` 后在下次启动生效。

默认静态网络：`10.0.2.15/24`，网关 `10.0.2.2`，DNS `10.0.2.3`。无需常驻 DHCP 或 Python；状态位于 `/run/kernel-debug/network.status`。需要 DHCP 时，在 overlay 的 `etc/kernel-debug/network.conf` 设置 `KERNEL_NET_MODE=dhcp`，也支持 `off`。配置失败仍提供串口 shell。

## 局部变量

默认使用 `-Os`，设置 `output/config.local.json` 的 `debug_sources` 可为选定 C 文件使用 `-Og -g3 -fno-ipa-sra -fvar-tracking-assignments`：

```json
"debug_sources": ["net/ipv4/ping.c"]
```

或使用 `KERNEL_DEBUG_SOURCES="net/ipv4/ping.c"`。修改后先结束调试，再构建，不能仅重启旧构建。配置只修改容器中的源码镜像，不修改绑定源码。

以 Linux 6.1.102 的 `ping_v4_sendmsg` 为例：入口仍有未赋值变量。在 `tos = get_rttos(&ipc, inet)` 处断下并按 F10，再选中对应调用栈帧，地址、tos 等才有有效值。已经用完的 `err` 仍可能被优化掉。`-Og` 不保证所有变量始终可见，全局 `-O0` 在当前 ARM64 内核会遇到静态分支汇编约束错误。

模板、工具链镜像与网络配置均由 `kernel/common` 维护。正在运行的旧 Guest 继续使用已加载内核和 initramfs；下一次完整构建才应用新的精简配置。
