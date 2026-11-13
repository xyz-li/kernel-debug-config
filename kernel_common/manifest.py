#!/usr/bin/env python3
"""Content-based build identities shared by the kernel and rootfs stages."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(root):
    root = Path(root)
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.name == '.gitkeep':
            continue
        info = path.lstat()
        digest.update(str(path.relative_to(root)).encode() + b'\0')
        digest.update(str(stat.S_IMODE(info.st_mode)).encode() + b'\0')
        if path.is_symlink():
            digest.update(os.readlink(path).encode())
        elif path.is_file():
            digest.update(file_hash(path).encode())
        elif not path.is_dir():
            raise ValueError(f'Unsupported file type: {path}')
    return digest.hexdigest()


def write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.part')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def normalize_config(files):
    values = {}
    for filename in files:
        for line in Path(filename).read_text().splitlines():
            match = re.match(r'(CONFIG_\w+)=("(?:[^"\\]|\\.)*"|[^#\s]+)', line)
            disabled = re.match(r'# (CONFIG_\w+) is not set', line)
            if match:
                values[match[1]] = f'{match[1]}={match[2]}'
            elif disabled:
                values[disabled[1]] = f'# {disabled[1]} is not set'
    return '\n'.join(values.values()) + '\n'


def kernel_manifest(output, release):
    return dict(schema=1, release=release, image=file_hash(output / 'Image'),
                vmlinux=file_hash(output / 'vmlinux'), config=file_hash(output / 'kernel.config'),
                modules=tree_hash(output / 'modules' / release))


def rootfs_fingerprint(output, scripts, overlay, image_id):
    kernel = json.loads((output / 'kernel.json').read_text())
    inputs = dict(release=kernel['release'], modules=kernel['modules'], image=image_id,
                  overlay=tree_hash(overlay), scripts={name: file_hash(scripts / name)
                  for name in ('build-rootfs.sh', 'manifest.py', 'guest-init', 'guest-rcS', 'guest-udhcpc')})
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def rootfs_valid(output, fingerprint):
    try:
        record = json.loads((output / 'rootfs.json').read_text())
        return record['fingerprint'] == fingerprint and record['archive'] == file_hash(output / 'initramfs.cpio.gz')
    except (OSError, ValueError, KeyError):
        return False


if __name__ == '__main__':
    output = Path(os.environ.get('OUTPUT_DIR', '/output'))
    if sys.argv[1] == 'kernel':
        write_json(output / 'kernel.json', kernel_manifest(output, sys.argv[2]))
    elif sys.argv[1] == 'rootfs-fingerprint':
        print(rootfs_fingerprint(output, Path(__file__).parent, Path('/overlay'), os.environ['ROOTFS_IMAGE_ID']))
    elif sys.argv[1] == 'rootfs-record':
        kernel = json.loads((output / 'kernel.json').read_text())
        write_json(output / 'rootfs.json', dict(fingerprint=sys.argv[2], release=kernel['release'],
                   modules=kernel['modules'], archive=file_hash(output / 'initramfs.cpio.gz')))
    elif sys.argv[1] == 'rootfs-check':
        raise SystemExit(0 if rootfs_valid(output, sys.argv[2]) else 1)
    elif sys.argv[1] == 'normalize-config':
        Path(sys.argv[-1]).write_text(normalize_config(sys.argv[2:-1]))
