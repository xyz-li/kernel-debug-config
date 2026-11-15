#!/usr/bin/env python3
"""Exercise the real QEMU host debugger, guest network and persistent disk."""
import argparse
import glob
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output'
LOG = OUTPUT / 'console.log'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--existing', action='store_true')
args = parser.parse_args()


def cli(command, timeout=120):
    return subprocess.run([str(ROOT / 'dev.sh'), command], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def wait_guest():
    deadline = time.monotonic() + 60
    while 'KERNEL_DEBUG_READY' not in LOG.read_text(errors='replace'):
        if time.monotonic() > deadline:
            raise RuntimeError(LOG.read_text(errors='replace')[-5000:])
        time.sleep(.1)


def guest_command(command):
    console = subprocess.Popen([str(ROOT / 'dev.sh'), 'console'], stdin=subprocess.PIPE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    beginning = len(LOG.read_text(errors='replace'))
    try:
        console.stdin.write((command + " && printf '\\nQEMU_GUEST_%s\\n' OK\r").encode())
        console.stdin.flush()
        deadline = time.monotonic() + 45
        while not re.search(r'\nQEMU_GUEST_OK\n', LOG.read_text(errors='replace')[beginning:]):
            if time.monotonic() > deadline:
                raise RuntimeError(LOG.read_text(errors='replace')[-5000:])
            time.sleep(.1)
        console.stdin.write(b'\x1d')
        console.stdin.flush()
        console.communicate(timeout=10)
    finally:
        if console.poll() is None:
            console.terminate()
            console.wait(timeout=5)


if json.loads(cli('status').stdout)['running']:
    raise SystemExit('Stop this environment before running the smoke test')
cli('up' if args.existing else 'build', timeout=900)
workspace = json.loads((OUTPUT / 'debug.local.code-workspace').read_text())
source = next(Path(folder['path']) for folder in workspace['folders'] if folder['name'] == 'qemu-source')
config = json.loads((ROOT / '.vscode/launch.json').read_text())['configurations'][1 if args.existing else 0]
for key in ('type', 'preLaunchTask', 'postDebugTask'):
    config.pop(key, None)


def expand(value):
    if isinstance(value, str):
        return value.replace('${workspaceFolder:qemu-source}', str(source)).replace('${workspaceFolder}', str(ROOT))
    if isinstance(value, list):
        return [expand(item) for item in value]
    if isinstance(value, dict):
        return {key: expand(item) for key, item in value.items()}
    return value


config = expand(config)
config['logging'] = {'engineLogging': True}
adapters = glob.glob(str(Path.home() / '.vscode/extensions/ms-vscode.cpptools-*/debugAdapters/bin/OpenDebugAD7'))
if not adapters:
    raise SystemExit('Install the VSCode C/C++ extension first')
process = subprocess.Popen([adapters[0]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=open(OUTPUT / 'runtime-dap.stderr', 'wb'))
messages = queue.Queue()
trace = []
sequence = 0
pending_status = None


def reader():
    try:
        while True:
            headers = {}
            while True:
                line = process.stdout.readline()
                if not line:
                    raise EOFError('Adapter exited')
                if line == b'\r\n':
                    break
                key, value = line.decode().split(':', 1)
                headers[key.lower()] = value.strip()
            messages.put(json.loads(process.stdout.read(int(headers['content-length']))))
    except Exception as error:
        messages.put({'reader_error': str(error)})


threading.Thread(target=reader, daemon=True).start()


def send(command, arguments):
    global sequence
    sequence += 1
    data = json.dumps(dict(seq=sequence, type='request', command=command, arguments=arguments)).encode()
    process.stdin.write(f'Content-Length: {len(data)}\r\n\r\n'.encode() + data)
    process.stdin.flush()
    return sequence


def until(predicate, seconds=60):
    deadline = time.monotonic() + seconds
    while True:
        message = messages.get(timeout=max(.1, deadline - time.monotonic()))
        trace.append(message)
        if 'reader_error' in message or (message.get('type') == 'response' and not message.get('success', True)):
            raise RuntimeError(message)
        if predicate(message):
            return message
        if time.monotonic() > deadline:
            raise TimeoutError('DAP operation timed out')


def request(command, arguments):
    number = send(command, arguments)
    return until(lambda message: message.get('request_seq') == number)


try:
    request('initialize', dict(adapterID='cppdbg', clientID='qemu-runtime-smoke', linesStartAt1=True,
                               columnsStartAt1=True, pathFormat='path', supportsRunInTerminalRequest=False))
    send('launch', config)
    until(lambda message: message.get('event') == 'initialized')
    send('configurationDone', {})
    stopped = until(lambda message: message.get('event') == 'stopped')
    thread = stopped['body']['threadId']
    frames = request('stackTrace', dict(threadId=thread, levels=5))['body']['stackFrames']
    main = next(frame for frame in frames if frame['name'].startswith('main'))
    assert main['source']['path'] == str(source / 'system/main.c'), main
    argc = request('evaluate', dict(expression='argc', frameId=main['id'], context='watch'))['body']['result']
    assert int(argc) > 1, argc
    request('next', dict(threadId=thread))
    stopped = until(lambda message: message.get('event') == 'stopped')
    request('continue', dict(threadId=stopped['body']['threadId']))
    wait_guest()
    print('QEMU main source breakpoint, argc inspection and single-step passed', flush=True)
    guest_command("curl -4 -fsSI --max-time 25 https://deb.debian.org/debian/ && printf 'persistent\\n' > /root/.qemu-runtime-smoke")
    beginning = len(trace)
    result = request('setFunctionBreakpoints', dict(breakpoints=[dict(name='qmp_query_status')]))
    assert all(item['verified'] for item in result['body']['breakpoints']), result
    # The following QMP query must execute only after an internal interrupt has
    # auto-resumed; an exposed Interrupt exception would leave it blocked.
    pending_status = subprocess.Popen([str(ROOT / 'dev.sh'), 'status'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stopped = until(lambda message: message.get('event') == 'stopped')
    assert stopped['body']['reason'] == 'breakpoint', stopped
    frames = request('stackTrace', dict(threadId=stopped['body']['threadId'], levels=5))['body']['stackFrames']
    assert any('qmp_query_status' in frame['name'] for frame in frames), frames
    assert not any('<PENDING>' in message.get('body', {}).get('output', '') for message in trace[beginning:])
    request('setFunctionBreakpoints', dict(breakpoints=[]))
    request('continue', dict(threadId=stopped['body']['threadId']))
    pending_status.communicate(timeout=20)
    assert pending_status.returncode == 0
    print('Live QMP breakpoint, stack trace and continue passed', flush=True)
    request('disconnect', dict(terminateDebuggee=True))
    process.wait(timeout=20)
    assert process.returncode == 0, (OUTPUT / 'runtime-dap.stderr').read_text()
    cli('stop')
    assert not json.loads(cli('status').stdout)['running']
    with (OUTPUT / 'rootfs.ext4').open('rb') as disk:
        disk.seek(1024 + 58)
        assert int.from_bytes(disk.read(2), 'little') & 1, 'Guest filesystem shutdown was not clean'
    cli('run')
    wait_guest()
    guest_command('test "$(cat /root/.qemu-runtime-smoke)" = persistent && rm /root/.qemu-runtime-smoke')
    cli('stop')
    print('Debian HTTPS, persistent writes and clean debugger shutdown passed', flush=True)
finally:
    if process.poll() is None:
        try:
            request('disconnect', dict(terminateDebuggee=True))
            process.wait(timeout=20)
        except Exception:
            process.terminate()
            process.wait(timeout=10)
    if pending_status and pending_status.poll() is None:
        pending_status.terminate()
        pending_status.wait(timeout=5)
    (OUTPUT / 'runtime-dap-smoke.json').write_text(json.dumps(trace, indent=2) + '\n')
    cli('stop')
