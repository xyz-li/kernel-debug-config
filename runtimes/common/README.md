# 运行时公共工具

这里放置可被多个运行时复用的工具。运行时专属配置仍保存在各自目录。

| 目录或文件 | 职责 |
| --- | --- |
| [`host/`](host/README.md) | Ubuntu ARM64 Apple Container Host 镜像、创建入口 |
| [`guest/console.py`](guest/console.py) | 独立 PTY、Unix socket 串口和日志回放 |
| [`guest/ssh.sh`](guest/ssh.sh) | 专用 SSH 密钥、固定主机公钥和命令参数传输 |
| `bind.py` | 检查上游源码，保存本地绑定并生成 VSCode 工作区 |
| `config.sh` | gVisor/Kata 共用的 Host、工具安装与命令传输 |
| `dap_bridge.py` | macOS 到 Linux 的 Delve DAP 通道 |
| `dlv_server.py` | Linux Delve 的会话锁与退出清理；转发断开时自动结束调试器 |
| `mi-pipe.sh` | GDB/MI 输入转发；隔离暂停等辅助命令的标准输入 |
| `tools.py` | 校验并安装官方 Go 工具链 |
| `tests/` | 公共工具和运行时调试配置的回归测试 |

共享配置放在 `runtimes/common/.env`，可参考 `.env.example`；各运行时先读取共享设置，再读取自己的 `.env`。Firecracker 和 Cloud Hypervisor 的运行目录、网络、密钥与磁盘仍由各自的 `config.sh` 决定。QEMU 使用独立普通容器，不读取 `MACHINE` 来启动 machine；具体入口见 [QEMU 指南](../qemu/README.md)。

Kata 的 OCI bundle 和 VM 资产检查属于 `runtimes/kata/tools/`，不再放在公共目录。

## GDB 主通道与辅助控制命令

FC、CH、Kata 的 macOS 调试配置都使用 `gdb-pipe.sh`，但调试适配器会以两种方式调用它：

| 调用类型 | FC 调用示例（路径为示意） | 标准输入的用途 |
| --- | --- | --- |
| GDB/MI 主通道 | `gdb-pipe.sh --guest-mode liquidmetal /path/to/gdb-host.sh --interpreter=mi` | 持续传递 GDB/MI 命令，需要 `container machine run --interactive` |
| 辅助控制命令 | `gdb-pipe.sh --guest-mode liquidmetal "kill -5 <FC_PID>"` | 一次性发送信号，不读取输入；连接 `/dev/null` |

主通道的实际通信关系为 `VSCode → DAP → OpenDebugAD7 → GDB/MI → Linux GDB → FC`。DAP 是 VSCode 与调试适配器之间的协议，GDB/MI 是调试适配器与 GDB 之间的协议，两段各有自己的输入流。

### 配置项、自动命令与实现路径

这几部分分别负责不同的工作：

- `pipeTransport` 配置执行通道：`pipeProgram` 指定本机包装脚本，`pipeArgs` 提供模式等参数，`debuggerPath` 指定主通道要启动的调试器或启动脚本。适配器也会复用 `pipeProgram` 执行辅助命令。
- `setupCommands` 配置 GDB 初始化：GDB 启动后，适配器通过主通道发送这些命令，例如 `set pagination off`、`handle SIG35 nostop noprint pass`、`-break-insert -f firecracker::main`。
- `kill -5 <PID>` 是适配器内部按需生成的辅助控制命令，没有单独的 `launch.json` 配置项，也不是 `setupCommands` 中的一条初始化命令。

以 FC 为例，按下面的路径查找配置和实现：

