# 网络实验

| 目录 | 内容 |
| --- | --- |
| [`cilium/bgp/`](cilium/bgp/README.md) | Cilium BGP 实验与所需 Helm chart |
| [`cilium/bgp-ecmp/`](cilium/bgp-ecmp/README.md) | Cilium BGP ECMP 拓扑与部署脚本 |
| [`dpdk/`](dpdk/README.md) | DPDK 相关实验笔记 |
| [`katran/`](katran/README.md) | Katran 相关实验笔记 |

Cilium 实验在 Linux 主机或 VM 内运行，分别使用独立的集群、拓扑名称及 kubeconfig；部署、验证和清理方式见 [Cilium 公共指南](cilium/README.md)。DPDK / Katran 目录仍是源码构建与硬件实验笔记，尚未提供自动化部署环境。
