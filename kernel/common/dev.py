#!/usr/bin/env python3
"""Build a matching kernel/rootfs and prepare a managed QEMU debug session."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import termios
import tty

from manifest import file_hash, write_json
from layout import ALIASES, KERNEL_ROOT, REPO_ROOT, SERVICES, canonical

REPO = REPO_ROOT


class Environment:
    def __init__(self, kind):
        self.kind = kind = canonical(kind)
        self.directory = KERNEL_ROOT / kind
        self.output = self.directory / 'output'
        self.output.mkdir(exist_ok=True)
        self.local = json.loads((self.output / 'config.local.json').read_text()) if (self.output / 'config.local.json').exists() else {}
        self.source = Path(os.environ.get('KERNEL_SOURCE', self.local.get('source', str(REPO / 'linux-source')))).expanduser().resolve()
        suffix = hashlib.sha256(str(self.directory).encode()).hexdigest()[:8]
        self.project = self.local.get('project', f'kernel-debug-{kind}-{suffix}')
        self.environment = dict(os.environ, KERNEL_SOURCE=str(self.source),
            KERNEL_BUILDER_IMAGE=f'{self.project}-builder:local', ROOTFS_BUILDER_IMAGE=f'{self.project}-rootfs:local',
            KERNEL_SESSION_NAME=self.project)
        for key, default in [('JOBS', '2'), ('CPUS', '2'), ('MEMORY', '2G'), ('KERNEL_BASE_CONFIG', 'defconfig')]:
            self.environment[key] = os.environ.get(key, str(self.local.get(key.lower(), default)))
        self.overlay = Path(os.environ.get('ROOTFS_OVERLAY', str(self.directory / 'rootfs-overlay'))).expanduser().resolve()
        self.overlay.mkdir(parents=True, exist_ok=True)
        self.environment['ROOTFS_OVERLAY'] = str(self.overlay)
        self.service = SERVICES[kind]
        self.compose = ['docker', 'compose', '-p', self.project, '-f', str(self.directory / 'docker-compose.yml')]

    def call(self, arguments, capture=False):
        return subprocess.run(self.compose + arguments, env=self.environment, check=True,
                              text=capture, stdout=subprocess.PIPE if capture else None)

    def exec(self, arguments, capture=False):
        return self.call(['exec', '-T', self.service, *arguments], capture)

    def validate_source(self):
        image = self.local.get('source_image')
        mount = self.local.get('source_mount')
        if sys.platform == 'darwin' and image and mount and not (self.source / 'Makefile').exists():
            mount = Path(mount).expanduser().resolve()
            try:
                self.source.relative_to(mount)
            except ValueError:
                pass
            else:
                mount.mkdir(parents=True, exist_ok=True)
                with open(mount.parent / 'source-mount.lock', 'a') as mount_lock:
                    fcntl.flock(mount_lock, fcntl.LOCK_EX)
                    if not (self.source / 'Makefile').exists() and not os.path.ismount(mount):
                        subprocess.run(['hdiutil', 'attach', str(Path(image).expanduser()), '-mountpoint', str(mount), '-nobrowse'], check=True)
        if not (self.source / 'Makefile').is_file() or not (self.source / 'init/main.c').is_file():
            raise ValueError(f'Bind Linux sources first: ./kernel/{self.kind}/dev.sh bind /path/to/linux (current: {self.source})')
        upper = self.source / 'include/uapi/linux/netfilter/xt_MARK.h'
        lower = self.source / 'include/uapi/linux/netfilter/xt_mark.h'
        if upper.exists() and lower.exists() and upper.samefile(lower):
            raise ValueError('Linux source has case-collapsed headers; use a case-sensitive source filesystem.')
        if not self.environment['JOBS'].isdigit() or int(self.environment['JOBS']) < 1:
            raise ValueError('JOBS must be a positive integer')

    def images(self, force=False):
        self.validate_source()
        previous = json.loads((self.output / 'images.local.json').read_text()) if (self.output / 'images.local.json').exists() else {}
        fingerprints = {}
        changed = []
        for service, dockerfile, variable in [(self.service, 'Dockerfile', 'KERNEL_BUILDER_IMAGE'),
                                             ('initramfs-builder', 'Dockerfile.initramfs', 'ROOTFS_BUILDER_IMAGE')]:
            digest = hashlib.sha256((file_hash(self.directory / dockerfile) +
                                     file_hash(self.directory / 'ubuntu.sources') + self.environment.get('BASE_IMAGE', 'alpine:3.22')).encode()).hexdigest()
            fingerprints[service] = digest
            exists = subprocess.run(['docker', 'image', 'inspect', self.environment[variable]],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            if force or not exists or previous.get(service) != digest:
                changed.append(service)
        if changed:
            self.call(['build', *changed])
        write_json(self.output / 'images.local.json', fingerprints)

    def up(self):
        self.images()
        self.call(['up', '-d', self.service])

    def qemu(self, command, capture=False):
        return self.exec(['python3', '/scripts/kernel/qemu.py', command], capture)

    def stopped(self):
        status = json.loads(self.qemu('status', True).stdout)
        if status['running']:
            raise ValueError('The managed VM is running. Stop debugging or run dev.sh stop before rebuilding.')
        # Remove only this environment's stale ownership files before the build guard.
        self.qemu('stop')

    def refuse_running(self):
        running = self.call(['ps', '-q', '--status', 'running', self.service], True)
        if running.stdout.strip():
            status = json.loads(self.qemu('status', True).stdout)
            if status['running']:
                raise ValueError('Stop the current debug session before rebuilding or recreating its container.')

    def build(self):
        self.refuse_running()
        self.up()
        self.stopped()
        self.exec(['/bin/bash', '/scripts/kernel/build-kernel.sh'])
        write_json(self.output / 'source.local.json', dict(source=str(self.source)))
        database = self.output / 'compile_commands.linux.json'
        if database.exists():
            def mapped(value):
                return value.replace('/cache/source', str(self.source)).replace('/cache/build', str(self.output / 'generated'))
            entries = json.loads(database.read_text())
            for entry in entries:
                for key in ('file', 'directory'):
                    entry[key] = mapped(entry[key])
                if 'command' in entry:
                    entry['arguments'] = [mapped(argument) for argument in shlex.split(entry.pop('command'))]
                elif 'arguments' in entry:
                    entry['arguments'] = [mapped(argument) for argument in entry['arguments']]
            write_json(self.output / 'compile_commands.json', entries)

    def rootfs(self, force=False):
        self.refuse_running()
        source_record = self.output / 'source.local.json'
        if not (self.output / 'kernel.json').exists() or not source_record.exists() or json.loads(source_record.read_text())['source'] != str(self.source):
            self.build()
        else:
            self.refuse_running()
            record = self.output / 'source.local.json'
            if not record.exists() or json.loads(record.read_text())['source'] != str(self.source):
                raise ValueError('No build for this source binding; run dev.sh build first.')
            self.up()
            self.stopped()
        image = self.environment['ROOTFS_BUILDER_IMAGE']
        identity = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()
        self.call(['run', '--rm', '-T', '-e', f'ROOTFS_IMAGE_ID={identity}', '-e', f'ROOTFS_FORCE={int(force)}',
                   'initramfs-builder', '/bin/sh', '/scripts/kernel/build-rootfs.sh'])

    def debug(self, rebuild=True, paused=True):
        if rebuild:
            self.build()
            self.rootfs()
        else:
            self.refuse_running()
            record = self.output / 'source.local.json'
            if not record.exists() or json.loads(record.read_text())['source'] != str(self.source):
                raise ValueError('Existing artifacts do not match this source binding; run dev.sh build first.')
            self.up()
            self.stopped()
        self.qemu('start' if paused else 'run')

    def stop(self):
        # Does not start a stopped container just to stop a VM.
        result = self.call(['ps', '-q', '--status', 'running', self.service], True)
        if result.stdout.strip():
            self.qemu('stop')

    def terminal(self, arguments):
        old = termios.tcgetattr(0) if os.isatty(0) else None
        try:
            if old is not None:
                tty.setraw(0)
            self.exec(arguments)
        finally:
            if old is not None:
                termios.tcsetattr(0, termios.TCSADRAIN, old)


def main():
    # MI pipe arguments are passed as argv, without a second shell or task output.
    if len(sys.argv) >= 4 and sys.argv[2] == 'pipe' and sys.argv[1] in (*SERVICES, *ALIASES):
        environment = Environment(sys.argv[1])
        os.execvpe('docker', environment.compose + ['exec', '-T', environment.service, *sys.argv[3:]], environment.environment)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', choices=(*SERVICES, *ALIASES))
    parser.add_argument('command', choices=('bind', 'setup', 'up', 'build', 'rootfs', 'debug', 'start', 'run', 'stop', 'down', 'status', 'console', 'logs', 'gdb', 'shell'))
    parser.add_argument('source', nargs='?', help='Source directory for bind')
    parser.add_argument('--force', action='store_true', help='Rebuild Docker images or rootfs')
    args = parser.parse_args()
    environment = Environment(args.environment)
    with open(environment.output / 'workflow.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        command = args.command
        if command == 'bind':
            if not args.source:
                parser.error('bind needs /path/to/linux')
            subprocess.run([sys.executable, str(Path(__file__).with_name('workspace.py')), environment.kind, args.source], check=True)
        elif command == 'setup':
            environment.refuse_running()
            environment.images(args.force)
        elif command == 'up':
            environment.refuse_running()
            environment.up()
        elif command == 'build':
            environment.build()
            environment.rootfs()
        elif command == 'rootfs':
            environment.rootfs(args.force)
        elif command in ('debug', 'run', 'start'):
            environment.debug(rebuild=command != 'start', paused=command != 'run')
        elif command == 'stop':
            environment.stop()
        elif command == 'down':
            environment.stop()
            environment.call(['stop', environment.service])
        elif command == 'status':
            running = environment.call(['ps', '-q', '--status', 'running', environment.service], True)
            if running.stdout.strip():
                environment.qemu('status')
            else:
                print('{"running": false}')
        elif command == 'console':
            fcntl.flock(lock, fcntl.LOCK_UN)
            environment.terminal(['python3', '/scripts/kernel/qemu.py', 'console'])
        elif command == 'logs':
            fcntl.flock(lock, fcntl.LOCK_UN)
            environment.exec(['tail', '-n', '100', '-f', '/output/console.log'])
        elif command == 'shell':
            environment.up()
            fcntl.flock(lock, fcntl.LOCK_UN)
            environment.call(['exec', environment.service, '/bin/bash'])
        elif command == 'gdb':
            environment.debug()
            fcntl.flock(lock, fcntl.LOCK_UN)
            try:
                environment.call(['exec', environment.service, 'gdb-multiarch', '-q', '/output/vmlinux',
                    '-ex', 'target remote /cache/run/gdb.sock', '-ex', 'hbreak start_kernel', '-ex', 'continue'])
            finally:
                environment.stop()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'kernel-debug: {error}')
