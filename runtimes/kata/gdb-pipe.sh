#!/usr/bin/env bash
set -Eeuo pipefail
DEBUG_KIND=kata
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/common/config.sh"
source "$DEBUG_COMMON/mi-pipe.sh"
prepare_mi_pipe "$@"
exec container machine run -n "$MACHINE" --root "${MI_PIPE_FLAGS[@]}" -- "$@"
