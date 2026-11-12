#!/usr/bin/env bash
# Create a new image atomically; never edits the source or a running guest disk.
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"
BASE=${1:?usage: inject-fc-rootfs.sh BASE.ext4 OUTPUT.ext4}
OUTPUT=${2:?usage: inject-fc-rootfs.sh BASE.ext4 OUTPUT.ext4}
[[ "$BASE" != "$OUTPUT" ]] || { echo 'Input and output must differ.' >&2; exit 1; }
[[ -s "$BASE" && -s "$AGENT_BIN" ]] || { echo 'Missing base rootfs or guest-agent.' >&2; exit 1; }
file "$AGENT_BIN" | grep -q 'ELF 64-bit.*ARM aarch64.*statically linked' || {
    echo 'guest-agent must be a static Linux ARM64 ELF.' >&2; exit 1;
}
mkdir -p "$(dirname "$OUTPUT")"
TMP=$(mktemp -d "$(dirname "$OUTPUT")/.inject.XXXXXX")
trap 'rm -rf -- "$TMP"' EXIT
IMAGE=$TMP/rootfs.ext4
cp --reflink=auto --sparse=always "$BASE" "$IMAGE"

stat_guest() { debugfs -R "stat $1" "$IMAGE" 2>/dev/null; }
exists() { stat_guest "$1" | grep -q '^Inode:'; }
dbg() {
    local result
    result=$(debugfs -w -R "$1" "$IMAGE" 2>&1)
    # debugfs often exits 0 even on errors; check diagnostics and verify writes.
    if [[ "$result" == *'not found'* || "$result" == *'File exists'* ||
          "$result" == *'Could not allocate'* || "$result" == *'Usage:'* ||
          "$result" == *'while '* ]]; then
        printf '%s\n' "$result" >&2; return 1
    fi
}
ensure_dir() { exists "$1" || dbg "mkdir $1"; exists "$1"; }
write_guest() {
    local src=$1 dest=$2 mode=${3:-0100644}
    if exists "$dest"; then dbg "rm $dest"; fi
    dbg "write \"$src\" $dest"
    exists "$dest"
    dbg "set_inode_field $dest mode $mode"
    dbg "set_inode_field $dest uid 0"
    dbg "set_inode_field $dest gid 0"
    debugfs -R "dump $dest $TMP/verify" "$IMAGE" >/dev/null 2>&1
    cmp "$src" "$TMP/verify"
    rm "$TMP/verify"
}
enable_unit() {
    local name=$1 target=$2 link
    link=/etc/systemd/system/multi-user.target.wants/$name
    if exists "$link"; then dbg "rm $link"; fi
    dbg "symlink $link $target"
    stat_guest "$link" | grep -q 'Type: symlink'
}
exists /lib/systemd/systemd || exists /usr/lib/systemd/systemd || {
    echo 'Only Ubuntu/systemd guest images are supported (Host may be Alpine or Ubuntu).' >&2; exit 1;
}
for dir in /usr/local /usr/local/bin /etc/systemd /etc/systemd/system \
    /etc/systemd/system/multi-user.target.wants /etc/systemd/network; do ensure_dir "$dir"; done
write_guest "$AGENT_BIN" /usr/local/bin/guest-agent 0100755
cat > "$TMP/guest-agent.service" <<EOF
[Unit]
Description=LiquidMetal Guest Agent over vsock
After=local-fs.target

[Service]
Type=simple
ExecStart=/usr/local/bin/guest-agent --net vsock --control-port $AGENT_PORT
Restart=on-failure
RestartSec=1

[Install]
WantedBy=multi-user.target
EOF
write_guest "$TMP/guest-agent.service" /etc/systemd/system/guest-agent.service
enable_unit guest-agent.service /etc/systemd/system/guest-agent.service

# Deliberately replace dangling symlinks too. A plain resolv.conf works without
# systemd-resolved and is not removed by restarting systemd-networkd.
printf 'nameserver %s\nnameserver %s\noptions timeout:2 attempts:3 single-request-reopen\n' \
    "$DNS_SERVER" "$DNS_SECONDARY" > "$TMP/resolv.conf"
write_guest "$TMP/resolv.conf" /etc/resolv.conf
if [[ "$ENABLE_NETWORK" == 1 ]]; then
    cat > "$TMP/00-fc-debug.network" <<EOF
[Match]
MACAddress=$GUEST_MAC

[Network]
Address=$GUEST_IP/$PREFIX
Gateway=$HOST_IP
DNS=$DNS_SERVER
DNS=$DNS_SECONDARY
LinkLocalAddressing=no
IPv6AcceptRA=no
EOF
    # The first matching .network wins, ahead of CI image defaults.
    write_guest "$TMP/00-fc-debug.network" /etc/systemd/network/00-fc-debug.network
    unit=/usr/lib/systemd/system/systemd-networkd.service
    if exists /lib/systemd/system/systemd-networkd.service; then
        unit=/lib/systemd/system/systemd-networkd.service
    fi
    exists "$unit" || { echo 'Guest lacks systemd-networkd.' >&2; exit 1; }
    enable_unit systemd-networkd.service "$unit"
fi
e2fsck -fn "$IMAGE" > "$TMP/fsck.log" 2>&1 || { cat "$TMP/fsck.log" >&2; exit 1; }
mv "$IMAGE" "$OUTPUT"
printf 'Injected Agent, network and DNS: %s\n' "$OUTPUT"
