# Linux 内核自动构建与调试

`one_container/` 和 `multi_containers/` 使用相同的自动化入口，各自保留 Docker 镜像、编译缓存、rootfs、运行状态和 VSCode 工作区。默认调试 ARM64 Linux，GDB、QEMU 和编译器均在 Docker 中运行。

## 第一次使用

先 clone Linux 源码，再从配置仓库根目录执行：

```bash
./one_container/dev.sh bind /path/to/linux
# 或使用另一套环境
./multi_containers/dev.sh bind /path/to/linux
```

Linux 源码需要区分大小写的文件系统。macOS 默认卷可能把 `xt_MARK.h` 和 `xt_mark.h` 合并，`bind` 会提前检查这一问题；请在区分大小写的 APFS 卷或可访问的 Linux 文件系统上 clone / 解包源码。原生编译缓存不会恢复已经丢失的源码文件。

`bind` 检查 `Makefile` 和 `init/main.c`，生成对应目录下的 `output/debug.local.code-workspace` 和 `output/config.local.json`。已有的 `python3 vscode/kernel_workspace.py one_container /path/to/linux` 方式也继续可用。

在 VSCode 选择 **文件 → 从文件打开工作区**，打开生成的文件。左侧 `kernel-config` 是环境配置，`kernel-source` 是源码；安装 C/C++ 扩展。Docker Engine 需要正在运行。

默认把源码放在本仓库的 `linux-source/` 时，也可直接打开公开模板：

- [`one-container.code-workspace`](../one_container/one-container.code-workspace)
- [`multi-containers.code-workspace`](../multi_containers/multi-containers.code-workspace)

选择 **Kernel: Build and debug (automatic)**，按 **F5**。首次自动构建所需 Docker 镜像，随后完成：

```text
同步源码到原生缓存 → 配置/增量编译内核和模块 → 自动生成或复用 initramfs
  → 校验 Image/vmlinux 对应关系 → 启动暂停的 QEMU → GDB → start_kernel
```

F10/F11 单步、F5 继续；**停止调试会自动停止本环境的 QEMU**，构建容器和缓存保留，下一轮可以直接 F5。任务失败时先修复错误，不要选择“仍然调试”使用旧产物。

## build 后怎样快速调试

```bash
cd one_container                  # 或 multi_containers
./dev.sh build                    # 内核、匹配模块、rootfs 一次完成
./dev.sh start                    # 直接使用当前产物，暂停等待 GDB
./dev.sh console                  # 另一终端，Ctrl+] 断开串口
./dev.sh stop                     # 停止本环境的 QEMU
```

VSCode 提供三种入口：

| 配置 | 行为 |
| --- | --- |
| **Kernel: Build and debug (automatic)** | 增量编译、按需打包 rootfs、启动 QEMU、连接 GDB；停止调试自动清理 |
| **Kernel: Debug existing build** | 跳过编译和打包，校验并启动已有产物；停止调试自动清理 |
| **Kernel: Connect to running QEMU** | 连接本环境已启动的 QEMU，保持当前暂停点；断开时保留 VM |

不使用 VSCode 时，`./dev.sh gdb` 自动构建、启动并进入命令行 GDB，退出后停止 QEMU。`./dev.sh run` 构建后直接启动 Guest，使用另一个终端的 `console` 连接 root shell；`logs` 查看串口日志。

快入口使用现有产物；修改源码或内核配置后，选择自动入口或先执行 `build`。重新绑定另一份源码后，快入口会拒绝使用旧绑定的产物，需先完成构建。

## rootfs 自动创建与定制

当前默认 rootfs 以 **initramfs（cpio.gz）** 提供给 Guest，不需要手工创建 ext4 分区或挂载磁盘。自动打包内容为：

1. 所选 Alpine 镜像的用户空间和工具。
2. 本次内核版本对应的模块。
3. BusyBox init、串口 root shell、QEMU user 网络的 DHCP 配置。
4. 本环境 `rootfs-overlay/` 中的自定义文件。

例如新增一个 Guest 测试脚本：

```bash
mkdir -p rootfs-overlay/usr/local/bin
cat > rootfs-overlay/usr/local/bin/test-ping <<'SCRIPT'
#!/bin/sh
ping -c 2 10.0.2.2
SCRIPT
chmod +x rootfs-overlay/usr/local/bin/test-ping
./dev.sh rootfs
```

文件会出现在 Guest 的 `/usr/local/bin/test-ping`。overlay 最后应用，可修改 `/init`、`/etc/inittab`、启动脚本和测试程序。也可通过 `ROOTFS_OVERLAY=/path/to/overlay` 指定其他目录。Guest 每次从 initramfs 启动，持久修改应放入 overlay 后重新打包。

