#!/usr/bin/env python3
"""Content-based build identities shared by the kernel and rootfs stages."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid


# Check the resolved .config, since Kconfig can silently drop fragment values
# when a parent menu or dependency is disabled (notably with tinyconfig).
REQUIRED_CONFIG = ('DEBUG_INFO', 'GDB_SCRIPTS', 'BLK_DEV_INITRD', 'RD_GZIP',
                   'DEVTMPFS', 'SERIAL_AMBA_PL011_CONSOLE', 'BINFMT_ELF',
                   'BINFMT_SCRIPT', 'VIRTIO', 'VIRTIO_MMIO', 'VIRTIO_NET', 'INET')


def validate_config(path):
    values = set(Path(path).read_text().splitlines())
    missing = [f'CONFIG_{symbol}=y' for symbol in REQUIRED_CONFIG
               if f'CONFIG_{symbol}=y' not in values]
    if missing:
        raise ValueError('Required kernel configuration missing: ' + ', '.join(missing) +
                         '. Rebuild with dev.sh build before debugging.')


def validate_disk_config(path):
    values = set(Path(path).read_text().splitlines())
    missing = [symbol for symbol in ('BLOCK', 'VIRTIO_BLK', 'EXT4_FS', 'FILE_LOCKING', 'VIRTIO_CONSOLE',
                                    'RTC_CLASS', 'RTC_DRV_PL031', 'RTC_HCTOSYS')
               if f'CONFIG_{symbol}=y' not in values]
    if missing:
        raise ValueError('Persistent guest needs built-in storage, file locking, control and clock support: ' + ', '.join(missing))


def validate_network_config(path):
    text = Path(path).read_text()
    required = ('NF_TABLES', 'NF_TABLES_INET', 'NF_CONNTRACK', 'NF_NAT', 'NFT_CT', 'NFT_NAT',
                'NFT_MASQ', 'NFT_COMPAT', 'IP_NF_IPTABLES', 'IP_NF_FILTER', 'IP_NF_NAT',
                'IP6_NF_IPTABLES', 'IP6_NF_FILTER')
    missing = [name for name in required if not re.search(r'^CONFIG_' + name + r'=[ym]$', text, re.M)]
    if missing:
        raise ValueError('Required iptables/nftables support missing after Kconfig: ' + ', '.join(missing))


def validate_requested_config(resolved, requested):
    actual = dict(re.findall(r'^(CONFIG_\w+)=(.*)$', Path(resolved).read_text(), re.M))
    desired = dict(re.findall(r'^(CONFIG_\w+)=(.*)$', Path(requested).read_text(), re.M))
    # A missing/renamed tristate must never silently produce an unusable module profile.
    missing = [name + '=' + value for name, value in desired.items()
               if value == 'm' and actual.get(name) != 'm']
    if missing:
        raise ValueError('Requested modules were dropped or forced built-in; check Kconfig dependencies: ' + ', '.join(missing))


def disk_uuid(path):
    with open(path, 'rb') as stream:
        stream.seek(1024)
        block = stream.read(1024)
    if len(block) != 1024 or block[56:58] != b'\x53\xef':
        raise ValueError('Persistent root disk is not a valid ext4 filesystem')
    return str(uuid.UUID(bytes=block[104:120]))


def disk_fingerprint(output, scripts, overlay, image_id):
    kernel = json.loads((output / 'kernel.json').read_text())
    inputs = dict(release=kernel['release'], modules=kernel['modules'], image=image_id,
                  overlay=tree_hash(overlay), scripts={name: file_hash(scripts / name) for name in
                  ('build-disk-rootfs.sh', 'guest-bootstrap', 'guest-disk-rcS', 'guest-control', 'guest-udhcpc')})
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


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
                  for name in ('build-rootfs.sh', 'manifest.py', 'guest-init', 'guest-rcS', 'guest-network', 'guest-udhcpc')})
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
    elif sys.argv[1] == 'check-config':
        try:
            validate_config(sys.argv[2])
        except ValueError as error:
            raise SystemExit(str(error))
    elif sys.argv[1] == 'check-network-config':
        validate_network_config(sys.argv[2])
    elif sys.argv[1] == 'check-requested-config':
        validate_requested_config(sys.argv[2], sys.argv[3])
