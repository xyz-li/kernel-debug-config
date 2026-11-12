# Linux runtime 源码调试配置

本仓库集中管理 Firecracker、gVisor 和 Kata 的开发配置；上游源码保持独立。macOS 通过 Apple Container 的 Ubuntu Linux 主机编译和调试，Linux ARM64 原生主机也可直接使用。

三套环境及共用脚本集中在 [`environments/`](environments/README.md)，各环境的配置和运行产物分别保存在自己的子目录。

| 环境 | 上游源码 | 调试对象 | 构建方式 | VSCode 调试器 |
| --- | --- | --- | --- | --- |
| [Firecracker](environments/fc/README.md) | `firecracker-microvm/firecracker` | Rust VMM；可选 Guest 内核 | Cargo，带符号、关闭优化 | C/C++ 扩展 → Linux GDB |
| [gVisor](environments/gvisor/README.md) | `google/gvisor` | Go runsc、Sentry、Gofer | Bazel `//:release` 的 debug 构建，保留 sidecars | Go 扩展 → Linux Delve DAP |
| [Kata](environments/kata/README.md) | `kata-containers/kata-containers` | Rust runtime-rs、kata-agent、shim-ctl | 原生 Linux GNU Cargo debug 构建 | C/C++ 扩展 → Linux GDB |

## clone 后接入与单步调试

在本仓库根目录执行。源码可以在任意目录；macOS 下该路径必须对 Linux Host 可见，默认 home-mount 共享用户主目录。

```bash
mkdir -p "$HOME/src"
git clone https://github.com/firecracker-microvm/firecracker.git "$HOME/src/firecracker"
git clone https://github.com/google/gvisor.git "$HOME/src/gvisor"
git clone https://github.com/kata-containers/kata-containers.git "$HOME/src/kata-containers"

./environments/fc/dev.sh bind "$HOME/src/firecracker"
./environments/gvisor/dev.sh bind "$HOME/src/gvisor"
./environments/kata/dev.sh bind "$HOME/src/kata-containers"
```

`bind` 检查上游目录特征，保存 `FC_SOURCE` 或 `SOURCE_DIR` 到对应目录的 `.env`，生成 `output/debug.local.code-workspace`。它不修改上游源码，不复制上游仓库，也不覆盖其他本地设置。绝对路径和生成工作区均被 Git 忽略。

```bash
# 共用已有 Ubuntu Host；默认 machine 名为 fc-ubuntu。
# 若需要新建 Host，先配置 environments/fc/.env 中的 HOST_KERNEL，然后执行：
./environments/fc/dev.sh host-create

./environments/gvisor/dev.sh setup
./environments/gvisor/dev.sh build
./environments/gvisor/dev.sh dap          # 保持此终端运行，再在 VSCode 按 F5

# Kata 在另一轮调试中使用：
./environments/kata/dev.sh setup
./environments/kata/dev.sh build all
```

分别在 VSCode 打开 `environments/fc/output/debug.local.code-workspace`、`environments/gvisor/output/debug.local.code-workspace` 或 `environments/kata/output/debug.local.code-workspace`。工作区同时显示配置目录和真正的源码目录，断点应设置在 `*-source` 文件夹下。

1. 选择相应的 Launch 配置，F5 启动；Kata / FC 的入口配置自动设置 Rust main 断点，gVisor 使用 `stopOnEntry`。
2. 在源码中按 F9 设置业务断点，F5 继续；F10 单步跳过，F11 单步进入，Shift+F11 返回调用者。
3. 修改源码后先停止调试，重新执行相应 `dev.sh build`，再 F5；不能把旧二进制和新 checkout 混用。

连接关系是：源码目录 → 本仓库构建脚本 → `bin/` 中的带符号二进制 → Linux GDB/Delve → VSCode 的源码路径映射。无需在上游仓库增加本仓库的依赖，也无需改系统默认 container runtime。

## 配置与隐私

公开文件使用相对路径、环境变量和通用示例。机器名、源码路径等个人配置放在 Git 忽略的 `.env`；日志、二进制、镜像、构建缓存和生成工作区也不提交。调试二进制的 DWARF 和日志可能包含本机路径，分享时只分享配置源文件，不打包 `bin/`、`output/` 或 `.env`。

现有 `one_container/`、`multi_containers/` 是 Linux 内核构建配置，使用 `KERNEL_SOURCE` 选择源码目录；`net/` 中的地址属于实验拓扑示例。

## 验证范围

Firecracker 的 Ubuntu KVM、VSCode 入口断点、Guest 网络和 DNS 已验证。gVisor、Kata 的上游仓库由使用者 clone / bind 后再进行实际构建；配置和调试通道的验证情况见各自 README。Guest 内核、Sentry 和 Kata VM 内 Agent 分属不同进程或机器，不能用 Host 进程的 main 断点代替相应内部代码的调试。
