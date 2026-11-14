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
| `mi-pipe.sh` | GDB/MI 输入转发；隔离暂停等辅助命令的标准输入 |
| `tools.py` | 校验并安装官方 Go 工具链 |
| `tests/` | 公共工具和运行时调试配置的回归测试 |

共享配置放在 `runtimes/common/.env`，可参考 `.env.example`；四种运行时先读取共享设置，再读取自己的 `.env`。Firecracker 和 Cloud Hypervisor 的运行目录、网络、密钥与磁盘仍由各自的 `config.sh` 决定。

Kata 的 OCI bundle 和 VM 资产检查属于 `runtimes/kata/tools/`，不再放在公共目录。

## GDB 主通道与辅助控制命令

FC、CH、Kata 的 macOS 调试配置都使用 `gdb-pipe.sh`，但调试适配器会以两种方式调用它：

| 调用类型 | FC 调用示例（路径为示意） | 标准输入的用途 |
| --- | --- | --- |
| GDB/MI 主通道 | `gdb-pipe.sh --guest-mode liquidmetal /path/to/gdb-host.sh --interpreter=mi` | 持续传递 GDB/MI 命令，需要 `container machine run --interactive` |
| 辅助控制命令 | `gdb-pipe.sh --guest-mode liquidmetal "kill -5 <FC_PID>"` | 一次性发送信号，不读取输入；连接 `/dev/null` |

主通道的实际通信关系为 `VSCode → DAP → OpenDebugAD7 → GDB/MI → Linux GDB → FC`。DAP 是 VSCode 与调试适配器之间的协议，GDB/MI 是调试适配器与 GDB 之间的协议，两段各有自己的输入流。

点击“暂停”，或在程序运行中增加、删除断点时，适配器可能先通过辅助调用向被调试进程发送 `SIGTRAP`（`kill -5`），由 GDB 捕获并暂停，再修改断点或向界面报告暂停。这里的 `kill` 是发送信号的工具；这条命令用于触发调试暂停。

原来的包装脚本无条件添加 `--interactive`。辅助进程继承的是调试适配器的标准输入；继续转发它，会与适配器竞争 DAP 数据，或改变共享输入描述符的读取标志。已复现的结果是适配器出现读取异常，FC 被 GDB 停住，VSCode 却仍显示“正在运行”，API 请求也因处理线程暂停而等待。

[`mi-pipe.sh`](mi-pipe.sh) 的处理规则是：参数中包含 `--interpreter=mi*` 时，保留主通道的交互输入；其他调用先执行 `exec </dev/null`，再以非交互方式运行控制命令。FC、CH、Kata 的包装脚本共同使用此规则。

若旧会话已经失去同步，需要结束该调试会话后重新 Launch；新脚本无法恢复旧适配器已经中断的协议读取。正常命中 API 断点时，界面会显示暂停位置，终端中的 API 命令仍会等待；继续执行并发送 HTTP 响应后，命令才返回。

回归测试检查主通道的输入保留，以及辅助命令不会消费父进程的 DAP 输入。实际 C/C++ 调试适配器验证覆盖运行中设置 API 断点、命中并读取调用栈、单步、继续、收到 JSON 响应，以及独立的暂停和继续操作。
