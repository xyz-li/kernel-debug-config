#!/usr/bin/env bash
# VSCode MI pipe: no TTY, no banners or stdout logging before GDB starts.
set -Eeuo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"
exec /usr/local/bin/container machine run -n "$MACHINE" --root --interactive -- "$@"
