#!/usr/bin/env bash
set -Eeuo pipefail
DEBUG_KIND=gvisor
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)/common/config.sh"

# The configuration folder has no Bazel packages. Only load the bound checkout.
case "$(pwd -P)/" in
    "$SOURCE_DIR/"*)
        export MACHINE LSP_CWD="$PWD"
        exec python3 "$DEBUG_DIR/tools/gopackagesdriver.py" "$@"
        ;;
    *) printf '{"NotHandled":true}\n' ;;
esac
