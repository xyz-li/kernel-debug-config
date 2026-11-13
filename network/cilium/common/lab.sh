#!/usr/bin/env bash
# Run only the named lab, with its own kubeconfig and explicit Kubernetes context.
set -Eeuo pipefail

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[[ $# == 2 ]] || fail 'Usage: lab.sh LAB_DIRECTORY deploy|destroy|verify'
LAB_DIR=$(cd -- "$1" && pwd)
COMMON_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
case "${LAB_DIR##*/}" in
    bgp) LAB_NAME=cilium-bgp ;;
    bgp-ecmp) LAB_NAME=cilium-bgp-ecmp ;;
    *) fail "Unknown lab: $LAB_DIR" ;;
esac
ACTION=$2
case "$ACTION" in deploy|destroy|verify) ;; *) fail "Unknown action: $ACTION" ;; esac
OUTPUT="$LAB_DIR/output"
CONFIG="$OUTPUT/kubeconfig"
CONTEXT="kind-$LAB_NAME"
LAB_WAIT_SECONDS=${LAB_WAIT_SECONDS:-300}
[[ "$LAB_WAIT_SECONDS" =~ ^[1-9][0-9]*$ ]] || fail 'LAB_WAIT_SECONDS must be a positive integer'
# Pin the node image instead of inheriting a different Kubernetes version per kind release.
KIND_NODE_IMAGE=${KIND_NODE_IMAGE:-kindest/node:v1.34.0@sha256:7416a61b42b1662ca6ca89f02028ac133a309a2a30ba309614e8ec94d976dc5a}
export KIND_EXPERIMENTAL_PROVIDER=docker

