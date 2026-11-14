#!/usr/bin/env bash
# Keep stdout reserved for GDB/MI. No TTY, SSH server or TCP listener required.
set -Eeuo pipefail
if [[ ${1:-} == --guest-mode ]]; then
    export CH_GUEST_MODE=${2:?Missing Guest mode}; shift 2
fi
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"
source "$CH_DIR/../common/mi-pipe.sh"
prepare_mi_pipe "$@"
opts=()
for key in "${CH_ENV_KEYS[@]}" CH_GUEST_MODE; do opts+=(--env "$key=${!key}"); done
exec /usr/local/bin/container machine run -n "$MACHINE" --root "${MI_PIPE_FLAGS[@]}" "${opts[@]}" -- "$@"
