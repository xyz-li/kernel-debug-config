#!/usr/bin/env python3
"""Validate settings and write the exact Cloud Hypervisor launch arguments."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import urllib.request


def validate(env):
    host, guest = (ipaddress.IPv4Address(env[k]) for k in ('HOST_IP', 'GUEST_IP'))
    network = ipaddress.IPv4Network(f'{host}/{env["PREFIX"]}', strict=False)
    if host == guest or guest not in network or any(a in (network.network_address, network.broadcast_address) for a in (host, guest)):
        raise ValueError('Guest and gateway must be distinct usable addresses in one subnet')
    for key in ('DNS_SERVER', 'DNS_SECONDARY'):
        ipaddress.IPv4Address(env[key])
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,15}', env['TAP_DEV']):
        raise ValueError('Invalid TAP device')
    mac = env['GUEST_MAC']
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', mac) or int(mac[:2], 16) & 1:
        raise ValueError('Invalid unicast MAC')
    if not 1 <= int(env['VCPUS']) <= 32 or int(env['MEMORY_MIB']) < 128 or not 1 <= int(env['SSH_PORT']) <= 65535:
        raise ValueError('Invalid CPU, memory or SSH port setting')
    if any(env[k] not in ('0', '1') for k in ('ENABLE_NETWORK', 'ENABLE_NAT', 'GUEST_DEBUG')):
        raise ValueError('Flags must be 0 or 1')
    if env['SECCOMP'] not in ('true', 'false', 'log', 'errno'):
        raise ValueError('Invalid SECCOMP action')
    if env['GUEST_MODE'] not in ('serial', 'ssh') or env['GUEST_MODE'] == 'ssh' and env['ENABLE_NETWORK'] != '1':
        raise ValueError('SSH mode requires ENABLE_NETWORK=1')
    # CH device options use commas as delimiters; reject paths it cannot represent.
    for key in ('WORKDIR', 'KERNEL', 'BASE_ROOTFS'):
        if not Path(env[key]).is_absolute() or any(c in env[key] for c in (',', '\n', '\0')):
            raise ValueError(f'{key} must be an absolute path without commas/newlines')
    if Path(env['WORKDIR']).resolve() == Path('/') or len(os.fsencode(env['WORKDIR'])) >= 80:
        raise ValueError('WORKDIR must be a dedicated absolute path shorter than 80 bytes')
    if Path(env['BASE_ROOTFS']).resolve() in {
        Path(env['WORKDIR'], name).resolve() for name in ('rootfs-run.ext4', 'rootfs-serial.ext4', 'rootfs-ssh.ext4')
    }:
        raise ValueError('BASE_ROOTFS must differ from all prepared and runtime disks')


def arguments(env):
    validate(env)
    work = Path(env['WORKDIR'])
    args = ['--api-socket', str(work / 'api.socket'), '--kernel', env['KERNEL'],
            '--disk', f'path={work / "rootfs-run.ext4"},image_type=raw',
            '--cpus', f'boot={1 if env["GUEST_DEBUG"] == "1" else int(env["VCPUS"])}',
            '--memory', f'size={int(env["MEMORY_MIB"])}M',
            '--cmdline', 'console=ttyAMA0 root=/dev/vda rw rootwait nokaslr panic=1',
            '--serial', 'tty', '--console', 'off', '--seccomp', env['SECCOMP']]
    if env['ENABLE_NETWORK'] == '1':
        args += ['--net', f'tap={env["TAP_DEV"]},mac={env["GUEST_MAC"]}']
    if env['GUEST_DEBUG'] == '1':
        args += ['--gdb', f'path={work / "gdb.socket"}']
    return args


def kernel(env):
    destination = Path(env['KERNEL'])
    if not destination.exists():
        digest = env['KERNEL_SHA256']
        if not re.fullmatch(r'[0-9a-fA-F]{64}', digest) or not env['KERNEL_URL'].startswith('https://'):
            raise ValueError('Kernel download requires HTTPS and a SHA256')
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + '.part')
        sha = hashlib.sha256()
        try:
            print(f'Downloading verified CH ARM64 kernel: {env["KERNEL_URL"]}', flush=True)
            with urllib.request.urlopen(env['KERNEL_URL'], timeout=60) as response, temporary.open('wb') as output:
                while chunk := response.read(1024 * 1024):
                    sha.update(chunk)
                    output.write(chunk)
            if sha.hexdigest() != digest.lower():
                raise ValueError('Kernel SHA256 mismatch')
            check_image(temporary)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    check_image(destination)


def check_image(path):
    with Path(path).open('rb') as f:
        f.seek(56)
        if f.read(4) != b'ARM\x64':
            raise ValueError('KERNEL must be a raw ARM64 Image; use the matching ELF only as VMLINUX')


if __name__ == '__main__':
    operation = sys.argv[1]
    validate(os.environ)
    if operation == 'kernel':
        kernel(os.environ)
    elif operation == 'args':
        Path(os.environ['WORKDIR'], 'args.json').write_text(json.dumps(arguments(os.environ), indent=2) + '\n')
    elif operation != 'validate':
        raise SystemExit(f'Unknown operation: {operation}')