| 负责的部分 | 路径与入口 |
| --- | --- |
| 生成辅助命令 | 微软 MIEngine 的 [`src/MICore/Transports/PipeTransport.cs`](https://github.com/microsoft/MIEngine/blob/d8f7a3d17e1607f06a3ba4f8453e609f4e0f3a23/src/MICore/Transports/PipeTransport.cs#L41-L49)：`PipeTransport.Interrupt()` 生成 `kill -5 <PID>`，再通过配置的管道执行 |
| 指定执行通道及 GDB 初始化 | 本仓库 [`runtimes/fc/.vscode/launch.json`](../fc/.vscode/launch.json)：分别查看 `pipeTransport` 和 `setupCommands` |
| 将调用转交 Ubuntu Host | 本仓库 [`runtimes/fc/gdb-pipe.sh`](../fc/gdb-pipe.sh)：接收参数，通过 `container machine run` 执行 |
| 准备环境并启动 GDB | 本仓库 [`runtimes/fc/gdb-host.sh`](../fc/gdb-host.sh) → [`runtimes/fc/run-firecracker.sh`](../fc/run-firecracker.sh) 的 `debug-mi` 分支 |
| 区分两类调用的输入方式 | 本仓库 [`runtimes/common/mi-pipe.sh`](mi-pipe.sh)：`prepare_mi_pipe()` 决定是否启用交互输入 |

FC 的调用链可以分别展开为：

```text
主通道：launch.json 的 pipeTransport
        → gdb-pipe.sh → gdb-host.sh → run-firecracker.sh debug-mi → GDB
        GDB 启动后，适配器经主通道发送 setupCommands。

辅助调用：MIEngine 的 PipeTransport.Interrupt()
          → gdb-pipe.sh --guest-mode liquidmetal "kill -5 <FC_PID>"
          → container machine run → Ubuntu 中的 kill
```

FC 配置中的 `${workspaceFolder}` 指调试配置目录 `runtimes/fc`；`firecracker-source` 是另一个工作区根目录，指向上游源码。上述包装脚本在本配置仓库中，命令生成逻辑则在 C/C++ 扩展使用的 MIEngine 中。

CH 对应 [`runtimes/ch/.vscode/launch.json`](../ch/.vscode/launch.json)、[`runtimes/ch/gdb-pipe.sh`](../ch/gdb-pipe.sh) 和 [`runtimes/ch/gdb-host.sh`](../ch/gdb-host.sh)；Kata 对应 [`runtimes/kata/.vscode/launch.json`](../kata/.vscode/launch.json)、[`runtimes/kata/gdb-pipe.sh`](../kata/gdb-pipe.sh) 和 [`runtimes/kata/gdb-host.sh`](../kata/gdb-host.sh)。三者都引用公共的 `mi-pipe.sh`。

### 暂停行为与输入隔离

点击“暂停”，或在程序运行中增加、删除断点时，适配器可能先通过辅助调用向被调试进程发送 `SIGTRAP`（`kill -5`），由 GDB 捕获并暂停，再修改断点或向界面报告暂停。这里的 `kill` 是发送信号的工具；这条命令用于触发调试暂停。

原来的包装脚本无条件添加 `--interactive`。辅助进程继承的是调试适配器的标准输入；继续转发它，会与适配器竞争 DAP 数据，或改变共享输入描述符的读取标志。已复现的结果是适配器出现读取异常，FC 被 GDB 停住，VSCode 却仍显示“正在运行”，API 请求也因处理线程暂停而等待。

[`mi-pipe.sh`](mi-pipe.sh) 的处理规则是：参数中包含 `--interpreter=mi*` 时，保留主通道的交互输入；其他调用先执行 `exec </dev/null`，再以非交互方式运行控制命令。FC、CH、Kata 的包装脚本共同使用此规则。

若旧会话已经失去同步，需要结束该调试会话后重新 Launch；新脚本无法恢复旧适配器已经中断的协议读取。正常命中 API 断点时，界面会显示暂停位置，终端中的 API 命令仍会等待；继续执行并发送 HTTP 响应后，命令才返回。

回归测试检查主通道的输入保留，以及辅助命令不会消费父进程的 DAP 输入。实际 C/C++ 调试适配器验证覆盖运行中设置 API 断点、命中并读取调用栈、单步、继续、收到 JSON 响应，以及独立的暂停和继续操作。
