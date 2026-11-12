#!/usr/bin/env bash
# Runs inside Ubuntu. The launcher keeps TAP/NAT and disk locks alive for GDB.
set -Eeuo pipefail
FC_WRAPPER_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec /bin/bash "$FC_WRAPPER_DIR/run-firecracker.sh" debug-mi "$@"
