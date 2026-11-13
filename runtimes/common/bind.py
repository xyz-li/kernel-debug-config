#!/usr/bin/env python3
"""Bind a checkout without editing it; keep absolute paths in ignored files."""
import json
import os
from pathlib import Path
import shlex
import sys

root = Path(__file__).resolve().parent.parent
kind, source_arg = sys.argv[1:]
kind = {"fc": "firecracker"}.get(kind, kind)
if kind not in {"firecracker", "gvisor", "kata", "cloud-hypervisor"}:
    raise SystemExit("Expected firecracker, gvisor, kata or cloud-hypervisor")
source = Path(source_arg).expanduser().resolve(strict=True)
marker = {"firecracker": "src/firecracker/Cargo.toml", "gvisor": ".bazelversion", "kata": "src/agent/Cargo.toml",
          "cloud-hypervisor": "vmm/src/lib.rs"}[kind]
if not (source / marker).is_file():
    raise SystemExit(f"Not the expected {kind} checkout: missing {marker}")
directory = root / kind
key = {"firecracker": "FC_SOURCE", "cloud-hypervisor": "CH_SOURCE"}.get(kind, "SOURCE_DIR")
env = directory / ".env"
lines = env.read_text().splitlines() if env.exists() else []
lines = [line for line in lines if not line.startswith(key + "=")]
lines.append(f"{key}={shlex.quote(str(source))}")
env.write_text("\n".join(lines) + "\n")
os.chmod(env, 0o600)
output = directory / "output"
output.mkdir(exist_ok=True)
workspace = output / "debug.local.code-workspace"
data = {"folders": [{"name": f"{kind}-debug", "path": ".."}, {"name": f"{kind}-source", "path": str(source)}],
        "settings": {"debug.allowBreakpointsEverywhere": True}}
workspace.write_text(json.dumps(data, indent=2) + "\n")
print(f"Bound {kind} source. Open in VSCode: {workspace}")
