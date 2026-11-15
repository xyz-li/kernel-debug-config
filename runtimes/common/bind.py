#!/usr/bin/env python3
"""Bind a checkout without editing it; keep absolute paths in ignored files."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
kind, source_arg = sys.argv[1:]
kind = {"firecracker": "fc", "cloud-hypervisor": "ch", "gvisor": "gv"}.get(kind, kind)
if kind not in {"fc", "gv", "kata", "ch", "qemu"}:
    raise SystemExit("Expected fc, ch, gv, kata or qemu")
source = Path(source_arg).expanduser().resolve(strict=True)
marker = {"fc": "src/firecracker/Cargo.toml", "gv": ".bazelversion", "kata": "src/agent/Cargo.toml",
          "ch": "vmm/src/lib.rs", "qemu": "system/vl.c"}[kind]
if not (source / marker).is_file():
    raise SystemExit(f"Not the expected {kind} checkout: missing {marker}")
directory = root / kind
source_name = {"fc": "firecracker", "ch": "cloud-hypervisor", "gv": "gvisor"}.get(kind, kind)
template = directory / f"{source_name}.code-workspace"
settings = json.loads(template.read_text()).get("settings", {})
if kind == "gv":
    # gopls does not expand VSCode workspace variables in build.env. An absolute
    # driver also takes precedence over the upstream folder's native Bazel driver.
    driver = str(directory / "tools/gopackagesdriver.sh")
    settings.setdefault("go.toolsEnvVars", {})["GOPACKAGESDRIVER"] = driver
    settings.setdefault("gopls", {}).setdefault("build.env", {})["GOPACKAGESDRIVER"] = driver
    go_mod = source / "go.mod"
    if go_mod.is_file():
        version = re.search(r"^go\s+(\d+\.\d+(?:\.\d+)?)", go_mod.read_text(), re.MULTILINE)
        if version:
            bootstrap_go = shutil.which("go")
            if not bootstrap_go:
                raise SystemExit("gVisor editor setup requires a local Go installation.")
            toolchain = "go" + version[1]
            go_env = dict(os.environ, GOTOOLCHAIN=toolchain, GO111MODULE="on")
            go_env.pop("GOROOT", None)
            goroot = subprocess.check_output([bootstrap_go, "env", "GOROOT"], cwd=source,
                                             env=go_env, text=True, timeout=180).strip()
            go_bin = Path(goroot) / "bin/go"
            if not os.access(go_bin, os.X_OK):
                raise SystemExit(f"Missing Go toolchain executable: {go_bin}")
            # gopls queries ReleaseTags with GO111MODULE=off, which bypasses
            # toolchain switching. Put the selected executable itself on PATH.
            go_directory = str(go_bin.parent)
            search_path = os.pathsep.join([go_directory] + [entry for entry in
                os.environ.get("PATH", os.defpath).split(os.pathsep) if entry != go_directory])
            settings.setdefault("go.alternateTools", {})["go"] = str(go_bin)
            for environment in (settings["go.toolsEnvVars"], settings["gopls"]["build.env"]):
                environment["GOTOOLCHAIN"] = toolchain
                environment["PATH"] = search_path
key = {"fc": "FC_SOURCE", "ch": "CH_SOURCE", "qemu": "QEMU_SOURCE"}.get(kind, "SOURCE_DIR")
env = directory / ".env"
lines = env.read_text().splitlines() if env.exists() else []
lines = [line for line in lines if not line.startswith(key + "=")]
lines.append(f"{key}={shlex.quote(str(source))}")
env.write_text("\n".join(lines) + "\n")
os.chmod(env, 0o600)
output = directory / "output"
output.mkdir(exist_ok=True)
workspace = output / "debug.local.code-workspace"
data = {"folders": [{"name": f"{kind}-debug", "path": ".."}, {"name": f"{source_name}-source", "path": str(source)}],
        "settings": settings}
workspace.write_text(json.dumps(data, indent=2) + "\n")
print(f"Bound {kind} source. Open in VSCode: {workspace}")
