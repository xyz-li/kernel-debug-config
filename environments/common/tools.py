#!/usr/bin/env python3
"""Install an official Go archive after checking its published SHA256."""
import hashlib
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

_, version, directory = sys.argv[1:]
root = Path(directory)
destination = root / f"go-{version}"
if (destination / "bin/go").is_file():
    subprocess.run([str(destination / "bin/go"), "version"], check=True)
    raise SystemExit(0)
arch = {"aarch64": "arm64", "x86_64": "amd64"}[platform.machine()]
filename = f"go{version}.linux-{arch}.tar.gz"
with urllib.request.urlopen("https://go.dev/dl/?mode=json&include=all", timeout=60) as response:
    versions = json.load(response)
entry = next((file for release in versions for file in release["files"] if file["filename"] == filename), None)
if entry is None:
    raise SystemExit(f"Go {version} is not in the official download list")
root.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=root) as temporary:
    archive = Path(temporary) / filename
    digest = hashlib.sha256()
    with urllib.request.urlopen("https://go.dev/dl/" + filename, timeout=120) as response, archive.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != entry["sha256"]:
        raise SystemExit("Official Go SHA256 verification failed")
    with tarfile.open(archive) as package:
        package.extractall(temporary, filter="data")
    shutil.move(str(Path(temporary) / "go"), destination)
print(f"Installed verified Go {version}")
