#!/usr/bin/env bash
# Runs on Linux. Isolate Agent mount/hostname/PID changes from the Host.
set -Eeuo pipefail
DEBUG_KIND=kata
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/common/config.sh"
linux_init
export KATA_CONF_FILE=$KATA_CONFIG
exec unshare --mount --uts --ipc --pid --fork --mount-proc --propagation private /usr/bin/gdb "$@"