preflight() {
    [[ $(uname -s) == Linux ]] || fail 'Run this lab inside a Linux host/VM with local Docker Engine; macOS needs a Linux VM.'
    [[ $(id -u) == 0 ]] || fail 'Containerlab needs root: run this script with sudo on the Linux lab host.'
    local required=(docker kind clab)
    if [[ "$ACTION" != destroy ]]; then required+=(kubectl python3); fi
    if [[ "$ACTION" == deploy ]]; then required+=(helm); fi
    if [[ "$ACTION" == deploy && "$LAB_NAME" == cilium-bgp-ecmp ]]; then required+=(modprobe); fi
    local tool endpoint security
    for tool in "${required[@]}"; do command -v "$tool" >/dev/null || fail "Missing command: $tool"; done
    [[ $(docker info --format '{{.OSType}}') == linux ]] || fail 'A working Linux Docker Engine is required'
    security=$(docker info --format '{{json .SecurityOptions}}')
    [[ "$security" != *name=rootless* ]] || fail 'Containerlab requires a rootful Docker Engine for this topology'
    if [[ -n ${DOCKER_HOST:-} && -z ${DOCKER_CONTEXT:-} ]]; then
        endpoint=$DOCKER_HOST
    else
        endpoint=$(docker context inspect --format '{{.Endpoints.docker.Host}}')
    fi
    [[ "$endpoint" == unix://* ]] || fail 'Run inside the Linux Docker host using its local Unix socket; remote Docker contexts cannot supply local network namespaces.'
}

kube() { kubectl --kubeconfig "$CONFIG" --context "$CONTEXT" "$@"; }

retry() {
    local description=$1
    shift
    local deadline=$((SECONDS + LAB_WAIT_SECONDS))
    until "$@"; do
        (( SECONDS < deadline )) || fail "Timed out waiting for $description"
        sleep 2
    done
}

wait_crds() {
    local crd deadline=$((SECONDS + LAB_WAIT_SECONDS)) remaining
    for crd in ciliumbgpclusterconfigs.cilium.io ciliumbgppeerconfigs.cilium.io ciliumbgpadvertisements.cilium.io; do
        until kube get crd "$crd" --request-timeout=5s >/dev/null 2>&1; do
            (( SECONDS < deadline )) || fail "Timed out waiting for CRD $crd"
            sleep 2
        done
        remaining=$((deadline - SECONDS))
        (( remaining > 0 )) || fail 'Timed out waiting for BGP CRDs'
        kube wait --for=condition=Established "crd/$crd" --timeout="${remaining}s"
    done
}

peers_ready() {
    local router=$1
    shift
    docker exec "clab-$LAB_NAME-$router" vtysh -c 'show bgp ipv4 unicast summary json' |
        python3 "$COMMON_DIR/check.py" peers "$@"
}

route_ready() {
    local router=$1 prefix=$2
    shift 2
    docker exec "clab-$LAB_NAME-$router" vtysh -c "show ip route $prefix json" |
        python3 "$COMMON_DIR/check.py" route "$prefix" "$@"
}

verify() {
    [[ -s "$CONFIG" ]] || fail "Missing $CONFIG; deploy this lab first"
    kube wait --for=condition=Ready nodes --all --timeout="${LAB_WAIT_SECONDS}s"
    retry 'router0 eBGP peers' peers_ready router0 --minimum 2
    retry 'tor0 node peers' peers_ready tor0 10.0.1.2 10.0.2.2
    retry 'tor1 node peers' peers_ready tor1 10.0.3.2 10.0.4.2
    local cidrs prefix pod_ips ip server
    cidrs=$(kube get nodes -o 'jsonpath={range .items[*]}{.spec.podCIDR}{"\n"}{end}')
    [[ $(printf '%s\n' "$cidrs" | grep -c /) == 4 ]] || fail 'Expected a PodCIDR for all four nodes'
    while IFS= read -r prefix; do
        retry "router0 route to $prefix" route_ready router0 "$prefix"
    done <<< "$cidrs"
    kube rollout status deployment/nginx --timeout="${LAB_WAIT_SECONDS}s"
    kube -n kube-system rollout status deployment/coredns --timeout="${LAB_WAIT_SECONDS}s"
    kube exec deployment/nginx -- /bin/busybox nslookup kubernetes.default.svc.cluster.local
    pod_ips=$(kube get pods -l app=nginx -o 'jsonpath={range .items[*]}{.status.podIP}{"\n"}{end}')
    [[ -n "$pod_ips" ]] || fail 'No nginx Pod IPs'
    # netshoot supplies curl; test both racks without assuming FRR contains curl.
    for server in server0 server3; do
        while IFS= read -r ip; do
            [[ -n "$ip" ]] || continue
            docker exec "clab-$LAB_NAME-$server" curl --fail --silent --show-error --max-time 10 "http://$ip/" >/dev/null
        done <<< "$pod_ips"
    done
    if [[ "$LAB_NAME" == cilium-bgp-ecmp ]]; then
        retry 'two installed VIP next hops on tor1' route_ready tor1 10.100.0.100/32 10.0.3.2 10.0.4.2
        docker exec "clab-$LAB_NAME-server0" curl --fail --silent --show-error --max-time 10 http://10.100.0.100/ >/dev/null
        docker exec "clab-$LAB_NAME-tor1" vtysh -c 'show ip route 10.100.0.100/32'
    fi
    kube get nodes -o wide
    printf '%s: BGP, Pod routes, DNS and HTTP checks passed\n' "$LAB_NAME"
}

deploy() {
    local clusters containers image
    clusters=$(kind get clusters)
    if grep -Fxq "$LAB_NAME" <<< "$clusters"; then
        fail "$LAB_NAME already exists; use verify.sh or explicitly destroy it before redeploying"
    fi
    containers=$(docker ps -a --format '{{.Names}}')
    if grep -Eq "^clab-$LAB_NAME-(router0|tor0|tor1|server[0-3])$" <<< "$containers"; then
        fail "Existing $LAB_NAME topology containers found; inspect them or use destroy.sh"
    fi
    mkdir -p "$OUTPUT"
    chmod 700 "$OUTPUT"
    trap 'printf "Deployment failed. Resources are retained for inspection; cleanup: sudo %q/destroy.sh\n" "$LAB_DIR" >&2' ERR
    if [[ "$LAB_NAME" == cilium-bgp-ecmp ]]; then modprobe dummy; fi
    # No --wait: CNI and physical links are installed after kind bootstraps.
    kind create cluster --name "$LAB_NAME" --config "$LAB_DIR/kind.yaml" --image "$KIND_NODE_IMAGE" --kubeconfig "$CONFIG"
    chmod 600 "$CONFIG"
    clab deploy --topo "$LAB_DIR/topo.yaml"
    local images=(quay.io/cilium/cilium:v1.19.0 quay.io/cilium/operator-generic:v1.19.0
        quay.io/cilium/cilium-envoy:v1.35.9-1768828720-c6e4827ebca9c47af2a3a6540c563c30947bae29 nginx:alpine)
    for image in "${images[@]}"; do docker pull "$image"; done
    kind load docker-image --name "$LAB_NAME" "${images[@]}"
    helm upgrade --install cilium "$LAB_DIR/cilium" --namespace kube-system \
        --kubeconfig "$CONFIG" --kube-context "$CONTEXT" --wait --timeout "${LAB_WAIT_SECONDS}s"
    wait_crds
    kube apply -f "$LAB_DIR/bgp-config.yaml"
    kube apply -f "$LAB_DIR/svc.yaml"
    verify
    printf 'Kubeconfig: %s\nContext: %s\n' "$CONFIG" "$CONTEXT"
}

destroy() {
    # Never target the legacy shared cilium-lb cluster or another lab's context.
    local status=0 containers
    containers=$(docker ps -a --format '{{.Names}}')
    if [[ -d "$LAB_DIR/clab-$LAB_NAME" ]] || grep -Eq "^clab-$LAB_NAME-(router0|tor0|tor1|server[0-3])$" <<< "$containers"; then
        clab destroy --topo "$LAB_DIR/topo.yaml" --cleanup || status=$?
    fi
    KUBECONFIG="$CONFIG" kind delete cluster --name "$LAB_NAME" || status=$?
    if (( status == 0 )); then rm -f -- "$CONFIG"; fi
    return "$status"
}

preflight
cd -- "$LAB_DIR"
case "$ACTION" in deploy) deploy ;; destroy) destroy ;; verify) verify ;; esac
