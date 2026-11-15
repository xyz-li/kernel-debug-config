# QEMU 源码调试

在独立的 Apple `container` Ubuntu ARM64 容器中编译并调试 **QEMU 进程自身的 C 源码**。支持 VSCode F5、入口暂停、源码断点、变量、单步和命令行 GDB。Guest 内核调试继续使用 [`kernel/`](../../kernel/README.md) 的入口。

本入口直接使用 `container build/run/exec`，不依赖 `container machine` 或旧的 `fc-ubuntu`。源码以只读方式挂载，在原生 Linux 缓存卷内增量编译；不会改写绑定源码。默认只构建 ARM64 `virt` 和所需 virtio 设备，启用 TCG、user NAT 和调试符号，关闭优化，不启动图形界面。

## 快速开始

从配置仓库根目录执行，源码可以在任意本机目录：

```bash
git clone --recurse-submodules https://gitlab.com/qemu-project/qemu.git "$HOME/src/qemu"
./runtimes/qemu/dev.sh bind "$HOME/src/qemu"
./runtimes/qemu/dev.sh build
```

也可绑定解压的 [QEMU 官方发布包](https://www.qemu.org/download/)。当前使用 11.1.3 实测；首次构建会自动准备编译器、GDB、GLib、libfdt 和 libslirp。离线配置使用源码内随附的 Meson/Python wheels 和容器内依赖，Git checkout 应包含必需的子模块。

首次 `build` 默认从 `kernel/debian-container/output/` **复制独立的 Debian Guest**。在新机器上先按 [Debian 指南](../../kernel/debian-container/README.md)构建内核和根盘，并执行其 `dev.sh down`，再运行上述 QEMU 构建。已有本机产物可以直接使用。

## VSCode F5

1. 打开本目录 `output/debug.local.code-workspace`，安装 C/C++ 扩展。
2. `qemu-debug` 是本配置目录，`qemu-source` 是实际绑定的 QEMU 源码。
3. 选择 **QEMU: Build and debug** 后按 F5，增量编译并停在 `system/main.c` 的 `main`。
4. F10 单步跳过，F11 进入函数，F5 继续。Guest 启动后，另一个终端运行 `dev.sh console`。

已有构建选 **QEMU: Debug existing build**，跳过编译。两个入口均校验当前源码绑定及二进制摘要，避免使用其他源码的旧产物。源码中的断点使用 `/cache/qemu-source` 编译路径映射回 `qemu-source`。

QEMU 的 C 入口使用适配器的 `stopAtEntry`，避免手工插入同名 `main` 断点后被入口处理自动继续。运行中修改断点使用 GDB 原生 MI 中断，辅助控制命令不转发调试适配器的标准输入。

## 命令行和 Guest

```bash
cd runtimes/qemu
./dev.sh debug       # 增量构建，GDB 停在 QEMU main；quit 退出
./dev.sh run         # 使用现有 QEMU 构建，后台启动 Guest
./dev.sh console     # 串口 root shell；Ctrl+] 断开并保留 Guest
./dev.sh status
./dev.sh logs
./dev.sh stop        # 同步并关闭 dev.sh run 启动的 Guest
./dev.sh down        # 同时停止外层容器，保留缓存及根盘
```

Guest 默认 **1 CPU / 256 MiB**，通过 DHCP 配置网络，可运行 `curl -I https://deb.debian.org/debian/`、`apt-get update`。外层容器默认 **2 CPU / 1 GiB**，包含编译器、Host GDB 和 QEMU 的开销；使用结束后 `down` 释放运行内存。

调试中先点击 VSCode“停止”，或在 GDB 输入 `quit`。GDB 先清除断点并 detach，让 QEMU 继续；VSCode 的停止任务随后通过控制通道请求 Guest 同步、正常关机。命令行 GDB 的退出清理也执行同样的关机流程。`stop/down` 不会强行终止正在持锁的 GDB 会话；先结束调试再执行。Guest 无法确认同步时保留实例并报错。

## 持久化与独立性

本目录的 `output/rootfs.ext4` 是运行盘，文件和安装的软件重启后保留，`/tmp` 等 tmpfs 目录除外。默认从已正常关机的 Debian 根盘复制一次；macOS 优先使用 APFS 克隆，后续写入独立，不与内核调试环境共用运行盘。

需要导入更新的内核/启动包时，停止两个环境后执行：

```bash
./runtimes/qemu/dev.sh guest
# 或从其他匹配的持久化 Guest 产物目录导入
./runtimes/qemu/dev.sh guest /path/to/guest-output
```

已有运行盘会保留，只更新 `Image`、`vmlinux`、内核配置、匹配的启动 initramfs 和元数据。导入目录必须包含这些文件、`kernel.json`、`rootfs.json` 和裸 ext4 `rootfs.ext4`，并已停止其 Guest。不要删除 `output/`，其中包含持久化数据。

私有设置放在 Git 忽略的 `.env`，可参考 `.env.example`。`bind` 保存 `QEMU_SOURCE` 并保留其他设置；可调整 `JOBS`、`BUILDER_CPUS`、`BUILDER_MEMORY`、`CPUS`、`MEMORY`。首次工具链镜像构建也可单独运行 `dev.sh setup`。若扩大设备构建范围后编译内存不足，提高 `BUILDER_MEMORY` 或降低 `JOBS`。

## 验证

```bash
python3 -m unittest discover -s runtimes/qemu/tests -v
python3 -m unittest discover -s runtimes/common/tests -v
python3 runtimes/qemu/tests/smoke_debug.py --existing
```

集成检查要求已安装 VSCode C/C++ 扩展、已绑定源码且本环境没有运行中的调试会话。它检查 QEMU main 源码映射、`argc`、单步、运行中添加 QMP 断点、调用栈和继续，随后验证 Debian HTTPS、调试退出时根盘正常关闭及写入数据重启保留。调试协议记录保存在 `output/runtime-dap-smoke.json`。

2026-11-15 已在 macOS ARM64 / Apple container、1 GiB 外层容器中完成 QEMU 11.1.3 的真实构建和上述集成检查，Guest 为 Linux 6.1.102 / Debian 13、1 CPU / 256 MiB。命令行 GDB 的 main 暂停、quit 后关机也已验证；公共工具、源码绑定、目录布局与独立根盘导入检查均通过。

本入口与内核环境共用经过校验的 QEMU Guest 参数和磁盘关机逻辑；Host GDB 的启动、进程归属、会话锁与构建产物独立管理。系统安装的 QEMU 不会替换本环境编译出的调试二进制。
