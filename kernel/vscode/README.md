# 手工 VSCode 配置模板

这里保留可复制到 Linux 内核源码目录的手工配置：`launch.json`、`settings.json` 和 `c_cpp_properties.json`。使用时自行修改符号文件、GDB 路径和编译数据库位置。

日常使用推荐各环境的 `.code-workspace`，通过 `dev.sh bind` 绑定源码后直接 F5。自动构建、QEMU 生命周期和源码映射见 [内核调试指南](../README.md)。
