# Kata 源码调试

默认覆盖 **Rust runtime-rs、kata-agent 和 shim-ctl**。使用 Ubuntu Linux Host 原生 GNU debug 构建，保留调试符号，关闭优化和内联影响，并把源码路径映射到 `/src/kata-containers`。无需先接入系统 containerd。

```bash
# 在本配置仓库根目录执行
./runtimes/kata/dev.sh bind /path/to/kata-containers
./runtimes/kata/dev.sh setup
```

在 VSCode 选择 **文件 → 从文件打开工作区**，打开 `runtimes/kata/output/debug.local.code-workspace`，安装 C/C++ 扩展。源码使用默认同级 `kata-containers` 目录时，也可打开 [`kata.code-workspace`](kata.code-workspace)。工作区包含 `kata-debug` 和 `kata-source`，断点设在后者。

选择 `Kata: Rust shim entry` 后 F5，会先在 Ubuntu Host 编译 runtime-rs / shim-ctl；选择 `Kata: Agent entry` 则先编译 Agent / agent-ctl。编译成功后启动 Linux GDB，自动停在对应 Rust main。入口配置使用 `--help`，便于先验证源码、符号、调用栈和单步链路。

修改源码后保存文件、停止当前会话，再按 F5 即可增量构建和调试。首次需先完成 `setup`；手工构建可执行 `dev.sh build all`，也可分别 `build runtime` / `build agent`。Attach 配置连接运行中进程，使用对应的现有二进制和符号。

`build` 读取上游 `rust-toolchain.toml`，编译用户绑定的源码，输出在 `runtimes/kata/bin/`，不替换系统安装的 Kata 二进制。该配置针对 Linux Host 的源码调试；生成的 GNU Agent 不能直接当作无 glibc 的 Guest 静态 Agent 镜像使用。Guest 打包需按 [上游 Agent 指南](https://github.com/kata-containers/kata-containers/blob/main/src/agent/README.md)单独构建 musl 产物。

配置的构建产物是 Rust runtime。旧的 Go runtime 位于上游 `src/runtime/`，不能把它的 Go 符号交给这里的 Rust GDB 启动配置。

## 调试真实 Agent RPC

Kata Agent 可在开发 Linux VM 中以普通进程运行，使用独立的 Unix abstract socket。选择 VSCode 的 `Kata: Standalone Agent RPC`，F5 会先编译 Agent / agent-ctl，再创建最小 OCI bundle，随后启动 GDB 并命中 main；再次 F5 继续。在另一个终端执行：

```bash
./runtimes/kata/dev.sh agent-check
```

这会调用 `Check`、`GetGuestDetails`，可在 `kata-source/src/agent/src/rpc.rs` 设置相应断点。Agent 运行在独立的 mount、UTS、IPC 和 PID namespace，开发 RPC 仍应使用专用、可丢弃的 Linux VM 和测试 bundle；它拥有该开发 VM 的 root 权限。上游的 [standalone Agent 示例](https://github.com/kata-containers/kata-containers/blob/main/src/tools/agent-ctl/README.md#run-the-tool-and-the-agent-in-the-same-environment)是这一方式的依据。

## 调试完整 VM 生命周期

runtime shim 的 `--help` 只验证入口，不会启动 VM。完整流程使用 upstream 推荐的 [shim-ctl](https://github.com/kata-containers/kata-containers/blob/main/src/runtime-rs/crates/shim-ctl/README.md)，绕过 containerd 的外围协议，进入真实 runtime / hypervisor / Agent 逻辑。

准备与 checkout 兼容的 Kata 发行资产：所选 VMM、Guest kernel、initrd 或 image，以及所选共享文件系统需要的 virtiofsd。把完整、已经渲染的 upstream `configuration.toml` 的 `path`、`kernel`、`initrd` / `image`、`virtio_fs_daemon` 指向这些真实文件。在 `runtimes/kata/.env` 设置：

```bash
KATA_CONFIG=/path/to/complete/rendered-configuration.toml
KATA_BUNDLE=/var/tmp/kata-debug/bundle
```

选择 `Kata: shim-ctl real VM` 后 F5，启动前任务依次编译 runtime / shim-ctl、创建 OCI bundle、检查 VM 资产和设备，通过后才启动 GDB。在 runtime-rs 的 resource、hypervisor、agent 客户端代码中设置断点。也可手工执行 `dev.sh build runtime`、`dev.sh bundle`、`dev.sh vm-check`，再通过 `dev.sh vm` 启动。`KATA_CONFIG` 缺失时脚本会报错，不会伪造 Guest 资产。更改 `KATA_BUNDLE` 后，同步调整 VSCode 的 `cwd`。

已检查的 Host 有 `/dev/kvm`，但没有 `/dev/vhost-vsock`。QEMU 的 Kata VM 路径需要启用 `CONFIG_VHOST_VSOCK` 并提供该设备；也可以选择 Kata 的 Firecracker 或 Cloud Hypervisor hybrid-vsock 后端，它们通过 Unix Socket 通信。后端差异见 [upstream Agent 控制工具说明](https://github.com/kata-containers/kata-containers/blob/main/src/tools/agent-ctl/README.md#cloud-hypervisor-and-firecracker)。修改 Host 内核需要重启 machine，不会由配置脚本自动执行。

Host GDB 无法直接单步 VM 内部的 Agent；VM 内 Agent 需要带符号的 Guest Agent + Guest gdbserver / 连接通道，或 Guest 内核调试。这里提供的 Agent RPC 模式用于在 Host 的专用开发 VM 里直接调 Agent 代码。

源码目录由 `bind` 保存到 Git 忽略的 `.env`；VSCode 的 `sourceFileMap` 从 `/src/kata-containers` 映射到 `kata-source`，所以不用在公开配置里写本机绝对路径。GNU 构建不会复用 macOS 的 Cargo target。

实际 Kata 二进制和 VM 生命周期需要 clone / bind 对应源码以及准备发行资产后才能验证；入口、RPC 和完整 VM 是三种不同验证层次。

已验证 macOS → Linux GDB MI 管道，并确认 GDB 可以在隔离的 mount / UTS / IPC / PID namespace 中启动。配置绑定、带空格和引号的源码路径、参数保留和 VSCode JSON 检查均已通过；Kata 本体待 clone / bind 后构建验证。
