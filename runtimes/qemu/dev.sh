#!/usr/bin/env bash
set -Eeuo pipefail
directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
set -a
[[ ! -f "$directory/../common/.env" ]] || source "$directory/../common/.env"
[[ ! -f "$directory/.env" ]] || source "$directory/.env"
set +a
exec python3 "$directory/environment.py" "$@"
