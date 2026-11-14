# 仓库维护工具

[`migrate_layout.py`](migrate_layout.py) 用于从旧目录更新代码后，迁移未纳入 Git 的本地状态：

```bash
# 先停止调试，再从仓库根目录执行；可以重复运行。
python3 tools/migrate_layout.py
```

支持原来的 `environments/` 布局，也支持将 `runtimes/firecracker/`、`runtimes/cloud-hypervisor/`、`runtimes/gvisor/` 的本地状态迁移到 `runtimes/fc/`、`runtimes/ch/`、`runtimes/gv/`。处理 `.env`、`bin/` 和 `output/`，更新本地工作区、源码挂载记录和编译数据库中的旧绝对路径，以及工作区的配置目录显示名称。已有设置、文件权限和内核 Docker 项目/缓存名称会保留；新旧位置都存在本地状态时，会在移动前报告冲突。

该工具只迁移本地状态。受 Git 管理的代码和配置随版本更新移动；它不会删除 Docker 卷、重建镜像或修改上游源码。执行后重新打开新路径的工作区。
