# Cilium BGP 实验的部署与验证

两套实验使用相同的部署入口，各自拥有集群、拓扑和 kubeconfig：

| 实验 | Kind / Containerlab 名称 | Kubernetes context | 宣告内容 |
| --- | --- | --- | --- |
| [基础 BGP](bgp/README.md) | `cilium-bgp` | `kind-cilium-bgp` | 两个 rack 均宣告本节点 PodCIDR |
| [BGP ECMP](bgp-ecmp/README.md) | `cilium-bgp-ecmp` | `kind-cilium-bgp-ecmp` | 所有节点宣告 PodCIDR；rack1 额外宣告 Service VIP |

两套实验中的相同地址位于各自的容器网络命名空间中。容器及 Kind 集群名已分开；运行多套时仍需为 8 个 Kubernetes 节点及路由容器预留资源。

## 运行环境

在 **Linux 主机或 Linux VM 内**运行脚本，使用同一主机的 Docker Engine 和本地 Unix socket。需要 root 权限，以及 `docker`、`kind`、`clab`（Containerlab）、`kubectl`、`helm`、`python3`；ECMP 还需要 `modprobe`（通常来自 `kmod`）和支持 dummy 设备的内核。使用 rootful Docker，先确认 `sudo docker info` 能连接本地 daemon。

macOS 请先进入 Linux VM / Linux 远程主机，在其中准备仓库与上述工具；仅在 macOS 设置一个远程 Docker context 不满足网络命名空间的运行条件。安装方式参见 [Containerlab 安装](https://containerlab.dev/install/) 和 [macOS 说明](https://containerlab.dev/macos/)。脚本不会安装依赖，也不会自动切换宿主系统。

当前配置使用 Cilium `v1.19.0`、FRR `v8.4.0`。部署入口固定 Kubernetes node 镜像为 `kindest/node:v1.34.0` 的官方摘要，避免随 Kind 默认版本变化；可使用 `KIND_NODE_IMAGE` 覆盖。建议使用支持该镜像的 Kind（如 `v0.30.0`）和相应版本的 kubectl。镜像版本变更后需要重新验证。

## 部署、验证、清理

从仓库根目录执行，或从其他目录使用脚本的绝对路径：

```bash
# 基础 BGP
sudo ./network/cilium/bgp/all-in-one.sh
sudo ./network/cilium/bgp/verify.sh
sudo ./network/cilium/bgp/destroy.sh

# ECMP：按需选择这一套
sudo ./network/cilium/bgp-ecmp/all-in-one.sh
sudo ./network/cilium/bgp-ecmp/verify.sh
sudo ./network/cilium/bgp-ecmp/destroy.sh
```

脚本先检查系统、权限、工具与 Docker，再创建资源。已有同名集群或拓扑时拒绝覆盖；已有实验请执行 `verify.sh`，需要重建时先明确执行对应的 `destroy.sh`。

部署顺序是：Kind bootstrap → Containerlab 链路与 FRR → 拉取并加载 Cilium / nginx 镜像 → Helm 安装 → 等待三种 BGP CRD Established → 应用 BGP 与 nginx 配置 → 验证。Kind 创建阶段不等待节点 Ready，因为 CNI 和物理链路尚未部署；后续验证会等待 Ready。

每一步失败都会返回非零状态。部署失败保留资源便于检查，可用对应的 `destroy.sh` 清理；清理会尝试移除本套拓扑和集群，并报告失败。不会自动删除旧版共享的 `cilium-lb` 或另一套实验。

`LAB_WAIT_SECONDS` 默认 `300`，控制 Helm、CRD、节点、BGP 和路由的各阶段等待。例如：

```bash
sudo env LAB_WAIT_SECONDS=600 ./network/cilium/bgp-ecmp/all-in-one.sh
```

## kubeconfig 与日常检查

每套 kubeconfig 保存为 `<实验目录>/output/kubeconfig`，目录权限 `700`、文件权限 `600`，默认由执行部署的 root 拥有。部署和验证命令始终显式指定它及对应 context，不依赖终端当前 context，也不把新 context 写进用户的默认 kubeconfig。

```bash
# 下列命令从仓库根目录执行
sudo kubectl --kubeconfig "$PWD/network/cilium/bgp-ecmp/output/kubeconfig" \
  --context kind-cilium-bgp-ecmp get pods -A -o wide

sudo docker exec clab-cilium-bgp-ecmp-tor1 vtysh -c 'show bgp ipv4 unicast summary'
sudo docker exec clab-cilium-bgp-ecmp-tor1 vtysh -c 'show ip route 10.100.0.100/32'
sudo docker exec clab-cilium-bgp-ecmp-server0 curl --max-time 10 http://10.100.0.100/
```

kubeconfig、Containerlab 生成目录和旧镜像归档被 Git 忽略。新流程直接使用 `kind load docker-image`，不依赖可能过期的 `cilium-image.tar`。

## 验证内容与预期

`verify.sh` 验证：

1. 四个 Kubernetes 节点 Ready，nginx 与 CoreDNS rollout 成功。
2. router0 的两个 eBGP 邻居，以及 tor0 / tor1 各自的两个 Cilium 节点邻居 Established。
3. router0 存在四个节点 PodCIDR 的已选中、已安装 BGP 路由，避免只宣告 VIP 却遗漏 Pod 网络。
4. nginx Pod 中能解析 `kubernetes.default.svc.cluster.local`，两端 rack 的 netshoot 都能访问 nginx Pod HTTP。
5. ECMP 中 tor1 的 `10.100.0.100/32` 同时有 `10.0.3.2` 和 `10.0.4.2` 两个 FIB 下一跳，并且 rack0 能通过 VIP 访问 nginx。

仅 `show bgp` 中出现两条候选路由不等于 ECMP 已安装；验证检查 FRR 返回的 `selected`、`installed` 和下一跳 `fib` 标记。该检查不代替高可用故障注入和流量分布测试。

## 旧版实验迁移

旧版本两套实验都叫 `cilium-lb`。新脚本不会接管或删除旧资源。如果仍运行旧版，请用对应的旧 `topo.yaml` 清理旧拓扑，并显式执行 `kind delete cluster --name cilium-lb`，之后再用新脚本部署；不要把旧 kubeconfig 复制到新实验的 output 中。

## 本地检查范围

```bash
# 配置测试需要 PyYAML，例如 Linux 上安装 python3-yaml
python3 -m unittest discover -s network/cilium/tests -v
helm lint network/cilium/bgp/cilium
helm lint network/cilium/bgp-ecmp/cilium
```

本次修复检查了 YAML、Helm 渲染、命名与宣告选择，以及通过模拟命令验证失败退出、context 隔离、清理范围和超时逻辑。当前 macOS 上没有完整运行 Containerlab；BGP / ECMP / DNS 的真实验证请在 Linux 上执行部署或 `verify.sh`，尚未声称通过。
