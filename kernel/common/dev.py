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

from manifest import write_json
from layout import ALIASES, KERNEL_ROOT, REPO_ROOT, SERVICES, canonical
from debug_profile import FLAGS as LOCAL_DEBUG_FLAGS, sources as debug_source_paths
import configuration
import sources

REPO = REPO_ROOT


class Environment:
    def __init__(self, kind):
        self.kind = kind = canonical(kind)
        self.directory = KERNEL_ROOT / kind
        self.output = self.directory / 'output'
        self.output.mkdir(exist_ok=True)
        self.local = json.loads((self.output / 'config.local.json').read_text()) if (self.output / 'config.local.json').exists() else {}
        self.source, self.requested_version, self.local = sources.select(KERNEL_ROOT, self.local)
        suffix = hashlib.sha256(str(self.directory).encode()).hexdigest()[:8]
        self.project = self.local.get('project', f'kernel-debug-{kind}-{suffix}')
        self.environment = dict(os.environ, KERNEL_SOURCE=str(self.source),
            KERNEL_BUILDER_IMAGE=f'{self.project}-builder:local', ROOTFS_BUILDER_IMAGE=f'{self.project}-rootfs:local',
            KERNEL_SESSION_NAME=self.project)
        for key, default in [('JOBS', '2'), ('CPUS', '1'), ('MEMORY', '256M'), ('KERNEL_BASE_CONFIG', 'tinyconfig')]:
            self.environment[key] = os.environ.get(key, str(self.local.get(key.lower(), default)))
        self.overlay = Path(os.environ.get('ROOTFS_OVERLAY', str(self.directory / 'rootfs-overlay'))).expanduser().resolve()
        self.overlay.mkdir(parents=True, exist_ok=True)
        self.environment['ROOTFS_OVERLAY'] = str(self.overlay)
        self.service = SERVICES[kind]

    def running(self):
        raise NotImplementedError('A container backend is required')

    def up(self):
        raise NotImplementedError('A container backend is required')

    def exec(self, arguments, capture=False, interactive=False):
        raise NotImplementedError('A container backend is required')

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
        requested = getattr(self, 'requested_version', None)
        if requested and not (self.source / 'Makefile').is_file():
            sources.prepare(self.source, requested, KERNEL_ROOT)
        if not (self.source / 'Makefile').is_file() or not (self.source / 'init/main.c').is_file():
            raise ValueError(f'Bind Linux sources first: ./kernel/{self.kind}/dev.sh bind /path/to/linux (current: {self.source})')
        sources.check(self.source, requested)
        upper = self.source / 'include/uapi/linux/netfilter/xt_MARK.h'
        lower = self.source / 'include/uapi/linux/netfilter/xt_mark.h'
        if upper.exists() and lower.exists() and upper.samefile(lower):
            raise ValueError('Linux source has case-collapsed headers; use a case-sensitive source filesystem.')
        if not self.environment['JOBS'].isdigit() or int(self.environment['JOBS']) < 1:
            raise ValueError('JOBS must be a positive integer')

    def qemu(self, command, capture=False):
        return self.exec(['python3', '/scripts/kernel/qemu.py', command], capture)

    def stopped(self):
        status = json.loads(self.qemu('status', True).stdout)
        if status['running']:
            raise ValueError('The managed VM is running. Stop debugging or run dev.sh stop before rebuilding.')
        # Remove only this environment's stale ownership files before the build guard.
        self.qemu('stop')

    def refuse_running(self):
        if self.running():
            status = json.loads(self.qemu('status', True).stdout)
            if status['running']:
                raise ValueError('Stop the current debug session before rebuilding or recreating its container.')

    def build(self):
        self.refuse_running()
        self.up()
        self.stopped()
        config_hash = configuration.write(self)
        selected = self.debug_sources()
        strip = os.environ.get('KERNEL_STRIP_MODULES', str(self.local.get('strip_modules', 1)))
        self.exec(['env', 'KERNEL_STRIP_MODULES=' + strip, '/bin/bash', '/scripts/kernel/build-kernel.sh', *selected])
        write_json(self.output / 'source.local.json', dict(source=str(self.source), debug_sources=selected,
                   debug_flags=LOCAL_DEBUG_FLAGS if selected else [], config_hash=config_hash,
                   kernel_version=sources.tree_version(self.source)))
        subprocess.run([sys.executable, str(Path(__file__).with_name('workspace.py')), self.kind, str(self.source)], check=True)
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

    def debug_sources(self):
        configured = os.environ.get('KERNEL_DEBUG_SOURCES')
        return debug_source_paths(shlex.split(configured) if configured is not None else
                                  getattr(self, 'local', {}).get('debug_sources', []))

    def matching_build(self, record):
        selected = self.debug_sources()
        return (record.get('source') == str(self.source) and
                record.get('debug_sources', []) == selected and
                record.get('debug_flags', []) == (LOCAL_DEBUG_FLAGS if selected else []) and
                record.get('config_hash') == configuration.identity(self))

    def rootfs(self, force=False):
        self.refuse_running()
        source_record = self.output / 'source.local.json'
        if not (self.output / 'kernel.json').exists() or not source_record.exists() or not self.matching_build(json.loads(source_record.read_text())):
            self.build()
        else:
            self.refuse_running()
            record = self.output / 'source.local.json'
            if not record.exists() or not self.matching_build(json.loads(record.read_text())):
                raise ValueError('No build for this source binding; run dev.sh build first.')
            self.up()
            self.stopped()
        self.package_rootfs(force)

    def package_rootfs(self, force):
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
            if not record.exists() or not self.matching_build(json.loads(record.read_text())):
                raise ValueError('Existing artifacts do not match this source binding, kernel configuration or local-variable profile; '
                                 'run dev.sh build or select "Kernel: Build and debug (automatic)" first.')
            self.up()
            self.stopped()
        self.qemu('start' if paused else 'run')

    def stop(self):
        # Does not start a stopped container just to stop a VM.
        if self.running():
            self.qemu('stop')

    def prepare_shell(self):
        # Reuse a running container: compose up may recreate it after an image
        # or configuration change, killing the QEMU being inspected.
        if not self.running():
            self.up()

    def terminal(self, arguments):
        old = termios.tcgetattr(0) if os.isatty(0) else None
        try:
            if old is not None:
                tty.setraw(0)
            self.exec(arguments, interactive=True)
        finally:
            if old is not None:
                termios.tcsetattr(0, termios.TCSADRAIN, old)


