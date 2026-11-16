# VSCode 内核调试

调试配置已集中到 `kernel/common/vscode`，两个有效环境通过链接复用。
执行 `./kernel/dev.sh bind /path/to/linux` 或 `./kernel/dev.sh source <版本>`，然后打开对应环境 `output/debug.local.code-workspace`。
完整用法见 [内核环境指南](../README.md)。
