#!/usr/bin/env python3
"""Build and debug QEMU itself in an independent Apple container."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

DIRECTORY = Path(__file__).resolve().parent
REPO = DIRECTORY.parents[1]
sys.path.insert(0, str(REPO / 'kernel/common'))
from apple import AppleEnvironment
from manifest import disk_uuid, file_hash, write_json
from storage import clone_disk


class Runtime(AppleEnvironment):
    # Reuse the container ownership, native volume and MI transport primitives.
    def __init__(self):
        self.directory = DIRECTORY
        self.output = DIRECTORY / 'output'
        self.output.mkdir(exist_ok=True)
        self.source = Path(os.environ.get('QEMU_SOURCE', REPO.parent / 'qemu')).expanduser().resolve()
        self.project = 'qemu-debug-' + hashlib.sha256(str(DIRECTORY).encode()).hexdigest()[:8]
        self.builder = self.project + '-builder'
        self.owner = str(DIRECTORY)
        self.builder_cpus = os.environ.get('BUILDER_CPUS', '2')
        self.builder_memory = os.environ.get('BUILDER_MEMORY', '1G')
        self.environment = dict(os.environ, KERNEL_SESSION_NAME=self.project,
                                CPUS=os.environ.get('CPUS', '1'), MEMORY=os.environ.get('MEMORY', '256M'),
                                JOBS=os.environ.get('JOBS', '2'), QEMU_BINARY='/cache/qemu-build/qemu-system-aarch64')
        self.image = self.project + '-toolchain:local'

    def validate_source(self):
        for marker in ('configure', 'VERSION', 'system/vl.c'):
            if not (self.source / marker).is_file():
                raise ValueError(f'Bind QEMU sources first: dev.sh bind /path/to/qemu (missing {marker})')
        if not self.environment['JOBS'].isdigit() or int(self.environment['JOBS']) < 1:
            raise ValueError('JOBS must be a positive integer')

    def images(self, force=False):
        fingerprint = hashlib.sha256(''.join(file_hash(DIRECTORY / name) for name in
                                            ('Dockerfile', 'ubuntu.sources')).encode()).hexdigest()
        record = self.output / 'image.local.json'
        previous = json.loads(record.read_text()) if record.exists() else {}
        available = {item['configuration']['name'].removeprefix('docker.io/library/') for item in
                     json.loads(self.cli(['image', 'list', '--format', 'json'], True).stdout)}
        if force or self.image not in available or previous.get('fingerprint') != fingerprint:
            self.cli(['build', '--platform', 'linux/arm64', '--progress', 'plain', '--tag', self.image,
                      '--file', str(DIRECTORY / 'Dockerfile'), str(DIRECTORY)])
        write_json(record, dict(fingerprint=fingerprint))

    def qemu(self, command, capture=False):
        return self.exec(['python3', '/scripts/runtime/vm.py', command], capture)

    def refuse_running(self):
        if self.running() and json.loads(self.qemu('status', True).stdout)['running']:
            raise ValueError('Stop the QEMU debug session or managed VM before changing its build or assets')

    def up(self):
        self.validate_source()
        self.images()
        values = {key: self.environment[key] for key in ('CPUS', 'MEMORY', 'JOBS', 'QEMU_BINARY', 'KERNEL_SESSION_NAME')}
        values['QEMU_SOURCE_HOST'] = str(self.source)
        spec = dict(source=str(self.source), image=self.image_id(self.image), cpus=self.builder_cpus,
                    memory=self.builder_memory, environment=values)
        fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        current = self.current()
        if current:
            if current['configuration']['labels'].get('kernel-debug.spec') == fingerprint:
                if current['status']['state'] != 'running':
                    self.cli(['start', self.builder])
                return
            self.refuse_running()
            if self.running():
                self.cli(['stop', self.builder])
            self.cli(['delete', self.builder])
        cache = self.volume('cache', '8G')
        command = ['run', '--detach', '--init', '--name', self.builder, '--cpus', self.builder_cpus,
                   '--memory', self.builder_memory, '--label', 'kernel-debug.owner=' + self.owner,
                   '--label', 'kernel-debug.spec=' + fingerprint]
        for source, destination in ((self.source, '/src/qemu'), (DIRECTORY, '/scripts/runtime'),
                                    (REPO / 'kernel/common', '/scripts/kernel')):
            command += self.mount(source, destination, readonly=True)
        command += self.mount(self.output, '/output') + self.mount(cache, '/cache', volume=True)
        for key, value in values.items():
            command += ['--env', key + '=' + value]
        self.cli([*command, self.image, 'sleep', 'infinity'])

    def build(self):
        self.refuse_running()
        self.up()
        self.exec(['/bin/bash', '/scripts/runtime/build.sh'])

    def import_guest(self, source):
        self.refuse_running()
        source = source.expanduser().resolve()
        if source == self.output:
            raise ValueError('Guest source and destination must differ')
        # Coordinate with the kernel workflow before snapshotting its disk.
        with open(source / 'workflow.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if source == REPO / 'kernel/debian-container/output':
                from debian import DebianEnvironment
                guest = DebianEnvironment()
                if guest.running() and json.loads(guest.qemu('status', True).stdout)['running']:
                    raise ValueError('Stop the Debian kernel-debug guest before importing its root disk')
            disk = source / 'rootfs.ext4'
            disk_uuid(disk)
            with disk.open('rb') as stream:
                stream.seek(1024 + 58)
                if not int.from_bytes(stream.read(2), 'little') & 1:
                    raise ValueError('Guest source disk was not shut down cleanly; boot it and use dev.sh down first')
            self.up()
            # The disk is copied once. Later imports update only matching boot artifacts.
            target = self.output / 'rootfs.ext4'
            if not target.exists():
                partial = target.with_suffix('.ext4.part')
                clone_disk(disk, partial)
                partial.replace(target)
            for name in ('Image', 'vmlinux', 'kernel.config', 'kernel.json', 'initramfs.cpio.gz'):
                partial = self.output / (name + '.part')
                shutil.copy2(source / name, partial)
                partial.replace(self.output / name)
            rootfs = json.loads((source / 'rootfs.json').read_text())
            rootfs['disk_uuid'] = disk_uuid(target)
            write_json(self.output / 'rootfs.json', rootfs)
            (self.output / 'rootfs.uuid').write_text(rootfs['disk_uuid'] + '\n')
        print('Independent persistent Debian guest ready; existing runtime disk preserved', flush=True)

    def ensure_guest(self):
        if not (self.output / 'rootfs.json').exists():
            self.import_guest(REPO / 'kernel/debian-container/output')

    def stop(self):
        if self.running():
            self.qemu('stop')



def main():
    runtime = Runtime()
    if len(sys.argv) > 2 and sys.argv[1] == 'pipe':
        runtime.pipe(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('bind', 'setup', 'up', 'build', 'guest', 'run', 'debug',
                                           'console', 'logs', 'stop', 'down', 'status', 'shell'))
    parser.add_argument('path', nargs='?')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    with open(runtime.output / 'workflow.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        command = args.command
        if command == 'bind':
            if not args.path:
                parser.error('bind requires /path/to/qemu')
            subprocess.run([sys.executable, str(DIRECTORY.parent / 'common/bind.py'), 'qemu', args.path], check=True)
        elif command == 'setup':
            runtime.refuse_running()
            runtime.images(args.force)
        elif command == 'up':
            runtime.refuse_running()
            runtime.up()
        elif command == 'build':
            runtime.build()
            runtime.ensure_guest()
        elif command == 'guest':
            runtime.import_guest(Path(args.path) if args.path else REPO / 'kernel/debian-container/output')
        elif command == 'run':
            runtime.up()
            runtime.ensure_guest()
            runtime.qemu('run')
        elif command == 'debug':
            runtime.build()
            runtime.ensure_guest()
            fcntl.flock(lock, fcntl.LOCK_UN)
            runtime.exec_interactive(['python3', '/scripts/runtime/vm.py', 'debug'])
        elif command == 'status':
            if runtime.running():
                runtime.qemu('status')
            else:
                print('{"running": false}')
        elif command == 'stop':
            runtime.stop()
        elif command == 'down':
            runtime.down()
        elif command in ('console', 'logs', 'shell'):
            fcntl.flock(lock, fcntl.LOCK_UN)
            if command == 'console':
                runtime.terminal(['python3', '/scripts/kernel/qemu.py', 'console'])
            elif command == 'logs':
                runtime.exec(['tail', '-n', '100', '-f', '/output/console.log'])
            else:
                runtime.prepare_shell()
                runtime.exec_interactive(['/bin/bash'])


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'qemu-runtime: {error}')
