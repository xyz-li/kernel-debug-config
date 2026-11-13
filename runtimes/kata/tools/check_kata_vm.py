#!/usr/bin/env python3
"""Validate rendered Kata configuration and Linux VM prerequisites."""
from pathlib import Path
import sys
import tomllib

with open(sys.argv[1], 'rb') as stream:
    config = tomllib.load(stream)
hypervisors = config.get('hypervisor', {})
selected = config.get('runtime', {}).get('hypervisor_name')
if not selected:
    if len(hypervisors) != 1:
        raise SystemExit('Set runtime.hypervisor_name when multiple hypervisors are configured')
    selected = next(iter(hypervisors))
settings = hypervisors[selected]
for key in ('path', 'kernel'):
    path = settings.get(key)
    if not path or not Path(path).is_file():
        raise SystemExit(f'Missing real {selected}.{key} asset: {path!r}')
disks = [settings.get(key) for key in ('image', 'initrd') if settings.get(key)]
if len(disks) != 1 or not Path(disks[0]).is_file():
    raise SystemExit('Configure exactly one existing Guest image or initrd')
if settings.get('shared_fs') == 'virtio-fs':
    daemon = settings.get('virtio_fs_daemon', '')
    if not daemon or not Path(daemon).is_file():
        raise SystemExit('virtio-fs needs a real virtio_fs_daemon executable')
if not Path('/dev/kvm').is_char_device():
    raise SystemExit('No /dev/kvm: enable nested virtualization and CONFIG_KVM in the Host kernel')
if selected.startswith('qemu') and not Path('/dev/vhost-vsock').is_char_device():
    raise SystemExit('QEMU needs /dev/vhost-vsock. Use a Host kernel with CONFIG_VHOST_VSOCK, or use the Kata Firecracker/Cloud Hypervisor hybrid-vsock backend.')
print(f'Kata {selected} VM assets and device prerequisites found')
