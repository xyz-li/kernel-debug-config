# Cilium BGP ECMP 负载均衡演示

本项目演示 Cilium 的 BGP ECMP（Equal-Cost Multi-Path，等价多路径）负载均衡功能，通过 BGP 协议宣告 Service ExternalIP，实现多路径负载均衡。

## 项目结构

```
bgp-ecmp/
├── all-in-one.sh      # 一键部署脚本（包含 modprobe dummy）
├── destroy.sh         # 清理环境脚本
├── kind.yaml          # Kind 集群配置（4节点集群）
├── topo.yaml          # Containerlab 网络拓扑配置（包含 dummy 网卡设置）
├── bgp-config.yaml    # Cilium BGP 配置（Service ExternalIP 宣告）
├── svc.yaml           # Nginx 服务（含 externalIPs）和 Deployment
└── cilium/            # Cilium Helm Chart（用于安装）
```

## 网络拓扑

```
                    router0 (AS 65000)
                    10.0.0.0/32
                   /            \
                  /              \
            tor0 (AS 65010)    tor1 (AS 65011)
            10.0.0.1/32        10.0.0.2/32
            /        \         /        \
           /          \       /          \
      server0      server1  server2   server3
      (control)    (worker) (worker2) (worker3)
      rack0        rack0    rack1     rack1
      10.0.1.2     10.0.2.2 10.0.3.2  10.0.4.2
                            [VIP]     [VIP]
                          10.100.0.1 10.100.0.1
                          (dummy网卡) (dummy网卡)
```

### 关键差异（与基础 BGP 版本对比）

1. **Dummy 网卡配置**: 在 server2 和 server3 (rack1) 上创建 `cilium-ext0` dummy 网卡，配置 VIP 地址 `10.100.0.1/24`
2. **Service ExternalIP**: nginx Service 配置了 externalIPs: `10.100.0.100`
3. **ECMP 路由**: 两个节点都宣告相同的 VIP，实现多路径负载均衡
4. **Pod 调度策略**: nginx pods 仅调度到 rack0，而 VIP 由 rack1 节点宣告

## ECMP 工作原理

### 1. VIP 配置

在 worker2 和 worker3 节点上配置相同的 VIP 地址：

```bash
# topo.yaml 中的配置
- ip link add cilium-ext0 type dummy
- ip addr add 10.100.0.1/24 dev cilium-ext0
- ip link set dev cilium-ext0 up
```

这个 VIP 用于接收发往 `10.100.0.100` 的流量。

### 2. BGP 路由宣告

rack1 的两个节点都通过 BGP 宣告相同的 VIP 路由：

```yaml
apiVersion: cilium.io/v2
kind: CiliumBGPAdvertisement
metadata:
  name: bgp-advertisements-vip
spec:
  advertisements:
  - advertisementType: Service
    service:
      addresses:
      - ExternalIP
    selector:
      matchExpressions:
        - { key: app, operator: In, values: [ nginx ] }
```

### 3. ECMP 路由形成

由于 tor1 从 worker2 和 worker3 收到相同的路由（10.100.0.100/32），并且这两条路由的 metric 相同，路由器会将它们作为等价路径安装到路由表中，实现 ECMP 负载均衡。

### 4. 流量路径

```
客户端
  ↓
router0
  ↓
tor1 (ECMP 路由选择)
  ↓ ↓
worker2 或 worker3 (10.100.0.100 → VIP)
  ↓
Cilium BPF (DNAT)
  ↓
nginx Pod (在 rack0 节点上)
```

## BGP 配置详解

### 宣告配置

本项目配置了两种宣告类型：

1. **Pod CIDR 宣告**（rack0）:
```yaml
apiVersion: cilium.io/v2
kind: CiliumBGPAdvertisement
metadata:
  name: bgp-advertisements-pods
spec:
  advertisements:
  - advertisementType: "PodCIDR"
```

2. **Service ExternalIP 宣告**（rack1）:
```yaml
apiVersion: cilium.io/v2
kind: CiliumBGPAdvertisement
metadata:
  name: bgp-advertisements-vip
spec:
  advertisements:
  - advertisementType: Service
    service:
      addresses:
      - ExternalIP
    selector:
      matchExpressions:
        - { key: app, operator: In, values: [ nginx ] }
```

