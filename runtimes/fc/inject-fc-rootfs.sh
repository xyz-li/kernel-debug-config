#!/usr/bin/env bash
# Create a new image atomically; never edits the source or a running guest disk.
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"
BASE=${1:?usage: inject-fc-rootfs.sh BASE.ext4 OUTPUT.ext4}
OUTPUT=${2:?usage: inject-fc-rootfs.sh BASE.ext4 OUTPUT.ext4}
[[ "$BASE" != "$OUTPUT" ]] || { echo 'Input and output must differ.' >&2; exit 1; }
[[ -s "$BASE" ]] || { echo 'Missing base rootfs.' >&2; exit 1; }
if [[ "$GUEST_MODE" == liquidmetal ]]; then
    [[ -s "$AGENT_BIN" ]] || { echo 'Missing guest-agent.' >&2; exit 1; }
    file "$AGENT_BIN" | grep -q 'ELF 64-bit.*ARM aarch64.*statically linked' || {
        echo 'guest-agent must be a static Linux ARM64 ELF.' >&2; exit 1;
    }
fi
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
remove_guest() { if exists "$1"; then dbg "rm $1"; fi; }
mask_unit() {
    remove_guest "/etc/systemd/system/$1"
    dbg "symlink /etc/systemd/system/$1 /dev/null"
}
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
if [[ "$GUEST_MODE" == liquidmetal ]]; then
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
else
    remove_guest /etc/systemd/system/multi-user.target.wants/guest-agent.service
    remove_guest /usr/local/bin/guest-agent
    mask_unit guest-agent.service
fi

if [[ "$GUEST_MODE" == serial || "$GUEST_MODE" == ssh ]]; then
    # The selected control path owns its services, even with a preconfigured base.
    for unit in ssh.service sshd.service ssh.socket sshd.socket; do mask_unit "$unit"; done
fi
if [[ "$GUEST_MODE" == serial ]]; then
    exists /sbin/agetty || { echo 'Serial mode requires /sbin/agetty in the Guest.' >&2; exit 1; }
    unit=/usr/lib/systemd/system/serial-getty@.service
    if exists /lib/systemd/system/serial-getty@.service; then unit=/lib/systemd/system/serial-getty@.service; fi
    exists "$unit" || { echo 'Guest lacks serial-getty@.service.' >&2; exit 1; }
    remove_guest /etc/systemd/system/serial-getty@ttyS0.service
    ensure_dir /etc/systemd/system/serial-getty@ttyS0.service.d
    cat > "$TMP/autologin.conf" <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I 115200 vt220
EOF
    write_guest "$TMP/autologin.conf" /etc/systemd/system/serial-getty@ttyS0.service.d/autologin.conf
    enable_unit serial-getty@ttyS0.service "$unit"
elif [[ "$GUEST_MODE" == ssh ]]; then
    exists /usr/sbin/sshd || { echo 'SSH mode requires a Guest rootfs with openssh-server installed.' >&2; exit 1; }
    [[ -s "$SSH_IDENTITY.pub" && -s "$SSH_HOST_KEY" ]] || { echo 'Prepare dedicated SSH keys first.' >&2; exit 1; }
    for dir in /root /root/.ssh /etc/ssh; do ensure_dir "$dir"; done
    dbg 'set_inode_field /root/.ssh mode 040700'
    write_guest "$SSH_IDENTITY.pub" /root/.ssh/authorized_keys.fc-debug 0100600
    write_guest "$SSH_HOST_KEY" /etc/ssh/ssh_host_ed25519_key.fc-debug 0100600
    cat > "$TMP/sshd_config" <<EOF
Port $SSH_PORT
ListenAddress 0.0.0.0
HostKey /etc/ssh/ssh_host_ed25519_key.fc-debug
AuthorizedKeysFile /root/.ssh/authorized_keys.fc-debug
PermitRootLogin prohibit-password
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
UsePAM yes
AllowUsers root
PidFile /run/sshd-fc-debug.pid
PrintMotd no
Subsystem sftp internal-sftp
EOF
    write_guest "$TMP/sshd_config" /etc/ssh/sshd_config.fc-debug
    cat > "$TMP/fc-debug-ssh.service" <<'EOF'
[Unit]
Description=Dedicated Firecracker debug SSH server
After=network.target

[Service]
ExecStartPre=/usr/bin/mkdir -p /run/sshd
ExecStart=/usr/sbin/sshd -D -e -f /etc/ssh/sshd_config.fc-debug
Restart=on-failure
RestartSec=1

[Install]
WantedBy=multi-user.target
EOF
    write_guest "$TMP/fc-debug-ssh.service" /etc/systemd/system/fc-debug-ssh.service
    enable_unit fc-debug-ssh.service /etc/systemd/system/fc-debug-ssh.service
fi

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
printf 'Prepared %s Guest, network and DNS: %s\n' "$GUEST_MODE" "$OUTPUT"
