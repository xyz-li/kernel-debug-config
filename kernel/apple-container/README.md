# Apple container 内核构建与调试

直接使用 macOS 的 `container build/run/exec`，不需要 Docker 或 Compose。独立 Ubuntu ARM64 容器负责编译、QEMU 和 GDB；独立 Alpine 容器生成匹配的 initramfs。源码以只读方式挂载，编译在原生 Linux volume 中完成。

从仓库根目录执行：

```bash
./kernel/apple-container/dev.sh bind /path/to/linux
./kernel/apple-container/dev.sh build
```

用 VSCode 打开 `output/debug.local.code-workspace`，安装 C/C++ 扩展，选择 **Kernel: Build and debug (automatic)** 后按 F5；已有构建可选 **Kernel: Debug existing build**。入口会停在 `start_kernel`，支持源码断点、变量和单步。停止调试自动停止本环境的 QEMU，保留构建容器和缓存。

命令行入口：

```bash
./dev.sh gdb          # 构建、启动并进入 GDB，退出时停止 QEMU
./dev.sh start        # 暂停启动现有产物，等待调试器
./dev.sh run          # 构建后直接启动 Guest
./dev.sh console      # 另一终端进入串口 root shell；Ctrl+] 断开
./dev.sh status
./dev.sh stop
./dev.sh shell        # 进入构建容器；保留已运行的调试 VM
./dev.sh down         # 停止本环境的 QEMU 和构建容器，保留缓存
```

首次 `build/debug/gdb` 自动构建两个 OCI 镜像、创建原生缓存卷和构建容器。需要已启动的 Apple container 服务，以及可用的镜像仓库、Ubuntu APT 和 Alpine APK 网络。只使用本环境名称和所有权标签管理容器，不修改已有 machine 或全局默认设置。镜像或挂载配置变化时，仅在没有运行中的调试 VM 时重建本环境容器。

默认 ARM64、`tinyconfig` 加调试片段、编译并行数 2、构建容器 2 CPU/4G、QEMU 2 CPU/2G，使用 TCG，不要求嵌套虚拟化。`CONFIG_VIRTIO_MENU` 和 `CONFIG_VIRTIO_MMIO` 必须生效；构建和启动都会校验，防止 Guest 缺失网卡。

`output/config.local.json` 可保存设置，例如：

```json
{
  "source": "/path/to/linux",
  "jobs": 2,
  "builder_cpus": 2,
  "builder_memory": "4G",
  "cpus": 2,
  "memory": "2G",
  "kernel_base_config": "tinyconfig"
}
```

对应环境变量为 `KERNEL_SOURCE`、`JOBS`、`BUILDER_CPUS`、`BUILDER_MEMORY`、`CPUS`、`MEMORY` 和 `KERNEL_BASE_CONFIG`。源码须位于区分大小写的文件系统；若在本地磁盘映像中，沿用公共指南的 `source_image` / `source_mount` 设置。源码不必位于默认 `linux-source/`。

自定义 Guest 文件放入 `rootfs-overlay/`，运行 `dev.sh rootfs` 更新；未改变的 rootfs 会复用。`setup --force` 重建镜像，`rootfs --force` 强制打包。完整的产物一致性、缓存与 overlay 说明见 [公共指南](../README.md)。

