#!/usr/bin/env bash
# Sourced by run-cloud-hypervisor.sh; all SSH operations happen on the Linux Host.
ensure_ssh_keys() {
    command -v ssh >/dev/null && command -v ssh-keygen >/dev/null || fail 'Run dev.sh setup to install openssh-client.'
    [[ "$SSH_IDENTITY" == /* ]] || fail 'SSH_IDENTITY must be an absolute path on the Linux Host.'
    mkdir -p "$WORKDIR/ssh" "$(dirname "$SSH_IDENTITY")"
    chmod 700 "$WORKDIR/ssh"
    local key
    for key in "$SSH_IDENTITY" "$SSH_HOST_KEY"; do
        if [[ ! -e "$key" ]]; then
            [[ ! -e "$key.pub" ]] || fail "Public key exists without private key: $key.pub"
            (umask 077; ssh-keygen -q -t ed25519 -N '' -C ch-debug-config -f "$key")
        fi
        # Derive the public key to reject encrypted/invalid keys and stale .pub files.
        ssh-keygen -y -P '' -f "$key" > "$WORKDIR/ssh/public-key.part"
        if [[ -e "$key.pub" ]]; then
            [[ $(cut -d ' ' -f 1,2 "$key.pub") == $(cut -d ' ' -f 1,2 "$WORKDIR/ssh/public-key.part") ]] || fail "Private/public key mismatch: $key"
        else mv "$WORKDIR/ssh/public-key.part" "$key.pub"; fi
    done
    python3 - "$GUEST_IP" "$SSH_PORT" "$SSH_HOST_KEY.pub" "$SSH_KNOWN_HOSTS" <<'PY'
from pathlib import Path
import sys
address, port, public_key, destination = sys.argv[1:]
key = ' '.join(Path(public_key).read_text().split()[:2])
Path(destination).write_text(f'[{address}]:{port} {key}\n{address} {key}\n')
PY
    rm -f "$WORKDIR/ssh/public-key.part"
    chmod 600 "$SSH_KNOWN_HOSTS"
}

guest_ssh() {
    [[ -s "$SSH_IDENTITY" && -s "$SSH_KNOWN_HOSTS" ]] || { echo 'Prepare/run the SSH Guest first.' >&2; return 1; }
    local args=(-F /dev/null -i "$SSH_IDENTITY" -p "$SSH_PORT"
        -o BatchMode=yes -o IdentitiesOnly=yes -o IdentityAgent=none
        -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$SSH_KNOWN_HOSTS"
        -o GlobalKnownHostsFile=/dev/null -o ConnectTimeout=3 -o LogLevel=ERROR
        -o ServerAliveInterval=3 -o ServerAliveCountMax=2)
    if (( $# )); then
        local command
        command=$(python3 -c 'import shlex,sys; print(shlex.join(sys.argv[1:]))' "$@")
        ssh "${args[@]}" "root@$GUEST_IP" "$command"
    else
        ssh "${args[@]}" -t "root@$GUEST_IP"
    fi
}
