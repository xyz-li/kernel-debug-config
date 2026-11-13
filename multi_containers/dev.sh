#!/usr/bin/env bash
set -euo pipefail
exec python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../kernel_common" && pwd)/dev.py" multi_containers "$@"
