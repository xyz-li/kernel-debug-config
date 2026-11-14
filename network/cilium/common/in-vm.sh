#!/usr/bin/env bash
set -Eeuo pipefail
[[ $(uname -s) == Linux && $EUID == 0 ]] || { echo 'Run inside the Ubuntu VM as root.' >&2; exit 1; }
[[ ${NETWORK_VM_ROOT:-} == /* && "$NETWORK_VM_ROOT" != / ]] || { echo 'NETWORK_VM_ROOT must be a dedicated absolute directory.' >&2; exit 1; }
case ${NETWORK_VM_LAB:-} in bgp|bgp-ecmp) ;; *) exit 2 ;; esac
case ${NETWORK_VM_ACTION:-} in
    deploy) entry=all-in-one.sh ;;
    verify) entry=verify.sh ;;
    destroy) entry=destroy.sh ;;
    *) exit 2 ;;
esac
command -v rsync >/dev/null || { echo 'Install rsync in the Ubuntu VM.' >&2; exit 1; }
command -v docker >/dev/null || { echo 'Install Docker Engine in the Ubuntu VM.' >&2; exit 1; }
# machine run can execute before systemd has finished starting Docker at boot.
deadline=$((SECONDS + 60))
until docker info >/dev/null 2>&1; do
    (( SECONDS < deadline )) || { echo 'Docker Engine did not become ready in 60 seconds; check its systemd service.' >&2; exit 1; }
    sleep 1
done
mkdir -p "$NETWORK_VM_ROOT/cilium"
rsync -a --delete --exclude=output/ --exclude='clab-*/' \
    "$NETWORK_VM_SOURCE/" "$NETWORK_VM_ROOT/cilium/"
exec bash "$NETWORK_VM_ROOT/cilium/$NETWORK_VM_LAB/$entry"
