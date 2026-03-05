# Cilium BGP 基础演示

本项目演示 Cilium 的 BGP 功能，通过 BGP 协议宣告 Pod CIDR 到网络中。

## 项目结构

```
bgp/
├── all-in-one.sh      # 一键部署脚本
├── destroy.sh         # 清理环境脚本
├── kind.yaml          # Kind 集群配置（4节点集群）
├── topo.yaml          # Containerlab 网络拓扑配置
├── bgp-config.yaml    # Cilium BGP 配置
├── svc.yaml           # Nginx 服务和 Deployment
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
```

### 组件说明

- **router0**: BGP 路由器，AS 65000，作为上游路由器
- **tor0/tor1**: ToR（Top of Rack）交换机，分别为 AS 65010 和 AS 65011
- **server0-3**: 通过 `network-mode: container` 方式附加到 Kind 节点上，提供网络连接
- **Kubernetes 集群**:
  - 1个 control-plane 节点（rack0）
  - 3个 worker 节点（rack0: 1个，rack1: 2个）

## BGP 对等关系

### 拓扑中的 BGP 对等

1. **router0 ↔ tor0/tor1**: eBGP（外部 BGP）
   - router0 (AS 65000) 与 tor0 (AS 65010) 和 tor1 (AS 65011) 建立 eBGP 邻居

2. **tor0 ↔ server0/server1**: iBGP（内部 BGP）
   - tor0 与 rack0 中的 Kubernetes 节点建立 iBGP 邻居（AS 65010）

3. **tor1 ↔ server2/server3**: iBGP（内部 BGP）
   - tor1 与 rack1 中的 Kubernetes 节点建立 iBGP 邻居（AS 65011）

### Cilium BGP 配置

Cilium 在 Kubernetes 节点上通过以下配置建立 BGP 对等：

- **rack0 节点**（control-plane, worker）:
  - Local ASN: 65010
  - Peer: tor0 (10.0.0.1, AS 65010)
  - 宣告类型: **PodCIDR**

- **rack1 节点**（worker2, worker3）:
  - Local ASN: 65011
  - Peer: tor1 (10.0.0.2, AS 65011)
  - 宣告类型: **PodCIDR**

## 主要功能

### 1. Pod CIDR 宣告

Cilium 通过 BGP 将每个节点的 Pod CIDR 宣告给对应的 ToR 交换机：

```yaml
apiVersion: cilium.io/v2
kind: CiliumBGPAdvertisement
metadata:
  name: bgp-advertisements-pods
spec:
  advertisements:
  - advertisementType: "PodCIDR"
```

### 2. 节点按 Rack 分组

使用 Kubernetes 节点标签 `rack=rack0` 和 `rack=rack1` 将节点分配到不同的机架，每个机架使用不同的 AS 号码。

### 3. iBGP 对等配置

```yaml
apiVersion: cilium.io/v2
kind: CiliumBGPPeerConfig
metadata:
  name: ibgp-peer-template
spec:
  families:
  - afi: ipv4
    safi: unicast
    advertisements:
      matchLabels:
        advertise: "bgp-pods"
```

## 使用方法

### 部署环境

运行一键部署脚本：

```bash
./all-in-one.sh
```

该脚本会自动完成：
1. 创建 Kind 集群（4节点）
2. 部署 Containerlab 网络拓扑（router0, tor0, tor1, server0-3）
3. 下载并加载 Cilium 相关镜像
4. 通过 Helm 安装 Cilium（v1.19.0）
5. 部署 nginx 服务（2个副本）
6. 配置 Cilium BGP

### 验证 BGP 连接

查看 ToR 交换机上的 BGP 状态：

```bash
# 查看 tor0 的 BGP 路由表
docker exec -ti clab-cilium-lb-tor0 vtysh -c "show bgp ipv4"

# 查看 tor1 的 BGP 路由表
docker exec -ti clab-cilium-lb-tor1 vtysh -c "show bgp ipv4"

# 查看 router0 的 BGP 路由表
docker exec -ti clab-cilium-lb-router0 vtysh -c "show bgp ipv4"
```

你应该能看到从 Cilium 节点宣告的 Pod CIDR 路由。

### 验证网络连通性

```bash
# 查看 Cilium BGP 状态
kubectl get ciliumbgpclusterconfigs
kubectl get ciliumbgppeerconfigs
kubectl get ciliumbgpadvertisements

# 查看 Pods
kubectl get pods -o wide

# 从 tor1 访问服务（注意：这个环境主要是演示 Pod CIDR 宣告）
docker exec -ti clab-cilium-lb-tor1 curl <pod-ip>
```

### 清理环境

```bash
./destroy.sh
```

## 技术要点

1. **Cilium CNI**: 使用 Cilium 作为 Kubernetes CNI，替代默认 CNI 和 kube-proxy
2. **BGP 路由宣告**: 通过 BGP 协议将 Pod 网络宣告到物理网络
3. **Rack 感知**: 使用节点标签实现机架感知的 BGP 配置
4. **FRRouting**: 使用 FRR 作为 BGP 路由软件
5. **Containerlab**: 使用 Containerlab 模拟数据中心网络拓扑

## 依赖项

- Docker
- Kind
- Containerlab
- kubectl
- Helm

## 网络配置总结

| 节点 | IP 地址 | AS 号 | BGP Peer | 角色 |
|------|---------|-------|----------|------|
| router0 | 10.0.0.0/32 | 65000 | tor0, tor1 | 路由器 |
| tor0 | 10.0.0.1/32 | 65010 | router0, server0, server1 | ToR 交换机 |
| tor1 | 10.0.0.2/32 | 65011 | router0, server2, server3 | ToR 交换机 |
| control-plane | 10.0.1.2/24 | 65010 | tor0 | K8s 控制平面 |
| worker | 10.0.2.2/24 | 65010 | tor0 | K8s Worker |
| worker2 | 10.0.3.2/24 | 65011 | tor1 | K8s Worker |
| worker3 | 10.0.4.2/24 | 65011 | tor1 | K8s Worker |

## 相关资源

- [Cilium BGP 文档](https://docs.cilium.io/en/stable/network/bgp-control-plane/)
- [FRRouting 文档](https://docs.frrouting.org/)
- [Containerlab 文档](https://containerlab.dev/)
- [使用 Containerlab + Kind 快速部署 Cilium BGP 环境](https://cloud.tencent.com/developer/article/2187631?policyId=1004)
- [L4LB for Kubernetes: Theory and Practice with Cilium+BGP+ECMP](https://arthurchiao.art/blog/k8s-l4lb/)
