#!/usr/bin/env bash
# macOS entrypoint; keep mutable lab state on the Ubuntu VM's native filesystem.
set -Eeuo pipefail
CILIUM_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ $# == 2 ]] || { echo 'Usage: vm.sh bgp|bgp-ecmp deploy|verify|destroy' >&2; exit 2; }
case "$1" in bgp|bgp-ecmp) ;; *) echo 'Unknown lab' >&2; exit 2 ;; esac
case "$2" in deploy|verify|destroy) ;; *) echo 'Unknown action' >&2; exit 2 ;; esac
export NETWORK_VM_LAB=$1 NETWORK_VM_ACTION=$2
export NETWORK_VM_SOURCE=$CILIUM_DIR
export NETWORK_VM_ROOT=${NETWORK_VM_ROOT:-/var/tmp/kernel-network-labs}
if [[ $(uname -s) == Darwin ]]; then
    if [[ $NETWORK_VM_ACTION == deploy ]]; then
        # A sparse VM disk can have free space inside Linux while macOS is full.
        available_kb=$(df -Pk "$CILIUM_DIR" | awk 'NR == 2 { print $4 }')
        [[ $available_kb =~ ^[0-9]+$ && $available_kb -ge 20971520 ]] || {
            echo 'Deployment needs at least 20 GiB free on the macOS filesystem holding this checkout. Also check the VM disk location.' >&2
            exit 1
        }
    fi
    exec container machine run -n "${MACHINE:-fc-ubuntu}" --root \
        --env "NETWORK_VM_LAB=$NETWORK_VM_LAB" --env "NETWORK_VM_ACTION=$NETWORK_VM_ACTION" \
        --env "NETWORK_VM_SOURCE=$NETWORK_VM_SOURCE" --env "NETWORK_VM_ROOT=$NETWORK_VM_ROOT" \
        --env "LAB_TRACE=${LAB_TRACE:-0}" --env "LAB_WAIT_SECONDS=${LAB_WAIT_SECONDS:-600}" \
        --env "KIND_NODE_IMAGE=${KIND_NODE_IMAGE:-kindest/node:v1.34.0@sha256:7416a61b42b1662ca6ca89f02028ac133a309a2a30ba309614e8ec94d976dc5a}" \
        -- /bin/bash "$CILIUM_DIR/common/in-vm.sh"
fi
exec bash "$CILIUM_DIR/common/in-vm.sh"
