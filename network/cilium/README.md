# Cilium BGP 实验的部署与验证

两套实验使用相同的部署入口，各自拥有集群、拓扑和 kubeconfig：

| 实验 | Kind / Containerlab 名称 | Kubernetes context | 宣告内容 |
| --- | --- | --- | --- |
| [基础 BGP](bgp/README.md) | `cilium-bgp` | `kind-cilium-bgp` | 两个 rack 均宣告本节点 PodCIDR |
| [BGP ECMP](bgp-ecmp/README.md) | `cilium-bgp-ecmp` | `kind-cilium-bgp-ecmp` | 所有节点宣告 PodCIDR；rack1 额外宣告 Service VIP |

两套实验中的相同地址位于各自的容器网络命名空间中。容器及 Kind 集群名已分开；运行多套时仍需为 8 个 Kubernetes 节点及路由容器预留资源。

## 运行环境

在 **Linux 主机或 Linux VM 内**运行脚本，使用同一主机的 Docker Engine 和本地 Unix socket。需要 root 权限，以及 `docker`、`kind`、`clab`（Containerlab）、`kubectl`、`helm`、`python3`。使用 rootful Docker，先确认 `sudo docker info` 能连接本地 daemon。

macOS 请先进入 Linux VM / Linux 远程主机，在其中准备仓库与上述工具；仅在 macOS 设置一个远程 Docker context 不满足网络命名空间的运行条件。安装方式参见 [Containerlab 安装](https://containerlab.dev/install/) 和 [macOS 说明](https://containerlab.dev/macos/)。脚本不会安装依赖，也不会自动切换宿主系统。

Host 内核需要 BPF JIT、cgroup BPF、bridge、veth、overlay 和 ECMP 等能力。精简的 Apple Container Host 内核可能默认关闭 `CONFIG_BPF_JIT` / `CONFIG_IP_ROUTE_MULTIPATH`；可合并 [`common/host-network.config`](common/host-network.config) 后重编译匹配版本的 Host 内核。脚本能读取内核配置时会提前检查关键选项，避免到 Cilium 启动阶段才失败。

Containerlab 也需要内核的模块管理接口（`CONFIG_MODULES=y`，存在 `/proc/modules`）。网络驱动可以内建；使用匹配内核的 `modules.builtin` 元数据供 kmod 检测内建驱动。

当前配置使用 Cilium `v1.19.0`、FRR `v8.4.0`。部署入口固定 Kubernetes node 镜像为 `kindest/node:v1.34.0` 的官方摘要，避免随 Kind 默认版本变化；可使用 `KIND_NODE_IMAGE` 覆盖。建议使用支持该镜像的 Kind（如 `v0.30.0`）和相应版本的 kubectl。镜像版本变更后需要重新验证。

## 部署、验证、清理

macOS 使用已准备好的 Ubuntu machine 时，先在 VM 中安装上述工具和 `rsync`，然后可直接调用：

这里使用 Apple `container` 的 machine 管理 Ubuntu VM，Docker Engine 安装并运行在 Ubuntu 内；不需要 Docker Desktop。Kind / Containerlab 依赖 Docker API，不能直接用 macOS 的 `container` CLI 替换。命令调用关系为 `vm.sh → container machine run → Ubuntu 内的 Docker / Kind / Containerlab`。

Ubuntu 中需启用 Docker 服务：`sudo systemctl enable --now docker`。入口在 VM 启动后最多等待 60 秒，供 systemd 启动 Docker。

```bash
LAB_TRACE=1 ./network/cilium/vm.sh bgp deploy
LAB_TRACE=1 ./network/cilium/vm.sh bgp-ecmp deploy
./network/cilium/vm.sh bgp verify
./network/cilium/vm.sh bgp-ecmp verify
# 按需清理其中一套
./network/cilium/vm.sh bgp destroy
```

`MACHINE` 默认 `fc-ubuntu`。该入口把配置同步到 VM 的 `NETWORK_VM_ROOT`（默认 `/var/tmp/kernel-network-labs`）下，再以 root 执行；kubeconfig、锁文件及 Containerlab 状态都保存在 VM 原生磁盘。避免直接在 macOS 的 virtiofs 共享目录创建 kubeconfig 锁文件。同步保留各实验的 `output/` 和 `clab-*/`，不覆盖正在运行的状态；修改拓扑后需明确清理并重建。

VM 入口默认传入 `LAB_WAIT_SECONDS=600`，可通过同名环境变量覆盖。日常查询需在 Ubuntu 内使用原生状态目录中的 kubeconfig，例如：

```bash
container machine run -n fc-ubuntu --root -- kubectl \
  --kubeconfig /var/tmp/kernel-network-labs/cilium/bgp/output/kubeconfig \
  --context kind-cilium-bgp get pods -A -o wide
```

VM 使用稀疏磁盘时，Linux 内的可用容量不代表 Mac 物理磁盘仍有空间。macOS 部署入口检查仓库所在卷至少剩余 20 GiB；VM 磁盘放在其他卷时也要检查该卷。重复重建后，可在 Ubuntu 中执行 `sudo fstrim -v /` 回收已释放的块。VM 重启不会自动重建 Containerlab 的 veth 链路，需要清理并重新部署这两套实验。

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

部署前会将运行时 inotify 限制提高到至少 8192 个实例 / 1048576 个 watches，不降低已有更大值，防止多集群的 systemd 因 “Too many open files” 无法启动。这些运行时调整需通过系统 sysctl 配置持久化才能跨重启保留。

每一步失败都会返回非零状态。Kind 失败时也保留节点日志便于检查。部署失败保留资源便于检查，可用对应的 `destroy.sh` 清理；清理会尝试移除本套拓扑和集群，并报告失败。不会自动删除旧版共享的 `cilium-lb` 或另一套实验。

`LAB_WAIT_SECONDS` 默认 `300`，控制 Helm、CRD、节点、BGP 和路由的各阶段等待。例如：

```bash
sudo env LAB_WAIT_SECONDS=600 ./network/cilium/bgp-ecmp/all-in-one.sh
```

设置 `LAB_TRACE=1` 启用 Bash `set -x`，逐条输出命令，并显示脚本、行号和函数名；输出到 stderr，不混入 JSON 检查的数据流。默认 `LAB_TRACE=0`。部署、验证、清理均支持：

```bash
sudo env LAB_TRACE=1 ./network/cilium/bgp/all-in-one.sh
sudo env LAB_TRACE=1 ./network/cilium/bgp-ecmp/verify.sh
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

kubeconfig、Containerlab 生成目录和旧镜像归档被 Git 忽略。Docker 支持 `image save --platform` 时，流程先导出当前平台的临时归档再加载到 Kind，避免 Docker 29 的多架构索引引用未下载的内容；较旧 Docker 回退到 `kind load docker-image`。成功后删除临时归档，不依赖可能过期的 `cilium-image.tar`。

## 验证内容与预期

`verify.sh` 验证：

1. 四个 Kubernetes 节点 Ready，nginx 与 CoreDNS rollout 成功。
2. router0 的两个 eBGP 邻居，以及 tor0 / tor1 各自的两个 Cilium 节点邻居 Established。
3. router0 存在四个节点 PodCIDR 的已选中、已安装 BGP 路由，避免只宣告 VIP 却遗漏 Pod 网络。
4. nginx Pod 中能解析 `kubernetes.default.svc.cluster.local`，两端 rack 的 netshoot 和独立外部 `client0` 均能访问 nginx Pod HTTP。
5. ECMP 中 tor1 的 `10.100.0.100/32` 同时有 `10.0.3.2` 和 `10.0.4.2` 两个 FIB 下一跳，并且 rack0 与独立外部客户端均能通过 VIP 访问 nginx。

仅 `show bgp` 中出现两条候选路由不等于 ECMP 已安装；验证检查 FRR 返回的 `selected`、`installed` 和下一跳 `fib` 标记。该检查不代替高可用故障注入和流量分布测试。

## 旧版实验迁移

旧版本两套实验都叫 `cilium-lb`。新脚本不会接管或删除旧资源。如果仍运行旧版，请用对应的旧 `topo.yaml` 清理旧拓扑，并显式执行 `kind delete cluster --name cilium-lb`，之后再用新脚本部署；不要把旧 kubeconfig 复制到新实验的 output 中。

## 实际验证与本地检查

2026-11-14 已在 Apple `container` 管理的 Ubuntu 24.04 ARM64 VM 中完成两套环境的全新部署，并在同时运行时分别复核通过。VM 为 4 vCPU / 8 GiB 内存，使用合并网络配置后的 Linux `6.18.5-network-lab`；所有容器都由 Ubuntu 内的 Docker Engine 运行。

| 组件 | 实测版本 |
| --- | --- |
| Docker Engine | 29.1.3 |
| Kind / Kubernetes / kubectl | 0.30.0 / 1.34.0 / 1.34.0 |
| Containerlab / Helm | 0.79.0 / 3.19.0 |
| Cilium / FRR | 1.19.0 / 8.4.0 |

两套均通过四节点 Ready、BGP 邻居、四个 PodCIDR 路由、CoreDNS 解析、两端 rack 和独立外部客户端的 Pod HTTP 检查。ECMP 额外通过外部客户端到 VIP 的 HTTP 检查，tor1 同时安装两个下一跳；另以 16 个不同源端口的外部 HTTP 连接抓包，全部成功，最终一轮 `net1` / `net2` 分别观测到 9 / 7 个 SYN。这是一次按流分布实测，尚未进行节点故障切换测试。

部署、复核和抓包结果记录在本机各实验的 `output/` 下：`deploy-recovered.log`、`verify-recovered.log`，以及 ECMP 的 `ecmp-flow-result.log` / `ecmp-flow-proof.log`。这些运行记录与 VM 内状态均不纳入 Git。

```bash
# 配置测试需要 PyYAML，例如 Linux 上安装 python3-yaml
python3 -m unittest discover -s network/cilium/tests -v
helm lint network/cilium/bgp/cilium
helm lint network/cilium/bgp-ecmp/cilium
```

15 项配置及模拟测试、Bash 语法、YAML 解析和两套 Helm lint / 渲染均已通过。模拟测试覆盖失败退出、context 隔离、清理范围、超时、命令跟踪、平台镜像归档、inotify 下限及 macOS 磁盘空间检查；真实网络验证结果见上文。

部署期间曾遇到 Mac 物理磁盘耗尽、Ubuntu ext4 转为只读的问题。释放 Mac 空间后，对独立 APFS 克隆执行 `e2fsck`；在 VM 保持停止、原盘未变更时替换为检查通过的副本，保留最新原盘备份。启动后已确认根文件系统状态为 `clean`。检查记录保存在 `common/output/fsck-*.log`。

离线磁盘维护前需停止使用同一 VM 的全部 VSCode 调试、构建任务和终端；其他会话可能自动重新启动 VM。本次替换前检查了 VM 状态与原盘签名，遇到重新启动时保留原盘，重新取副本检查后才替换。
