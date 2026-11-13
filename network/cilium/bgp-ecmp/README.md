# Cilium BGP ECMP 负载均衡演示

在基础 BGP 拓扑上，由 rack1 的两个节点宣告同一 Service ExternalIP，tor1 安装两条等价下一跳。Linux 环境要求、独立 kubeconfig、部署与清理行为见 [公共指南](../README.md)。

| 项目 | 配置 |
| --- | --- |
| 集群 / 拓扑 | `cilium-bgp-ecmp` |
| context | `kind-cilium-bgp-ecmp` |
| rack0 | control-plane、worker；AS65010；对等体 tor0 `10.0.0.1` |
| rack1 | worker2、worker3；AS65011；对等体 tor1 `10.0.0.2` |
| nginx 后端 | 限制调度到 rack0；默认一个副本，control-plane 默认 taint 不会因为 rack 标签自动移除 |
| Service VIP | `10.100.0.100`（ExternalIP） |
| Cilium 转发 | native routing、kube-proxy replacement、DSR |

## 路由宣告

所有节点都宣告自身 PodCIDR。rack1 的 `ibgp-peer-pods-and-vip` 同时选择 `bgp-pods` 和 `bgp-vip`：

```yaml
advertisements:
  matchExpressions:
  - key: advertise
    operator: In
    values: [bgp-pods, bgp-vip]
```

这样 CoreDNS 或其他 Pod 即使调度到 rack1，也有相应的底层路由；nginx 放在 rack0 并不能替代 rack1 Pod 网络的路由配置。Service VIP 仍只由 rack1 宣告，nginx 的 `app=nginx` Service 标签与宣告 selector 对应。

`topo.yaml` 保留 rack1 上的 `cilium-ext0` dummy 和 `10.100.0.1/24`。该地址会产生连接路由，**不等于将 Service VIP `10.100.0.100` 配置为本机地址**；Service 流量由 Cilium 的 BPF 数据面处理，BGP 宣告本身不完成转发。不能把 dummy 的存在作为 VIP 可达的验证。

## 使用方法

从仓库根目录，在 Linux 上执行：

```bash
sudo ./network/cilium/bgp-ecmp/all-in-one.sh
sudo ./network/cilium/bgp-ecmp/verify.sh
sudo ./network/cilium/bgp-ecmp/destroy.sh
```

部署仅通过 `svc.yaml` 创建 nginx，避免先用 `kubectl create deploy` 创建一个没有 rack 限制的临时版本。BGP CRD 全部 Established 后再应用 BGP 和服务配置。

## ECMP 检查

```bash
sudo docker exec clab-cilium-bgp-ecmp-tor1 vtysh -c 'show bgp ipv4 unicast 10.100.0.100/32'
sudo docker exec clab-cilium-bgp-ecmp-tor1 vtysh -c 'show ip route 10.100.0.100/32'
sudo docker exec clab-cilium-bgp-ecmp-server0 curl --max-time 10 http://10.100.0.100/
```

`verify.sh` 要求 tor1 的已安装路由同时包含 `10.0.3.2` 和 `10.0.4.2`，并检查四个节点的 Pod 路由、DNS 和 HTTP。ECMP 通常按流哈希，同一连接不会逐包轮流使用两个节点。更多故障切换或负载分布测试应另外设计。

本地 kubeconfig 为 `output/kubeconfig`。当前修复的静态及模拟验证范围见公共指南，真实连通性需要在 Linux 上执行上述检查。