### 节点配置

- **rack0 节点**（control-plane, worker）:
  - Local ASN: 65010
  - Peer: tor0 (10.0.0.1)
  - 宣告: **PodCIDR**（通过 `ibgp-peer-pods`）

- **rack1 节点**（worker2, worker3）:
  - Local ASN: 65011
  - Peer: tor1 (10.0.0.2)
  - 宣告: **Service ExternalIP**（通过 `ibgp-peer-vip`）

```yaml
# rack1 配置示例
apiVersion: cilium.io/v2
kind: CiliumBGPClusterConfig
metadata:
  name: cilium-bgp-rack1
spec:
  nodeSelector:
    matchLabels:
      rack: rack1
  bgpInstances:
  - name: "instance-65011"
    localASN: 65011
    peers:
    - name: "peer-65011-tor1"
      peerASN: 65011
      peerAddress: "10.0.0.2"
      peerConfigRef:
        name: ibgp-peer-vip
```

## 使用方法

### 部署环境

运行一键部署脚本：

```bash
./all-in-one.sh
```

该脚本会自动完成：
1. 加载 dummy 内核模块（`modprobe dummy`）
2. 创建 Kind 集群（4节点）
3. 部署 Containerlab 网络拓扑（包含 dummy 网卡配置）
4. 下载并加载 Cilium 相关镜像
5. 通过 Helm 安装 Cilium（v1.19.0）
6. 部署 nginx Deployment
7. 创建带有 ExternalIP 的 nginx Service
8. 配置 Cilium BGP（包含 VIP 宣告）

### 验证 BGP ECMP

查看 tor1 上的 BGP 路由：

```bash
# 查看 BGP 路由表，应该看到来自两个节点的相同路由
docker exec -ti clab-cilium-lb-tor1 vtysh -c "show bgp ipv4"
```

你应该看到 `10.100.0.100/32` 有两条下一跳：
- 下一跳：10.0.3.2（worker2）
- 下一跳：10.0.4.2（worker3）

查看路由表中的 ECMP 路由：

```bash
# 查看 IP 路由表
docker exec -ti clab-cilium-lb-tor1 ip route show
```

### 测试负载均衡

从 control-plane 节点访问 VIP：

```bash
# 多次访问，流量会在 worker2 和 worker3 之间负载均衡
docker exec -ti cilium-lb-control-plane curl 10.100.0.100

# 查看连接统计（可选）
docker exec -ti cilium-lb-control-plane curl -v 10.100.0.100
```

### 验证配置

```bash
# 查看 Cilium BGP 配置
kubectl get ciliumbgpclusterconfigs
kubectl get ciliumbgppeerconfigs
kubectl get ciliumbgpadvertisements

# 查看 nginx Service
kubectl get svc nginx -o yaml

# 查看 nginx Pods（应该都在 rack0）
kubectl get pods -o wide -l app=nginx

# 检查 worker2/worker3 上的 dummy 网卡
docker exec clab-cilium-lb-server2 ip addr show cilium-ext0
docker exec clab-cilium-lb-server3 ip addr show cilium-ext0
```

### 清理环境

```bash
./destroy.sh
```

## 关键技术点

### 1. Dummy 网卡的作用

Dummy 网卡用于接收发往 VIP 的流量。如果没有配置 dummy 网卡和 VIP 地址，内核会直接丢弃目标地址为 VIP 的数据包。配置后：

```
数据包到达 → 匹配到 VIP 地址 → 被内核接收 → Cilium BPF 处理 → DNAT 到后端 Pod
```

### 2. BGP ECMP 负载均衡

ECMP 是在路由层面实现的负载均衡：
- **等价路径**: 多条路由的 metric 相同，被视为等价
- **负载分担**: 流量在多条路径之间分配（通常基于流的哈希）
- **高可用**: 某条路径失效时，流量自动切换到其他路径

### 3. Service ExternalIP vs LoadBalancer

本示例使用 `externalIPs` 而非 `type: LoadBalancer`：
- **ExternalIP**: 手动指定的外部 IP，需要自行保证可达性
- **LoadBalancer**: 通常由云提供商自动分配和配置

