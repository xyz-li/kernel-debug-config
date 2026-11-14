# Cilium BGP 基础演示

使用四节点 Kind 集群、Cilium 和 FRR，向底层网络宣告所有节点的 PodCIDR。完整的 Linux 环境要求、kubeconfig、等待与清理说明见 [部署与验证指南](../README.md)。

```text
                  client0 198.18.0.2
                        |
                     router0 AS65000
                        /       \
             tor0 AS65010       tor1 AS65011
               /      \           /      \
         control-plane worker   worker2  worker3
              rack0                 rack1
```

- 集群与拓扑名：`cilium-bgp`，context：`kind-cilium-bgp`。
- 节点地址依次为 `10.0.1.2`、`10.0.2.2`、`10.0.3.2`、`10.0.4.2`。
- tor0 / tor1 的 loopback 为 `10.0.0.1` / `10.0.0.2`，与所属 rack 的节点建立 iBGP；上游建立 eBGP。
- Cilium 使用 `ipam.mode=kubernetes`、`routingMode=native`、kube-proxy replacement；两组节点均宣告自己的 PodCIDR。
- `svc.yaml` 中 nginx 为两个副本，Service 为 ClusterIP。本实验不宣告 Service VIP；验证通过实际 Pod IP 访问 HTTP。

从仓库根目录，在 Linux 上执行：

```bash
sudo ./network/cilium/bgp/all-in-one.sh
sudo ./network/cilium/bgp/verify.sh
sudo ./network/cilium/bgp/destroy.sh
```

`all-in-one.sh` 会在部署完成后自动验证。日常检查可直接执行 `verify.sh`。查看路由：

```bash
sudo docker exec clab-cilium-bgp-router0 vtysh -c 'show bgp ipv4 unicast summary'
sudo docker exec clab-cilium-bgp-router0 vtysh -c 'show ip route bgp'
```

本地 kubeconfig 为 `output/kubeconfig`，实际路径与权限见公共指南。脚本支持从任意目录调用，部署失败返回非零并保留资源供检查。
