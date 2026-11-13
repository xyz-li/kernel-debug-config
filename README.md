# Linux 内核与运行时调试实验

集中管理内核、沙箱运行时和网络实验的调试配置。上游源码保持独立，通过 `dev.sh bind` 绑定；本地配置、镜像、二进制和日志留在各环境的私有目录中。

```text
kernel-debug-config/
├── runtimes/                   # Firecracker / Cloud Hypervisor / gVisor / Kata
│   ├── firecracker/
│   ├── cloud-hypervisor/
│   ├── gvisor/
│   ├── kata/
│   └── common/                 # Host、Guest 交互、绑定与调试通道
├── kernel/                     # Linux 内核构建和 QEMU/GDB 调试
│   ├── single-container/
│   ├── multi-container/
│   ├── common/                 # 构建、rootfs、QEMU、源码绑定
│   └── vscode/                 # 手工 VSCode 配置模板
├── network/                    # Cilium BGP/ECMP、DPDK、Katran 实验
├── tools/                      # 仓库维护和本地状态迁移
└── tests/                      # 跨目录结构及迁移检查
```

| 入口 | 内容 |
| --- | --- |
| [运行时调试](runtimes/README.md) | macOS → Ubuntu KVM Host 或 Linux 原生；VMM、Agent、runsc 源码断点 |
| [Linux 内核调试](kernel/README.md) | Docker 中编译匹配的内核、模块和 rootfs，F5 自动启动 QEMU 并停在 `start_kernel` |
| [网络实验](network/README.md) | 各实验的拓扑、部署脚本和配置 |
| [公共 Ubuntu Host](runtimes/common/host/README.md) | 四种运行时共用的 Host 镜像与创建入口 |

从仓库根目录使用统一入口：

```bash
./runtimes/firecracker/dev.sh bind /path/to/firecracker
./runtimes/cloud-hypervisor/dev.sh bind /path/to/cloud-hypervisor
./runtimes/gvisor/dev.sh bind /path/to/gvisor
./runtimes/kata/dev.sh bind /path/to/kata-containers
./kernel/single-container/dev.sh bind /path/to/linux
./kernel/multi-container/dev.sh bind /path/to/linux
```

在 VSCode 选择 **文件 → 从文件打开工作区**，打开对应目录的 `output/debug.local.code-workspace`。工作区同时显示配置与上游源码；选择 Launch 配置并按 F5，按该环境的流程自动构建和调试。首次 Host、工具链和 Guest 资产准备见各区域指南。

共享串口和 SSH 工具位于 `runtimes/common/guest/`；Kata 专属工具位于 `runtimes/kata/tools/`。运行时之间不通过对方目录借用脚本。

## 从旧目录升级

目录对应关系：`environments/` → `runtimes/`，其中 `fc/` → `firecracker/`；`one_container/`、`multi_containers/`、`kernel_common/` → `kernel/` 下的相应目录；`net/` → `network/`。原先 `vscode/` 的使用指南移到 `kernel/README.md`，绑定工具移到 `kernel/common/workspace.py`。

更新代码前先停止调试。更新后，如旧目录还保留 `.env`、`bin/` 或 `output/`，执行：

```bash
python3 tools/migrate_layout.py
```

脚本迁移本地状态、更新配置和生成工作区中的旧路径，并保留内核环境原有的 Docker 项目和缓存标识；遇到目标已有本地文件会停止并说明冲突。旧的 `one_container` / `multi_containers` 参数仍由内核 Python 入口兼容。迁移后重新打开新的工作区；运行时首次 F5 会按新源码路径增量构建。

## 验证

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s runtimes/common/tests -v
python3 -m unittest discover -s runtimes/firecracker/tests -v
python3 -m unittest discover -s runtimes/cloud-hypervisor/tests -v
python3 -m unittest discover -s kernel/common/tests -v
```

公共串口测试需要允许创建本地 Unix socket。实际 Host、Guest 和调试适配器的验证范围记录在各区域指南中。

目录迁移后已实测两套内核工作区的入口断点、变量读取、单步和 Guest 串口；Firecracker / Cloud Hypervisor 的 main 断点、新路径源码映射、Guest SSH、网络和清理也已通过。网络实验已补充独立部署、失败退出和验证入口；静态与模拟检查、Linux 实测的范围见 [Cilium 指南](network/cilium/README.md)。