在本示例中，通过 BGP 宣告 ExternalIP 实现了类似 LoadBalancer 的效果。

### 4. Pod 调度与 VIP 宣告分离

本示例展示了一种有趣的架构：
- **Pod 运行位置**: rack0（control-plane, worker）
- **VIP 宣告位置**: rack1（worker2, worker3）

这种设计可以实现：
- 流量入口集中在特定节点（rack1）
- 实际服务分布在其他节点（rack0）
- 通过 Cilium BPF 实现跨节点的流量转发

## 网络配置总结

| 节点 | IP 地址 | AS 号 | BGP Peer | VIP | 宣告类型 | nginx Pod |
|------|---------|-------|----------|-----|----------|-----------|
| router0 | 10.0.0.0/32 | 65000 | tor0, tor1 | - | - | - |
| tor0 | 10.0.0.1/32 | 65010 | router0, rack0 节点 | - | - | - |
| tor1 | 10.0.0.2/32 | 65011 | router0, rack1 节点 | - | - | - |
| control-plane | 10.0.1.2/24 | 65010 | tor0 | - | PodCIDR | ✓ |
| worker | 10.0.2.2/24 | 65010 | tor0 | - | PodCIDR | ✓ |
| worker2 | 10.0.3.2/24 | 65011 | tor1 | 10.100.0.1/24 | ExternalIP | ✗ |
| worker3 | 10.0.4.2/24 | 65011 | tor1 | 10.100.0.1/24 | ExternalIP | ✗ |

### Service 配置

- **Service Name**: nginx
- **Type**: ClusterIP
- **ExternalIP**: 10.100.0.100
- **Port**: 80

## 故障排查

### 1. VIP 无法访问

检查 dummy 网卡配置：
```bash
docker exec clab-cilium-lb-server2 ip addr show cilium-ext0
docker exec clab-cilium-lb-server3 ip addr show cilium-ext0
```

### 2. BGP 路由未宣告

检查 BGP 对等状态：
```bash
# 在 tor1 上查看 BGP 邻居
docker exec -ti clab-cilium-lb-tor1 vtysh -c "show bgp neighbors"

# 检查 Cilium BGP 状态
kubectl get ciliumbgpnodeconfigs -A
```

### 3. ECMP 未生效

检查路由表中是否有多条等价路由：
```bash
docker exec -ti clab-cilium-lb-tor1 ip route show 10.100.0.100
```

应该显示类似：
```
10.100.0.100 nhid 42 proto bgp metric 20
    nexthop via 10.0.3.2 dev net1 weight 1
    nexthop via 10.0.4.2 dev net2 weight 1
```

## 依赖项

- Docker
- Kind
- Containerlab
- kubectl
- Helm
- Linux kernel 支持 dummy 模块

## 相关资源

- [Cilium BGP 文档](https://docs.cilium.io/en/stable/network/bgp-control-plane/)
- [Cilium Service Load Balancing](https://docs.cilium.io/en/stable/network/lb-ipam/)
- [FRRouting ECMP 文档](https://docs.frrouting.org/en/latest/bgp.html#multipath)
- [Linux ECMP 路由](https://www.kernel.org/doc/Documentation/networking/multipath-routing.txt)
- [使用 Containerlab + Kind 快速部署 Cilium BGP 环境](https://cloud.tencent.com/developer/article/2187631?policyId=1004)
- [L4LB for Kubernetes: Theory and Practice with Cilium+BGP+ECMP](https://arthurchiao.art/blog/k8s-l4lb/)

## 与基础 BGP 版本的对比

| 特性 | bgp | bgp-ecmp |
|------|-----|----------|
| 宣告类型 | PodCIDR | PodCIDR + Service ExternalIP |
| Dummy 网卡 | ✗ | ✓ |
| ExternalIP | ✗ | ✓ (10.100.0.100) |
| ECMP 负载均衡 | ✗ | ✓ |
| VIP 配置 | ✗ | ✓ (10.100.0.1/24) |
| nginx 副本数 | 2 | 动态创建 |
| Pod 调度限制 | ✗ | ✓ (仅 rack0) |
