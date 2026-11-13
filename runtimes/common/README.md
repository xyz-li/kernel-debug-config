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
| `tools.py` | 校验并安装官方 Go 工具链 |
| `tests/` | 公共工具和运行时调试配置的回归测试 |

共享配置放在 `runtimes/common/.env`，可参考 `.env.example`；四种运行时先读取共享设置，再读取自己的 `.env`。Firecracker 和 Cloud Hypervisor 的运行目录、网络、密钥与磁盘仍由各自的 `config.sh` 决定。

Kata 的 OCI bundle 和 VM 资产检查属于 `runtimes/kata/tools/`，不再放在公共目录。
