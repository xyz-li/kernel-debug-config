# gVisor 源码调试

调试 `google/gvisor` 的 Go 代码，默认复用 Ubuntu Host。配置、二进制和运行状态独立于 Firecracker。需要 VSCode **Go** 扩展；源码使用 upstream Bazel checkout，不能用合成 `go` 分支的 `go build ./runsc` 代替。

```bash
# 在本配置仓库根目录执行
./runtimes/gv/dev.sh bind /path/to/gvisor
./runtimes/gv/dev.sh setup
```

在 VSCode 选择 **文件 → 从文件打开工作区**，打开 `runtimes/gv/output/debug.local.code-workspace`。`gvisor.code-workspace` 是生成模板；请使用 `bind` 生成的工作区，其中包含本机包驱动的绝对路径。工作区包含 `gv-debug` 和 `gvisor-source`，断点设在后者。

在 `gv-debug` 上右键选择 **在集成终端中打开**，终端目录就是本仓库的 `runtimes/gv`，此时使用 `./dev.sh ...`。只有在 `kernel-debug-config` 仓库根目录下才使用 `./runtimes/gv/dev.sh ...`。以下工作区内的调试命令均从 `gv-debug` 终端执行。

选择 `gVisor: Launch runsc (remote Delve)` 并按 F5，会依次执行 `gVisor: Build`、`gVisor: Start Delve DAP`，等 Linux Delve 输出就绪消息后才连接调试器；无需另外运行 `dev.sh dap`。F10/F11 单步。该入口使用 `--version` 验证启动链路；选择 `gVisor: Run sandbox (remote Delve)` 则执行一个真实 sandbox 示例。

修改源码后保存文件、停止当前会话，再按 F5，Bazel 会在 Ubuntu Host 增量构建。首次需先完成 `setup`，构建失败时先修复错误再重试。手工编译和启动通道仍可分别执行 `dev.sh build`、`dev.sh dap`。

`build` 使用 `.bazelversion` 对应的 Bazel，通过 `-c fastbuild --strip=never --@io_bazel_rules_go//go/config:gc_goopts=-l` 构建 `//:release`。保留 DWARF 调试符号并关闭 Go 内联，同时保留优化，避免 `-c dbg` 注入的 `-N` 导致 `nosplit stack over 792 byte limit` 链接错误。优化仍可能使部分局部变量不可见或让单步跳过某些源码行。

