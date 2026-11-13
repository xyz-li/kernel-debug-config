#!/usr/bin/env bash
set -Eeuo pipefail
DEBUG_KIND=kata
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/common/config.sh"
exec container machine run -n "$MACHINE" --root --interactive -- "$@"