def make_environment(kind):
    if canonical(kind) == 'debian-container':
        from debian import DebianEnvironment
        return DebianEnvironment()
    if canonical(kind) == 'apple-container':
        from apple import AppleEnvironment
        return AppleEnvironment('apple-container')
    raise ValueError("Unsupported kernel environment: " + kind)


def main(environment_type=None):
    environment_type = environment_type or make_environment
    # MI pipe arguments are passed as argv, without a second shell or task output.
    if len(sys.argv) >= 4 and sys.argv[2] == 'pipe' and sys.argv[1] in (*SERVICES, *ALIASES):
        environment_type(sys.argv[1]).pipe(sys.argv[3:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', choices=(*SERVICES, *ALIASES))
    parser.add_argument('command', choices=('bind', 'source', 'setup', 'up', 'build', 'rootfs', 'debug', 'start', 'boot', 'run', 'stop', 'down', 'status', 'console', 'logs', 'gdb', 'shell'))
    parser.add_argument('source', nargs='?', help='Source directory for bind')
    parser.add_argument('--force', action='store_true', help='Rebuild container images or rootfs')
    args = parser.parse_args()
    if args.command == 'source' and args.source:
        os.environ['KERNEL_VERSION'] = sources.version(args.source)
    environment = environment_type(args.environment)
    with open(environment.output / 'workflow.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        command = args.command
        if command == 'bind':
            if not args.source:
                parser.error('bind needs /path/to/linux')
            subprocess.run([sys.executable, str(Path(__file__).with_name('workspace.py')), environment.kind, args.source], check=True)
        elif command == 'source':
            environment.refuse_running()
            environment.validate_source()
            subprocess.run([sys.executable, str(Path(__file__).with_name('workspace.py')), environment.kind, str(environment.source)], check=True)
            print('Kernel source ready: ' + str(environment.source))
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
        elif command in ('debug', 'run', 'start', 'boot'):
            environment.debug(rebuild=command not in ('start', 'boot'), paused=command not in ('run', 'boot'))
        elif command == 'stop':
            environment.stop()
        elif command == 'down':
            environment.down()
        elif command == 'status':
            if environment.running():
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
            environment.prepare_shell()
            fcntl.flock(lock, fcntl.LOCK_UN)
            environment.exec_interactive(['/bin/bash'])
        elif command == 'gdb':
            environment.debug()
            fcntl.flock(lock, fcntl.LOCK_UN)
            try:
                environment.exec_interactive(['gdb-multiarch', '-q', '/output/vmlinux',
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
