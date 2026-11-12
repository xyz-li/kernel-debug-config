# Runtime 调试环境

三套调试环境分别位于独立子目录，共用脚本集中在 `common/`。

```text
environments/
├── fc/          # Firecracker VMM / Guest 调试
├── gvisor/      # runsc / Sentry / Gofer，使用 Delve
├── kata/        # runtime-rs / kata-agent / shim-ctl，使用 GDB
└── common/      # 源码绑定、工具安装、调试通道及测试
```

各环境保留自己的 `.env`、`.vscode/`、`bin/` 和 `output/`；本地配置及运行产物被 Git 忽略。已有 Ubuntu Host 和 Linux 构建缓存继续复用。

从仓库根目录调用：

```bash
./environments/fc/dev.sh help
./environments/gvisor/dev.sh help
./environments/kata/dev.sh help
```

接入源码和单步调试见[仓库指南](../README.md)，环境说明见 [Firecracker](fc/README.md)、[gVisor](gvisor/README.md)、[Kata](kata/README.md)。

配置检查：

```bash
python3 -m unittest discover -s environments/common/tests -v
```
