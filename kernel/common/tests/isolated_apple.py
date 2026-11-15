"""Run DAP checks in a disposable container without touching a user's VM."""
import json
import os
from pathlib import Path
import subprocess
import uuid

from apple import AppleEnvironment


class IsolatedApple:
    def __init__(self, root, source, artifacts=None):
        self.root = root
        self.source = source
        self.artifacts = artifacts or root / 'output'
        self.output = self.artifacts / 'test-run' if artifacts else root / 'output/breakpoint-smoke'
        self.output.mkdir(exist_ok=True)
        self.name = 'kernel-bp-test-' + uuid.uuid4().hex[:8]
        self.environment = AppleEnvironment()

    def exec_command(self, *arguments, interactive=False):
        return ['container', 'exec', *(['--interactive'] if interactive else []), self.name, *arguments]

    def prepare(self, config):
        for name in ('Image', 'vmlinux', 'kernel.config', 'kernel.json', 'rootfs.json', 'initramfs.cpio.gz'):
            destination = self.output / name
            destination.unlink(missing_ok=True)
            os.link(self.artifacts / name, destination)
        common = self.root.parent / 'common'
        pipe = self.output / 'gdb-pipe'
        pipe.write_text(f'''#!/usr/bin/env python3
import os,sys
sys.path.insert(0,{str(common)!r})
from mi_pipe import pipe_command
arguments,interactive=pipe_command(sys.argv[1:])
if not interactive:
    with open(os.devnull,'rb') as null:os.dup2(null.fileno(),0)
command=['container','exec',*(['--interactive'] if interactive else []),{self.name!r},*arguments]
os.execvp('container',command)
''')
        pipe.chmod(0o755)
        config['pipeTransport']['pipeProgram'] = str(pipe)
        config['pipeTransport']['pipeArgs'] = []
        # The disposable container has no build cache with generated GDB helpers.
        config['customLaunchSetupCommands'] = [command for command in config['customLaunchSetupCommands']
                                                if not command['text'].startswith('source ')]
        command = ['container', 'run', '--detach', '--rm', '--init', '--name', self.name,
                   '--cpus', '2', '--memory', '4G', '--env', 'KERNEL_SESSION_NAME=' + self.name,
                   '--label', 'kernel-debug.test=' + str(self.root)]
        for source, target, readonly in ((self.output, '/output', False), (common, '/scripts/kernel', True),
                                         (self.source, '/kernel', True), (self.source, '/cache/source', True)):
            command += self.environment.mount(source, target, readonly=readonly)
        command += [self.environment.environment['KERNEL_BUILDER_IMAGE'], 'sleep', 'infinity']
        try:
            with open(self.output / 'dap-prepare.log', 'w') as log:
                subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
                subprocess.run(self.exec_command('python3', '/scripts/kernel/qemu.py', 'start'),
                               check=True, stdout=log, stderr=subprocess.STDOUT)
        except BaseException:
            self.cleanup()
            raise

    def status(self):
        return json.loads(subprocess.check_output(
            self.exec_command('python3', '/scripts/kernel/qemu.py', 'status'), text=True))

    def cleanup(self):
        current = subprocess.run(['container', 'inspect', self.name], text=True, capture_output=True)
        if current.returncode:
            return
        record = json.loads(current.stdout)[0]
        if record['configuration'].get('labels', {}).get('kernel-debug.test') != str(self.root):
            raise RuntimeError('Refusing to clean up a container not owned by this test')
        if record['status']['state'] == 'running':
            subprocess.run(self.exec_command('python3', '/scripts/kernel/qemu.py', 'stop'), check=True)
            subprocess.run(['container', 'stop', self.name], check=True)
        else:
            subprocess.run(['container', 'delete', self.name], check=True)