Alpine 新打包的 rootfs 默认直接配置 QEMU 固定 NAT 网络：`10.0.2.15/24`、广播 `10.0.2.255`、网关 `10.0.2.2`、DNS `10.0.2.3`。启动器显式固定后端的网段、网关、DNS 和 DHCP 起始地址，参数见 [QEMU 网络文档](https://www.qemu.org/docs/master/system/invocation.html#network-options)。启动时不需要 DHCP 或 Python 进程，也不等待外网探测；`KERNEL_DEBUG_NETWORK_READY` 表示地址、路由和 DNS 配置已应用。状态在 `/run/kernel-debug/network.status`；配置失败会在串口输出 `KERNEL_DEBUG_NETWORK_FAILED`，并继续提供 root shell。IPv4 配置不会清空 IPv6 地址。

需要调试 DHCP 时，在本环境的 `rootfs-overlay/etc/kernel-debug/network.conf` 写入 `KERNEL_NET_MODE=dhcp` 后执行 `dev.sh rootfs`；也可选择 `off`，只保留回环接口。Guest 内可以临时执行 `KERNEL_NET_MODE=dhcp /etc/kernel-debug/network`，显式环境变量优先于配置文件。DHCP 获取地址后退出，日志位于 `/run/kernel-debug/udhcpc.log`，回调失败或超时不会报告网络就绪。

正在运行的 Guest 继续使用已加载的旧 initramfs；先结束调试，再运行 `dev.sh rootfs`，下一次启动使用新网络流程，无需重编内核。原有 Alpine 镜像仍可通过 DHCP 启动；Debian 持久化根盘的启动文件保持其现有配置。

隔离网络检查会在临时容器中打包并测试新 rootfs，保留当前调试实例，覆盖静态地址、DHCP、IPv6 保留、DNS、外部 HTTP 和故障提示，并记录网络配置阶段耗时：

```bash
python3 kernel/common/tests/smoke_network.py
```

结果和可检查的 rootfs 产物位于 `output/network-smoke/`。网络配置优化不包含 RTC 内核变更；旧内核的时间仍从 1970 年开始，HTTPS 证书时间问题需按此前检查启用 RTC。

真实调试检查使用生成的工作区配置和本机 C/C++ 调试适配器，验证入口断点、源码映射、变量、单步、串口、Guest 网卡和 ping，结束后停止 VM：

```bash
python3 kernel/common/tests/smoke_debug.py apple-container --existing
```

检查还覆盖运行中新增、删除和重新设置源码断点：内部暂停后必须自动继续，断点必须实际绑定到编译路径，并通过 TCP 请求命中 `tcp_v4_connect`。若当前已经打开调试会话，可在独立临时容器中验证，保留现有 VM：

```bash
python3 kernel/common/tests/smoke_debug.py apple-container --isolated
```

暂停请求由 GDB 原生 `-exec-interrupt` 处理，以便适配器区分内部暂停和用户异常。源码映射只允许 `/cache/source` 作为源码断点的编译路径；`/kernel` 仅用于显示映射。更新这些配置后，停止当前调试并重新启动，无需重新编译内核。

`start_kernel` 入口断点由启动配置中的 GDB 命令设置。C/C++ 扩展默认把未登记到适配器中的外部断点当作异常，导致正常命中时显示红色的 `Hit breakpoint 1 ...`。四套自动化内核环境均设置 `unknownBreakpointHandling: stop`，将其报告为普通断点暂停；真实信号和异常仍按原有流程报告。集成检查会断言入口暂停原因为 `breakpoint`，并确认没有异常文字。

## 查看局部变量

默认 tinyconfig 使用 `-Os`。`DEBUG_INFO` 和 DWARF 能提供符号信息，优化后的局部变量仍可能只在部分指令区间可见；未初始化或已经用完的变量不能通过重启调试恢复。[GDB 变量说明](https://sourceware.org/gdb/current/onlinedocs/gdb.html/Variables.html)

需要更完整的变量跟踪时，在 `output/config.local.json` 中增加文件列表：

```json
"debug_sources": ["net/ipv4/ping.c"]
```

也可用 `KERNEL_DEBUG_SOURCES="net/ipv4/ping.c net/ipv4/tcp_ipv4.c"` 指定。仅列出的对象使用 GCC `-Og -g3 -fno-ipa-sra -fvar-tracking-assignments`，其余内核保留原优化；配置片段中的 `CONFIG_CC_OPTIMIZE_FOR_SIZE=y` 因而仍可能存在。修改只应用到 Linux 编译缓存中的 Kbuild/Makefile，不修改绑定的上游源码；清空列表后重新构建恢复原 flags。

修改列表后，先结束当前调试，再执行 `dev.sh build`，或选择 **Kernel: Build and debug (automatic)**。第一次不能直接用 **Debug existing build**：入口会比较已构建的文件列表和 flags，不匹配时要求重编。实际生效记录保存在 `output/debug-profile.json`。

当前 Linux 6.1.102 中，`ping_v4_sendmsg` 的第 711 行仍是声明区：`free` 在 716 行初始化，地址变量在 735–772 行设置，`tos` 在 781 行赋值。可在 `tos = get_rttos(&ipc, inet)` 处断下，按 F10 后选择调用栈中的 `ping_v4_sendmsg` 帧。已在独立 `-Og` 内核中实测此时 `free/saddr/daddr/faddr/tos/rt` 均可读，ICMP 请求正常完成。`err` 的旧值此时已不再使用，仍可能显示 `optimized out`；需要在其赋值及使用附近查看。

`-Og` 改善变量可见性，不保证所有局部变量在整个函数中始终存在。部分内核文件依赖优化完成内联或段布局，不应把整个内核统一改成 `-O0`；本机 ARM64 的 `ping.c` 在 `-O0` 下也会触发静态分支汇编约束错误。新增文件需通过实际构建检查，失败时不要使用旧产物继续调试。

隔离局部变量检查会用实际 ping 请求命中函数入口和赋值后的断点，保存两次快照；不改变当前调试会话：

```bash
python3 kernel/common/tests/smoke_locals.py
```

2026-11-15 已在 macOS ARM64、Apple container 1.7.1 上构建 Linux 6.1.102，并实测自动构建和已有产物两种调试入口：`start_kernel` 断点、源码映射、`init_task.pid` 读取、单步、Alpine root shell、DHCP、网关 ping，以及停止调试后的自动退出和清理全部通过。也验证了中断后继续构建、增量构建、rootfs 缓存复用、运行中拒绝重建，以及进入 shell 保留调试 VM。上述验证不依赖旧的 `fc-ubuntu` machine。
