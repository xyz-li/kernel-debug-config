#!/usr/bin/env python3
"""Lightweight Debian guest with a persistent ext4 root disk."""
import os
import subprocess
import json
import uuid

from apple import AppleEnvironment
from dev import main
from manifest import disk_fingerprint, disk_uuid, file_hash, validate_disk_config, write_json


class DebianEnvironment(AppleEnvironment):
    def __init__(self, kind='debian-container'):
        super().__init__(kind)
        for key, value in [('CPUS', '1'), ('MEMORY', '256M')]:
            if key not in os.environ and key.lower() not in self.local:
                self.environment[key] = value
        if 'BUILDER_MEMORY' not in os.environ and 'builder_memory' not in self.local:
            self.builder_memory = '1G'
        self.environment['BASE_IMAGE'] = os.environ.get('BASE_IMAGE', 'debian:trixie-slim')

    def exec_interactive(self, arguments):
        if arguments and arguments[0] == 'gdb-multiarch':
            arguments = [arguments[0], '-ex', 'source /scripts/kernel/gdb-persistent.gdb', *arguments[1:]]
        return super().exec_interactive(arguments)

    def package_rootfs(self, force):
        validate_disk_config(self.output / 'kernel.config')
        image = self.environment['ROOTFS_BUILDER_IMAGE']
        kernel = json.loads((self.output / 'kernel.json').read_text())
        identity = self.output / 'rootfs.uuid'
        disk = self.output / 'rootfs.ext4'
        if not identity.exists():
            if disk.exists():
                raise ValueError('Existing root disk has no ownership UUID; refusing to replace it')
            identity.write_text(str(uuid.uuid4()) + '\n')
        expected = identity.read_text().strip()
        if disk.exists() and disk_uuid(disk) != expected:
            raise ValueError('Root disk UUID changed; refusing to replace or boot an unrelated disk')
        fingerprint = disk_fingerprint(self.output, self.directory.parent / 'common', self.overlay, self.image_id(image))
        record = self.output / 'rootfs.json'
        if not force and disk.exists() and record.exists():
            previous = json.loads(record.read_text())
            archive = self.output / 'initramfs.cpio.gz'
            if (previous.get('fingerprint') == fingerprint and archive.exists() and
                    previous.get('archive') == file_hash(archive)):
                print('Debian disk preserved; bootstrap and modules unchanged', flush=True)
                return
        cache = self.volume('rootfs-cache', '4G')
        command = ['run', '--rm', '--name', self.project + '-rootfs', '--cpus', '1', '--memory', '1G',
                   '--label', 'kernel-debug.owner=' + self.owner,
                   '--env', 'ROOTFS_IMAGE_ID=' + self.image_id(image), '--env', f'ROOTFS_FORCE={int(force)}',
                   '--env', 'ROOTFS_UUID=' + expected, '--env', 'KERNEL_RELEASE=' + kernel['release'],
                   '--env', 'MODULES_HASH=' + kernel['modules'],
                   '--env', 'ROOTFS_SIZE_MIB=' + os.environ.get('ROOTFS_SIZE_MIB', str(self.local.get('rootfs_size_mib', 2048)))]
        command += self.mount(self.output, '/output')
        command += self.mount(self.directory.parent / 'common', '/scripts/kernel', readonly=True)
        command += self.mount(self.overlay, '/overlay', readonly=True)
        command += self.mount(cache, '/cache', volume=True)
        self.cli([*command, image, '/bin/sh', '/scripts/kernel/build-disk-rootfs.sh'])
        if disk_uuid(disk) != expected:
            raise ValueError('Packaged disk UUID does not match its ownership record')
        write_json(record, dict(format='ext4', distro='Debian 13', fingerprint=fingerprint,
                   release=kernel['release'], modules=kernel['modules'], disk_uuid=expected,
                   archive=file_hash(self.output / 'initramfs.cpio.gz')))


if __name__ == '__main__':
    try:
        main(DebianEnvironment)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'kernel-debian: {error}')
