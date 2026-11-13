#!/usr/bin/env bash
# GDB exec-wrapper appends the prepared VM arguments after MI sets the program.
# This keeps .env paths/settings effective without hard-coding them in launch.json.
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"
mapfile -d '' -t args < <(python3 - "$WORKDIR/args.json" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    args = json.load(f)
sys.stdout.buffer.write(b''.join(a.encode() + b'\0' for a in args))
PY
)
(( ${#args[@]} > 0 )) || { echo 'Missing prepared VM arguments.' >&2; exit 1; }
printf '%s\n' "$$" > "$WORKDIR/cloud-hypervisor.pid"
exec "$@" "${args[@]}"
