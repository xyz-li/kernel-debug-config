#!/usr/bin/env python3
"""Manage exactly one QEMU owned by this environment's native cache."""
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import time

from manifest import file_hash, write_json

RUN = Path('/cache/run')
STATE = RUN / 'qemu.json'
QMP = RUN / 'qmp.sock'
GDB = RUN / 'gdb.sock'
CONSOLE = RUN / 'console.sock'


def owned(state):
    try:
        arguments = Path(f"/proc/{state['pid']}/cmdline").read_bytes().split(b'\0')
        return state['name'].encode() in arguments and str(QMP).encode() in b' '.join(arguments)
    except (OSError, KeyError):
        return False


def qmp(command):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(3)
        connection.connect(str(QMP))
        stream = connection.makefile('rwb')
        json.loads(stream.readline())
        for request in ('qmp_capabilities', command):
            stream.write(json.dumps({'execute': request}).encode() + b'\n')
            stream.flush()
            while True:
                line = stream.readline()
                if not line:
                    if request == 'quit':
                        return None
                    raise RuntimeError('QMP disconnected')
                reply = json.loads(line)
                if 'error' in reply:
                    raise RuntimeError(reply['error'])
                if 'return' in reply:
                    break
        return reply['return']


def state():
    if STATE.exists():
        result = json.loads(STATE.read_text())
        if owned(result):
            return result
    return None


def clear():
    for path in (STATE, QMP, GDB, CONSOLE):
        path.unlink(missing_ok=True)


def stop():
    current = state()
    if current:
        try:
            qmp('quit')
        except (OSError, RuntimeError):
            if owned(current):
                os.kill(current['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 5
        while owned(current) and time.monotonic() < deadline:
            time.sleep(.05)
        if owned(current):
            raise RuntimeError('Managed QEMU did not stop; refusing to forget its ownership')
    clear()
    if current:
        print('Managed QEMU stopped', flush=True)


def start(paused):
    if state():
        raise RuntimeError('Managed QEMU is already running; stop the current session first')
    clear()
    manifest = json.loads(Path('/output/kernel.json').read_text())
    for artifact in ('Image', 'vmlinux'):
        if file_hash(Path('/output') / artifact) != manifest[artifact.lower()]:
            raise RuntimeError(f'{artifact} differs from the recorded build; rebuild first')
    if not Path('/output/initramfs.cpio.gz').is_file():
        raise RuntimeError('Build rootfs first')
    rootfs = json.loads(Path('/output/rootfs.json').read_text())
    if (rootfs['release'], rootfs['modules']) != (manifest['release'], manifest['modules']):
        raise RuntimeError('Rootfs modules do not match the kernel; rebuild rootfs')
    if rootfs['archive'] != file_hash(Path('/output/initramfs.cpio.gz')):
        raise RuntimeError('Rootfs archive changed since packaging; rebuild rootfs')
    name = os.environ.get('KERNEL_SESSION_NAME', 'kernel-debug')
    arguments = ['qemu-system-aarch64', '-name', name, '-machine', 'virt', '-accel', 'tcg',
                 '-cpu', 'cortex-a57', '-m', os.environ.get('MEMORY', '2G'), '-smp', os.environ.get('CPUS', '2'),
                 '-kernel', '/output/Image', '-initrd', '/output/initramfs.cpio.gz',
                 '-append', 'console=ttyAMA0 nokaslr rdinit=/init', '-display', 'none', '-monitor', 'none',
                 '-qmp', f'unix:{QMP},server=on,wait=off',
                 '-chardev', f'socket,path={GDB},server=on,wait=off,id=gdb0', '-gdb', 'chardev:gdb0',
                 '-chardev', f'socket,path={CONSOLE},server=on,wait=off,id=uart0,logfile=/output/console.log',
                 '-serial', 'chardev:uart0', '-netdev', 'user,id=net0', '-device', 'virtio-net-device,netdev=net0']
    if paused:
        arguments.append('-S')
    Path('/output/console.log').write_text('')
    with open('/output/qemu.log', 'wb') as log:
        process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   start_new_session=True, close_fds=True)
    write_json(STATE, dict(pid=process.pid, name=name, release=manifest['release'], started_paused=paused))
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(Path('/output/qemu.log').read_text())
            try:
                status = qmp('query-status')
                if GDB.exists() and CONSOLE.exists():
                    print(f"QEMU ready: {manifest['release']}; status={status['status']}; GDB={GDB}", flush=True)
                    return
            except (OSError, ValueError):
                pass
            time.sleep(.05)
        raise RuntimeError('QEMU did not become ready; inspect output/qemu.log')
    except BaseException:
        stop()
        raise


def console():
    if not state():
        raise RuntimeError('Start a managed QEMU first')
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect(str(CONSOLE))
        print('Guest console; Ctrl+] disconnects and keeps the VM running.', file=sys.stderr, flush=True)
        sys.stdout.buffer.write(Path('/output/console.log').read_bytes()[-65536:])
        sys.stdout.buffer.flush()
        while True:
            ready, _, _ = select.select([connection, 0], [], [])
            if connection in ready:
                data = connection.recv(65536)
                if not data:
                    return
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            if 0 in ready:
                data = os.read(0, 4096)
                if not data:
                    return
                before, escape, _ = data.partition(b'\x1d')
                if before:
                    connection.sendall(before)
                if escape:
                    return


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    if sys.argv[1] == 'console':
        console()
        return
    with open('/cache/workflow.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        command = sys.argv[1]
        if command in ('start', 'run'):
            start(command == 'start')
        elif command == 'stop':
            stop()
        elif command == 'status':
            current = state()
            details = dict(current or {})
            if current:
                details['vm_state'] = qmp('query-status')['status']
            print(json.dumps(dict(running=bool(current), **details)))
        else:
            raise ValueError('Unknown QEMU command')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        raise SystemExit(f'QEMU: {error}')
