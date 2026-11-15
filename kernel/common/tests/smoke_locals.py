#!/usr/bin/env python3
"""Inspect real ICMP locals before and after assignment in a disposable VM."""
import argparse
import copy
import json
from pathlib import Path
import re
import subprocess
import sys
import time

COMMON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMMON))
from isolated_apple import IsolatedApple
from apple import AppleEnvironment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--artifacts', type=Path, help='Use independent kernel artifacts instead of the active environment')
args = parser.parse_args()
root = COMMON.parent / 'apple-container'
source = Path(json.loads((root / 'output/config.local.json').read_text())['source'])
config = copy.deepcopy(json.loads((root / '.vscode/launch.json').read_text())['configurations'][1])
artifacts = args.artifacts.resolve() if args.artifacts else None
if artifacts is None:
    environment = AppleEnvironment()
    record = root / 'output/source.local.json'
    if not record.exists() or not environment.matching_build(json.loads(record.read_text())):
        raise SystemExit('Build the selected debug_sources with dev.sh build before checking local variables')
test = IsolatedApple(root, source, artifacts=artifacts)
process = console = None
try:
    test.prepare(config)
    source_lines = (source / 'net/ipv4/ping.c').read_text().splitlines()
    ready_line = next(number for number, line in enumerate(source_lines, 1) if 'tos = get_rttos(&ipc, inet);' in line)
    commands = test.output / 'locals.gdb'
    commands.write_text('''set pagination off
set confirm off
file /output/vmlinux
target remote /cache/run/gdb.sock
python
import json
snapshots={}
def snapshot(stage):
    frame=gdb.newest_frame()
    for unused in range(8):
        if frame is None: raise gdb.GdbError('No ping_v4_sendmsg frame')
        if frame.name() == 'ping_v4_sendmsg':
            frame.select()
            break
        frame=frame.older()
    values={}
    for name in ['free','saddr','daddr','faddr','tos','err','rt']:
        try:
            value=gdb.parse_and_eval(name)
            values[name]={'value':str(value),'optimized_out':value.is_optimized_out}
        except gdb.error as error:
            values[name]={'error':str(error),'optimized_out':True}
    snapshots[stage]=values
    with open('/output/locals-snapshot.json','w') as output: json.dump(snapshots,output,indent=2)
end
hbreak ping_v4_sendmsg
continue
python snapshot('entry')
''' + f'hbreak /cache/source/net/ipv4/ping.c:{ready_line}\n' + '''continue
next
python snapshot('after_assignment')
delete breakpoints
detach
quit
''')
    with (test.output / 'locals-gdb.log').open('w') as output:
        process = subprocess.Popen(test.exec_command('gdb-multiarch', '-q', '-batch', '-x', '/output/locals.gdb'),
                                   stdout=output, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 70
        log = test.output / 'console.log'
        while 'KERNEL_DEBUG_READY' not in log.read_text(errors='replace'):
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError((test.output / 'locals-gdb.log').read_text())
            time.sleep(.1)
        console = subprocess.Popen(test.exec_command('python3', '/scripts/kernel/qemu.py', 'console', interactive=True),
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        console.stdin.write(b"ping -c 1 -W 15 10.0.2.2; result=$?; printf '\\nLOCALS_PING_%s\\n' \"$result\"\r")
        console.stdin.flush()
        process.wait(timeout=30)
        if process.returncode:
            raise RuntimeError((test.output / 'locals-gdb.log').read_text())
        deadline = time.monotonic() + 30
        while not re.search(r'\nLOCALS_PING_0\n', log.read_text(errors='replace')):
            if time.monotonic() > deadline:
                raise RuntimeError(log.read_text(errors='replace')[-4000:])
            time.sleep(.1)
        console.stdin.write(b'\x1d'); console.stdin.flush(); console.communicate(timeout=10)
    snapshots = json.loads((test.output / 'locals-snapshot.json').read_text())
    print(json.dumps(snapshots, indent=2), flush=True)
    profile = (artifacts or root / 'output') / 'debug-profile.json'
    selected = json.loads(profile.read_text())['sources'] if profile.exists() else []
    if 'net/ipv4/ping.c' in selected:
        for name in ('free', 'saddr', 'daddr', 'faddr', 'tos', 'rt'):
            assert not snapshots['after_assignment'][name]['optimized_out'], (name, snapshots)
    print('ICMP breakpoint, assigned local variables and guest ping passed', flush=True)
finally:
    if console and console.poll() is None:
        console.terminate(); console.wait(timeout=5)
    if process and process.poll() is None:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
    test.cleanup()
