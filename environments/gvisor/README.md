# gVisor 源码调试

调试 `google/gvisor` 的 Go 代码，默认复用 Ubuntu Host。配置、二进制和运行状态独立于 Firecracker。需要 VSCode **Go** 扩展；源码使用 upstream Bazel checkout，不能用合成 `go` 分支的 `go build ./runsc` 代替。

```bash
# 在本配置仓库根目录执行
./environments/gvisor/dev.sh bind /path/to/gvisor
./environments/gvisor/dev.sh setup
./environments/gvisor/dev.sh build
./environments/gvisor/dev.sh dap
```

在 VSCode 打开 `environments/gvisor/output/debug.local.code-workspace`，选择 `gVisor: Launch runsc (remote Delve)`，F5 从入口开始，F10/F11 单步。该入口使用 `--version` 验证启动链路；选择 `gVisor: Run sandbox (remote Delve)` 则执行一个真实 sandbox 示例。

`build` 使用 `.bazelversion` 对应的 Bazel，通过 `-c dbg --strip=never` 构建 `//:release`；输出中必须保留 `runsc` 同级的 `gvisor-bin/`。当前 upstream 已把 Sentry 等代码放入 sidecar 可执行文件，只有一个 runsc 文件不足以运行完整 sandbox。参考 [upstream 构建说明](https://github.com/google/gvisor/blob/master/CONTRIBUTING.md#editor-setup)和 [release 布局规则](https://github.com/google/gvisor/blob/master/tools/release.bzl)。

## 调试 Sentry / Gofer

runsc 是控制进程，Sentry 是另一个进程。要观察 `pkg/sentry/syscalls/` 的执行，先启动一个持续运行的测试 sandbox：

```bash
./environments/gvisor/dev.sh run --platform=ptrace --network=none do /bin/sleep 300

# 另一终端查看 Linux PID
./environments/gvisor/dev.sh ps
./environments/gvisor/dev.sh dap
```

选择 `gVisor: Attach Sentry or Gofer (Linux PID)`，输入 Linux PID，在 `gvisor-source/pkg/sentry/` 设置断点。断点命中需要测试进程实际触发相应 syscall；挂到 runsc 的 main 不会自动跟踪 Sentry。首次先在 runsc 入口确认源码路径映射，再调子进程。

## 调试通道

Ubuntu 的 `dlv dap` 只监听 `127.0.0.1:38697`。macOS 的同端口也只绑定 loopback；Python 转发器通过 Apple Container 标准输入输出和 Linux socat 连接它，不需要 SSH 或外部监听地址。每次 `dap` 接受一次 VSCode 会话，断开后重新运行 `dev.sh dap`。

Go launch / attach 配置使用 [Delve 原生 DAP](https://github.com/golang/vscode-go/blob/master/docs/debugging.md#remote-debugging)。`program` 指向 Linux 可见的真实二进制路径，`substitutePath` 把 Bazel 的 Go import 路径映射回 clone 的源码。更改 `DEBUG_PORT` 后，需要同步调整 `.vscode/launch.json`；更改 `WORKDIR` 后，同步修改 sandbox 配置的 `--root`。

`setup` 下载官方 Go 并核对官方 SHA256，然后通过 Go module 安装 Delve、Bazelisk。版本可在 `.env` 固定。首次 Bazel 构建还会下载 upstream 固定的 Go SDK / C++ 工具链，可能耗时较长。构建缓存保存在 Linux 的 `/var/tmp/gvisor-debug`，避免和 macOS 缓存混用。

当前未绑定上游源码时，`doctor` 会明确报错；不会把模拟程序的调试结果报告成 gVisor 的真实运行结果。

已用独立 Go 小程序验证这套 Delve DAP 通道：macOS → Apple Container 标准输入输出 → Linux loopback，能够命中源码断点、读取局部变量并单步。上游 gVisor 尚未 clone / bind，因此未报告 runsc 或 Sentry 的实际构建、运行通过。
