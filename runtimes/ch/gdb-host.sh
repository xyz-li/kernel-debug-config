#!/usr/bin/env bash
set -Eeuo pipefail
CH_WRAPPER_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec /bin/bash "$CH_WRAPPER_DIR/run-cloud-hypervisor.sh" debug-mi "$@"