rootfs 缓存按 **基础镜像 ID、内核版本、模块内容、打包脚本、overlay 内容与权限** 判断是否失效。仅修改不影响模块的内核代码时，复用现有 initramfs；修改 overlay、模块或基础镜像时自动重建。`./dev.sh rootfs --force` 强制重新打包。

Alpine 基础版本默认 `3.22`；`BASE_IMAGE` 应使用兼容的 Alpine 镜像。修改后执行 `setup` 或下一次 `build/debug`，镜像配置变化会自动触发构建。新增系统包请修改本环境的 `Dockerfile.initramfs`。

## 缓存、配置与版本一致性

源码先同步到本环境专用 Docker volume 的 `/cache/source`，通过 `O=/cache/build` 编译；自动化流程不修改绑定源码的 `.config` 或写入编译产物。这样也能接入已经做过源码内编译的目录。配置片段会先移除行尾注释、合并必需配置，再运行 Kconfig；最终有效配置保存在 `output/kernel.config`。

`Image`、`vmlinux`、当前版本模块和 `kernel.json` 一起导出到本环境的 `output/`。启动 QEMU 前检查镜像与符号文件的摘要，避免混用不同构建。每次只打包当前内核版本的模块。源码路径、生成工作区、日志、运行产物均被 Git 忽略。

`output/config.local.json` 可以保留本地设置，例如：

```json
{
  "source": "/path/to/linux",
  "jobs": 2,
  "cpus": 2,
  "memory": "2G",
  "kernel_base_config": "defconfig"
}
```

同名环境变量 `KERNEL_SOURCE`、`JOBS`、`CPUS`、`MEMORY`、`KERNEL_BASE_CONFIG` 优先。默认 `defconfig` 配合环境的 `minimal_debug.config` 与必需片段；需要更小内核时可尝试 `tinyconfig`，但最终功能仍由合并后的 Kconfig 决定。调整配置后重新 `build`。

macOS 源码存放在已有的大小写敏感磁盘映像时，还可在本地 JSON 中设置 `source_image`（映像路径）和 `source_mount`（挂载目录），`source` 指向该目录内的 Linux 源码。`setup/build/debug` 会在需要时先挂载它；普通源码目录不需要这些设置。

两套环境使用不同 Compose project、镜像和 volume，调试通过容器内 Unix socket `/cache/run/gdb.sock` 连接，不占用宿主机 1234 端口。构建前会检查本环境 VM 是否运行；正在调试时拒绝重建或替换产物。`stop` 通过 QMP 及进程归属校验停止本环境的实例。

## 常用命令

| 命令 | 功能 |
| --- | --- |
| `bind PATH` | 保存源码路径、生成 workspace |
| `setup` / `setup --force` | 按需构建镜像 / 明确执行镜像构建 |
| `build` | 增量编译内核和模块，按需打包 rootfs |
| `rootfs` / `rootfs --force` | 按需 / 强制重新打包 rootfs |
| `debug` | 构建后暂停启动 QEMU，供 VSCode/GDB 连接 |
| `start` | 校验并暂停启动已有产物 |
| `run` | 构建后直接启动 Guest |
| `gdb` | 自动构建并进入命令行内核调试 |
| `console` / `logs` | 交互式串口 / 串口日志 |
| `stop` / `down` | 停止本环境 VM / 同时停止构建容器 |
| `status` / `shell` | 查看 VM 状态 / 打开构建容器 shell |

旧的独立构建脚本保留，原有手工流程仍可使用；上面的新入口负责缓存编译与成套产物管理。原有 `vscode/launch.json` 等文件作为手工配置参考保留，新工作区直接加载环境目录的 `.vscode/`。

配置和缓存逻辑检查：

```bash
python3 -m unittest discover -s kernel_common/tests -v
```

安装 VSCode C/C++ 扩展并绑定真实源码后，可运行集成检查：

```bash
python3 kernel_common/tests/smoke_debug.py one_container
python3 kernel_common/tests/smoke_debug.py multi_containers --existing
```

检查会实际启动本环境的调试 VM，验证内核断点、源码映射、变量、单步、rootfs 启动及串口命令，结束后停止实例。`--existing` 使用已有构建；扩展不在默认目录时可用 `--adapter` 指定 `OpenDebugAD7`。

已在 macOS ARM64 / Docker Desktop 上用 Linux 6.1.102（`tinyconfig` 加调试片段）完成两套环境的实际构建和上述调试检查，也验证了 overlay 内容打包、修改后重建和未修改时复用。其他内核版本及自定义配置需按实际情况验证。
