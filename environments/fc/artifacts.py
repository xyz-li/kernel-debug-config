#!/usr/bin/env python3
"""Fetch a complete ARM64 CI artifact pair using paginated S3 listings."""
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

S3 = "https://s3.amazonaws.com/spec.ccfc.min"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}


def listing(prefix, delimiter=None):
    params = {"list-type": "2", "prefix": prefix}
    if delimiter:
        params["delimiter"] = delimiter
    keys, prefixes = [], []
    while True:
        url = S3 + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=60) as response:
            root = ET.fromstring(response.read())
        keys += [e.text for e in root.findall("s:Contents/s:Key", NS)]
        prefixes += [e.text for e in root.findall("s:CommonPrefixes/s:Prefix", NS)]
        if root.findtext("s:IsTruncated", "false", NS) != "true":
            return keys, prefixes
        token = root.findtext("s:NextContinuationToken", None, NS)
        if not token:
            raise RuntimeError("S3 returned a truncated listing without a continuation token")
        params["continuation-token"] = token


def download(key, path):
    temporary = Path(str(path) + ".part")
    print(f"Downloading {key} -> {path}", flush=True)
    try:
        with urllib.request.urlopen(S3 + "/" + urllib.parse.quote(key), timeout=60) as response:
            expected = response.headers.get("Content-Length")
            with temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        if not temporary.stat().st_size or (
            expected is not None and temporary.stat().st_size != int(expected)
        ):
            raise RuntimeError("Incomplete download")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    directory = Path(sys.argv[1])
    kernel = Path(os.environ["KERNEL"])
    squashfs = directory / "ubuntu.squashfs"
    if kernel.is_file() and kernel.stat().st_size and squashfs.is_file() and squashfs.stat().st_size:
        return
    _, prefixes = listing("firecracker-ci/", "/")
    for prefix in sorted(prefixes, reverse=True):
        keys, _ = listing(prefix + "aarch64/")
        kernels = [k for k in keys if re.fullmatch(r"vmlinux-\d+\.\d+\.\d+", k.rsplit("/", 1)[-1])]
        roots = [k for k in keys if re.fullmatch(r"ubuntu-\d+\.\d+\.squashfs", k.rsplit("/", 1)[-1])]
        if not kernels or not roots:
            continue
        numeric = lambda key: tuple(map(int, re.findall(r"\d+", key.rsplit("/", 1)[-1])))
        kernel_key, root_key = max(kernels, key=numeric), max(roots, key=numeric)
        if not kernel.is_file() or not kernel.stat().st_size:
            kernel.parent.mkdir(parents=True, exist_ok=True)
            download(kernel_key, kernel)
        if not squashfs.is_file() or not squashfs.stat().st_size:
            download(root_key, squashfs)
        (directory / "artifacts.json").write_text(json.dumps({"kernel": kernel_key, "rootfs": root_key}, indent=2) + "\n")
        return
    raise RuntimeError("No complete ARM64 kernel and Ubuntu SquashFS artifact set found")


if __name__ == "__main__":
    main()