输出中必须保留 `runsc` 同级的 `gvisor-bin/`。当前 upstream 已把 Sentry 等代码放入 sidecar 可执行文件，只有一个 runsc 文件不足以运行完整 sandbox。参考 [upstream 构建说明](https://github.com/google/gvisor/blob/master/CONTRIBUTING.md#editor-setup)和 [release 布局规则](https://github.com/google/gvisor/blob/master/tools/release.bzl)。

## 编辑器源码分析

工作区为 gopls 设置 `GOOS=linux`，并通过 `gv-debug/tools/gopackagesdriver.sh` 在 Ubuntu 中运行 rules_go 的 Bazel 包驱动。平台包的生成器需要执行 Linux 程序及 GCC，不能仅在 macOS 上设置 `GOOS`。驱动将生成源码、第三方依赖和标准库文件增量同步到 `output/gopls-files`，供本机 gopls 读取；上游源码直接使用共享目录。配置目录返回 `NotHandled`，避免把它当成 Bazel 源码仓库。

源码分析需要本机 Go/gopls 和运行中的 Ubuntu Host，并先完成 `setup`。Bazel 复用 Ubuntu 的构建缓存，首次索引会生成额外元数据并同步文件。不要为解决编辑器提示而在 upstream checkout 执行 `go mod tidy`。若修改工作区设置后仍显示旧诊断，重新执行 `bind`、打开生成的工作区，再在命令面板执行 **Go: Restart Language Server**，等待索引完成。

`bind` 根据源码 `go.mod` 选择本机 Go 工具链，并把该工具链的可执行文件配置给 Go 扩展和 gopls。包驱动也返回语言版本，避免旧 Go 将 `new(value)` 等语法误报为 `requires go1.26 or later`。

## 调试 Sentry / Gofer

`dev.sh run` 和 VSCode 的 Run sandbox 配置默认使用 `systrap`。手动传入 `--platform=ptrace`、`--platform=kvm` 或 `--platform=auto` 可覆盖默认值。

runsc 是控制进程，Sentry 是另一个进程。要观察 `pkg/sentry/syscalls/` 的执行，先用 F5 Launch 或 `dev.sh build` 生成二进制，再启动一个持续运行的测试 sandbox：

```bash
# gv-debug 终端 1：保持此命令运行；sleep 没有输出是正常现象。
./dev.sh run --platform=systrap --network=none do /bin/sleep 300

# gv-debug 终端 2：查看 Linux PID
./dev.sh ps
```

在 `ps` 输出中，命令以 `runsc-sandbox ... boot` 开始的是 Sentry 主进程；以 `runsc-gofer ... gofer` 开始的是 Gofer。调试 `pkg/sentry` 时使用 Sentry 主进程的 PID。`ps` 会省略平台辅助进程和查询命令自身。每次重新运行 sandbox 都要重新查询 PID。

选择 `gVisor: Attach Sentry or Gofer (Linux PID)`，按 F5，在任务输入框中填写 Linux PID。前置任务在 Ubuntu 中运行 `dlv --headless attach PID`，就绪后 VSCode 以 `mode: remote` 连接。PID 由任务传给 Linux，`launch.json` 不设置 `processId`，因此不会进入 macOS 的进程选择器。也可手动运行 `./dev.sh attach PID` 启动同一通道。

调试 Sentry 时选择上述 Attach 配置；`gVisor: Launch runsc` 用于调试控制进程。这些入口共用调试端口，切换前先断开当前调试会话并结束它的转发任务。

在 `gvisor-source/pkg/sentry/` 设置断点；调试 Gofer 的文件服务时则在 `gvisor-source/runsc/gofer/fs/` 设置断点。Attach 保留当前运行进程对应的构建产物。断点命中需要测试进程实际触发相应 syscall；挂到 runsc 的 main 不会自动跟踪 Sentry。`sleep 300` 只保持 sandbox 存活，attach 后不会持续触发读写 syscall。要验证 `pkg/sentry/syscalls/linux/sys_read_write.go` 中的 `Write` 断点，可在终端 1 改为运行：

```bash
./dev.sh run --platform=systrap --network=none do /bin/sh -c 'while :; do echo tick; sleep 1; done'
```

在终端 2 重新查询 Sentry PID，attach 后按 F5 继续，每秒的输出会触发 `Write`。结束时先在调试器中 Disconnect，再到终端 1 按 Ctrl+C 停止测试 sandbox。

### Gofer 文件请求断点

先断开 Sentry 调试会话，再使用同一个 Attach 配置输入对应的 Gofer PID；`dev.sh ps` 中命令以 `runsc-gofer` 开始的行就是 Gofer。它与同一 sandbox 的 Sentry 具有相同的 PPID 和容器 ID。

默认启用 `directfs`，部分文件访问会由 Sentry 直接执行。验证 Gofer 文件请求时，可在原 sandbox 的终端按 Ctrl+C，再使用下面的查询循环。命令只查询每次不同的路径，保留默认内存 overlay：

```bash
./dev.sh run --platform=systrap --network=none --directfs=false do /bin/sh -c 'i=0; while :; do i=$((i+1)); test -e "/etc/gofer-probe-$i"; echo "probe $i"; sleep 1; done'
```

重新查询 Gofer PID，在 `runsc/gofer/fs/lisafs.go` 的 `controlFDLisa.Walk` 函数中设置断点（例如 `childHostFD, err := tryOpen(...)` 这一行），再 F5 Attach 并继续运行。每次新的路径查询都会触发文件查找，可以查看 `name`、`fd.hostFD` 等变量。`WalkStat` 用于共享模式的缓存校验；`controlFDLisa.Open` 用于观察打开文件；`openFDLisa.Read` 只覆盖经 Gofer RPC 完成的读取，已传递给 Sentry 的主机 FD 可绕过它。

`runsc/cmd/gofer.go` 的 `Gofer.Execute` / `Gofer.serve` 属于启动及服务建立阶段；附加到已经运行的进程后，这些启动语句通常已经执行完毕。

## 调试通道

Launch 使用 Ubuntu 的 `dlv dap`，Attach 使用 `dlv --headless attach PID`，二者都只监听 `127.0.0.1:38697`。macOS 的同端口也只绑定 loopback；Python 转发器通过 Apple Container 标准输入输出和 Linux socat 连接它，不需要 SSH 或外部监听地址。Delve 作为 VSCode 后台任务运行，Launch 以 `DAP server listening at:`、Attach 以 `API server listening at:` 作为就绪标记。正常断开、连接意外关闭或转发任务终止时，Linux 调试器会退出并释放会话锁；Attach 会 detach，让目标进程继续运行。下次 F5 自动重新启动服务。若此前手动运行了 `dev.sh dap` 或 `dev.sh attach PID`，请先结束该终端中的旧服务，再使用 F5 自动任务，避免端口冲突。

Go launch / attach 配置使用 [Delve 原生 DAP](https://github.com/golang/vscode-go/blob/master/docs/debugging.md#remote-debugging)。`program` 指向 Linux 可见的真实二进制路径，`substitutePath` 将本地源码根目录映射到空前缀，对应当前 Bazel 产物中的 `runsc/main.go`、`pkg/sentry/...` 等相对路径。更改 `DEBUG_PORT` 后，需要同步调整 `.vscode/launch.json`；更改 `WORKDIR` 后，同步修改 sandbox 配置的 `--root`。

`setup` 下载官方 Go 并核对官方 SHA256，然后通过 Go module 安装 Delve、Bazelisk。版本可在 `.env` 固定。首次 Bazel 构建还会下载 upstream 固定的 Go SDK / C++ 工具链，可能耗时较长。构建缓存保存在 Linux 的 `/var/tmp/gvisor-debug`，避免和 macOS 缓存混用。

当前未绑定上游源码时，`doctor` 会明确报错；不会把模拟程序的调试结果报告成 gVisor 的真实运行结果。

已在 Ubuntu ARM64 上用 upstream `e45d53c763ac` 验证 `//:release` 完整构建和 `do /bin/echo sandbox-ready` 真实 sandbox。经 macOS → Apple Container → Linux Delve DAP 通道，已验证 runsc 的 `main.main` 源码断点、源码映射、变量读取、单步进入 `maincli.Main` 和退出清理；也已验证 headless Attach 真实 Sentry，在 `linux.Write` 中命中源码断点、读取 `sysno=64`、单步并 detach，以及 Attach Gofer、读取包含 `lisafs.(*Server).Wait` 和 `cmd.(*Gofer).serve` 的调用栈及变量后 detach。
