#!/usr/bin/env python3
"""Apple container backend for the shared ARM64 kernel build/debug workflow."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from dev import Environment, main
from mi_pipe import pipe_command
from manifest import file_hash, write_json


class AppleEnvironment(Environment):
    def __init__(self, kind='apple-container'):
        if kind not in ('apple-container', 'debian-container'):
            raise ValueError('The Apple backend requires an Apple container environment')
        super().__init__(kind)
        self.builder = self.project + '-builder'
        self.owner = str(self.directory)
        self.builder_cpus = os.environ.get('BUILDER_CPUS', str(self.local.get('builder_cpus', 2)))
        self.builder_memory = os.environ.get('BUILDER_MEMORY', str(self.local.get('builder_memory', '1G')))
        images = Path(__file__).resolve().parent / 'images'
        toolchain = hashlib.sha256((file_hash(images / 'Dockerfile.builder') + file_hash(images / 'ubuntu.sources')).encode()).hexdigest()[:12]
        flavor = 'debian' if kind == 'debian-container' else 'alpine'
        base = os.environ.get('BASE_IMAGE', 'debian:trixie-slim' if flavor == 'debian' else 'alpine:3.22')
        rootfs = hashlib.sha256((file_hash(images / ('Dockerfile.' + flavor)) + base).encode()).hexdigest()[:12]
        self.environment.update(KERNEL_BUILDER_IMAGE='kernel-debug-toolchain-' + toolchain + ':local',
                                ROOTFS_BUILDER_IMAGE='kernel-debug-rootfs-' + flavor + '-' + rootfs + ':local')
        if 'KERNEL_BASE_CONFIG' not in os.environ and 'kernel_base_config' not in self.local:
            self.environment['KERNEL_BASE_CONFIG'] = 'tinyconfig'

    def cli(self, arguments, capture=False):
        return subprocess.run(['container', *arguments], check=True, env=self.environment,
                              text=capture, stdout=subprocess.PIPE if capture else None)

    def containers(self):
        return json.loads(self.cli(['list', '--all', '--format', 'json'], True).stdout)

    def current(self):
        current = next((entry for entry in self.containers() if entry['id'] == self.builder), None)
        if current and current['configuration'].get('labels', {}).get('kernel-debug.owner') != self.owner:
            raise ValueError(f'Container {self.builder} is not owned by this environment')
        return current

    def running(self):
        current = self.current()
        return bool(current and current['status']['state'] == 'running')

    def exec(self, arguments, capture=False, interactive=False):
        flags = ['--interactive'] if interactive else []
        return self.cli(['exec', *flags, self.builder, *arguments], capture)

    def exec_interactive(self, arguments):
        flags = ['--interactive']
        if os.isatty(0) and os.isatty(1):
            flags.append('--tty')
        return self.cli(['exec', *flags, self.builder, *arguments])

    def pipe_arguments(self, arguments):
        # Auxiliary MIEngine commands must not consume the adapter's DAP input.
        arguments, interactive = pipe_command(arguments)
        return ['container', 'exec', *(['--interactive'] if interactive else []), self.builder, *arguments]

    def pipe(self, arguments):
        command = self.pipe_arguments(arguments)
        if '--interactive' not in command[2:3]:
            with open(os.devnull, 'rb') as null:
                os.dup2(null.fileno(), 0)
        os.execvpe('container', command, self.environment)

    def image_id(self, image):
        return json.loads(self.cli(['image', 'inspect', image], True).stdout)[0]['id']

    def images(self, force=False):
        self.validate_source()
        context = self.directory.parent / 'common/images'
        previous_path = self.output / 'images.local.json'
        previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
        available = {entry['configuration']['name'].removeprefix('docker.io/library/')
                     for entry in json.loads(self.cli(['image', 'list', '--format', 'json'], True).stdout)}
        fingerprints = {}
        flavor = 'debian' if self.kind == 'debian-container' else 'alpine'
        for service, dockerfile, key in [(self.service, 'Dockerfile.builder', 'KERNEL_BUILDER_IMAGE'),
                                         ('initramfs-builder', 'Dockerfile.' + flavor, 'ROOTFS_BUILDER_IMAGE')]:
            image = self.environment[key]
            digest = hashlib.sha256((file_hash(context / dockerfile) +
                                     file_hash(context / 'ubuntu.sources') +
                                     self.environment.get('BASE_IMAGE', 'alpine:3.22')).encode()).hexdigest()
            if force or image not in available or previous.get(service) != digest:
                command = ['build', '--platform', 'linux/arm64', '--progress', 'plain', '--tag', image,
                           '--file', str(context / dockerfile)]
                if service == 'initramfs-builder':
                    command += ['--build-arg', 'BASE_IMAGE=' + self.environment.get('BASE_IMAGE', 'alpine:3.22')]
                self.cli([*command, str(context)])
            fingerprints[service] = digest
        write_json(previous_path, fingerprints)

    def volume(self, suffix, size):
        name = self.project + '-' + suffix
        # Inspect errors propagate unless the volume is actually absent.
        entries = json.loads(self.cli(['volume', 'list', '--format', 'json'], True).stdout)
        current = next((entry for entry in entries if entry['id'] == name), None)
        if current and current['configuration'].get('labels', {}).get('kernel-debug.owner') != self.owner:
            raise ValueError(f'Volume {name} is not owned by this environment')
        if not current:
            self.cli(['volume', 'create', '--label', 'kernel-debug.owner=' + self.owner, '-s', size, name])
        return name

    @staticmethod
    def mount(source, target, readonly=False, volume=False):
        source = str(source)
        if ',' in source:
            raise ValueError('container mount source paths cannot contain commas')
        value = f'type={"volume" if volume else "bind"},source={source},target={target}'
        return ['--mount', value + (',readonly' if readonly else '')]

    def up(self):
        self.images()
        image = self.environment['KERNEL_BUILDER_IMAGE']
        values = {key: self.environment[key] for key in
                  ('JOBS', 'CPUS', 'MEMORY', 'KERNEL_BASE_CONFIG', 'KERNEL_SESSION_NAME')}
        values.update(ARCH='arm64', CROSS_COMPILE=self.environment.get('CROSS_COMPILE', ''), OUTPUT_DIR='/output')
        spec = dict(image=self.image_id(image), source=str(self.source),
                    cpus=self.builder_cpus, memory=self.builder_memory, environment=values)
        fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        current = self.current()
        if current:
            if current['configuration']['labels'].get('kernel-debug.spec') == fingerprint:
                if current['status']['state'] != 'running':
                    self.cli(['start', self.builder])
                return
            self.refuse_running()
            if current['status']['state'] == 'running':
                self.cli(['stop', self.builder])
            self.cli(['delete', self.builder])
        cache = self.volume('kernel-cache', '24G')
        command = ['run', '--detach', '--init', '--name', self.builder,
                   '--cpus', self.builder_cpus, '--memory', self.builder_memory,
                   '--label', 'kernel-debug.owner=' + self.owner, '--label', 'kernel-debug.spec=' + fingerprint]
        command += self.mount(self.source, '/kernel', readonly=True)
        command += self.mount(self.output, '/output')
        command += self.mount(self.directory.parent / 'common', '/scripts/kernel', readonly=True)
        # Apple virtiofs accepts directory mounts, not individual files.
        command += self.mount(self.directory, '/scripts/environment', readonly=True)
        command += self.mount(cache, '/cache', volume=True)
        for key, value in values.items():
            command += ['--env', f'{key}={value}']
        self.cli([*command, image, 'sleep', 'infinity'])

    def package_rootfs(self, force):
        image = self.environment['ROOTFS_BUILDER_IMAGE']
        cache = self.volume('rootfs-cache', '4G')
        command = ['run', '--rm', '--name', self.project + '-rootfs', '--cpus', '2', '--memory', '2G',
                   '--label', 'kernel-debug.owner=' + self.owner,
                   '--env', 'ROOTFS_IMAGE_ID=' + self.image_id(image), '--env', f'ROOTFS_FORCE={int(force)}']
        command += self.mount(self.output, '/output')
        command += self.mount(self.directory.parent / 'common', '/scripts/kernel', readonly=True)
        command += self.mount(self.overlay, '/overlay', readonly=True)
        command += self.mount(cache, '/cache', volume=True)
        self.cli([*command, image, '/bin/sh', '/scripts/kernel/build-rootfs.sh'])

    def down(self):
        self.stop()
        if self.running():
            self.cli(['stop', self.builder])


if __name__ == '__main__':
    try:
        main(AppleEnvironment)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'kernel-container: {error}')
