#!/usr/bin/env python3
"""Run QEMU under host GDB while retaining clean guest disk shutdown."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, '/scripts/kernel')
import qemu
from manifest import file_hash, write_json

BUILD = Path('/output/qemu-build.json')
DEBUGGER = Path('/cache/run/host-gdb.json')
BINARY = os.environ.get('QEMU_BINARY', '/cache/qemu-build/qemu-system-aarch64')


def debugger_running():
    try:
        saved = json.loads(DEBUGGER.read_text())
        arguments = Path(f"/proc/{saved['pid']}/cmdline").read_bytes().split(b'\0')
        return BINARY.encode() in arguments and any(b'gdb-multiarch' in item for item in arguments)
    except (OSError, ValueError, KeyError):
        return False


def require_stopped():
    if qemu.state() or debugger_running():
        raise RuntimeError('Managed QEMU or its host debugger is running; stop the session first')


def operation_running():
    with open('/cache/workflow.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def check_build():
    record = json.loads(BUILD.read_text())
    if record['source'] != os.environ['QEMU_SOURCE_HOST'] or record['binary'] != file_hash(Path(BINARY)):
        raise RuntimeError('QEMU binary does not match this source binding/build; run dev.sh build')


def record_build():
    write_json(BUILD, dict(source=os.environ['QEMU_SOURCE_HOST'], binary=file_hash(Path(BINARY)),
                          version=Path('/cache/qemu-source/VERSION').read_text().strip()))


def exec_wrapper(arguments):
    if not arguments or arguments[0] != BINARY:
        raise ValueError('Unexpected GDB exec-wrapper target')
    plan = json.loads(Path('/cache/run/host-launch.json').read_text())
    write_json(qemu.STATE, dict(pid=os.getpid(), **plan['details']))
    os.execv(BINARY, plan['arguments'])


def finish_guest():
    # At a main breakpoint QEMU has not created its QMP/control sockets yet.
    # Detach resumes it; wait for QMP before requesting the normal disk shutdown.
    deadline = time.monotonic() + 15
    while qemu.state() and not qemu.QMP.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError('QEMU has not exposed QMP; leaving the owned guest intact')
        time.sleep(.05)
    with contextlib.redirect_stdout(sys.stderr):
        qemu.stop()


def debug(arguments, interactive=False):
    require_stopped()
    check_build()
    qemu.clear()
    argv, details = qemu.command(False)
    Path('/output/console.log').write_text('')
    write_json(Path('/cache/run/host-launch.json'), dict(arguments=argv, details=details))
    commands = ['gdb-multiarch', '-q', '-ex', 'source /scripts/kernel/gdb-persistent.gdb',
                '-ex', 'set exec-wrapper /usr/bin/python3 /scripts/runtime/vm.py exec-wrapper']
    if interactive:
        commands += ['-ex', 'break main', '-ex', 'run']
    commands += [*arguments, '--args', BINARY]
    process = subprocess.Popen(commands)
    write_json(DEBUGGER, dict(pid=process.pid))
    try:
        result = process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        DEBUGGER.unlink(missing_ok=True)
        if interactive:
            finish_guest()
    if result:
        raise RuntimeError(f'GDB exited with status {result}')


def main():
    action, *arguments = sys.argv[1:]
    qemu.RUN.mkdir(parents=True, exist_ok=True)
    if action == 'exec-wrapper':
        exec_wrapper(arguments)
        return
    if action == 'status':
        current = qemu.state()
        details = dict(current or {})
        if current and qemu.QMP.exists():
            details['vm_state'] = qemu.qmp('query-status')['status']
        print(json.dumps(dict(**details, running=bool(current or debugger_running() or operation_running()),
                              debugger=debugger_running())))
        return
    if action == 'record-build':
        record_build()
        return
    if action == 'require-stopped':
        require_stopped()
        return
    with open('/cache/workflow.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if action in ('debug-mi', 'debug'):
            debug(arguments, interactive=action == 'debug')
        elif action == 'run':
            check_build()
            qemu.start(False)
        elif action == 'stop':
            finish_guest()
        else:
            raise ValueError('Unknown QEMU runtime action')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'qemu-runtime-vm: {error}')
