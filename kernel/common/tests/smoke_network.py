#!/usr/bin/env python3
"""Compare Alpine startup networking in disposable containers; preserve the user's VM."""
import fcntl
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

COMMON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMMON))
from apple import AppleEnvironment
from manifest import file_hash, write_json

ENVIRONMENT = AppleEnvironment()
ROOT = ENVIRONMENT.directory
SOURCE = ROOT / 'output'
OUTPUT = SOURCE / 'network-smoke'
OUTPUT.mkdir(exist_ok=True)
WORKFLOW_LOCK = open(OUTPUT / 'workflow.lock', 'a')
fcntl.flock(WORKFLOW_LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
IMAGE = ENVIRONMENT.environment['KERNEL_BUILDER_IMAGE']


def run(arguments, timeout=90):
    return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=timeout)


def prepare(directory, modules=False):
    directory.mkdir(exist_ok=True)
    for name in ('Image', 'vmlinux', 'kernel.config', 'kernel.json', 'kernel.release'):
        target = directory / name
        target.unlink(missing_ok=True)
        os.link(SOURCE / name, target)
    if modules:
        shutil.copytree(SOURCE / 'modules', directory / 'modules', symlinks=True,
                        copy_function=os.link, dirs_exist_ok=False)


def baseline_archive(directory):
    # Add timing markers around the original networking without changing its behavior.
    archive = gzip.decompress((SOURCE / 'initramfs.cpio.gz').read_bytes())
    output = bytearray()
    offset = 0
    changed = False
    while offset + 110 <= len(archive):
        header = bytearray(archive[offset:offset + 110])
        assert header[:6] == b'070701'
        size = int(header[54:62], 16)
        namesize = int(header[94:102], 16)
        name = archive[offset + 110:offset + 110 + namesize]
        offset = (offset + 110 + namesize + 3) // 4 * 4
        data = archive[offset:offset + size]
        offset = (offset + size + 3) // 4 * 4
        if name.rstrip(b'\0').removeprefix(b'./') == b'etc/kernel-debug/rcS':
            script = data.decode()
            begin = 'if ip link show eth0'
            end = "printf '\\nKERNEL_DEBUG_READY"
            if begin not in script:
                begin = 'if ! /etc/kernel-debug/network; then'
                script = script.replace(begin, 'if ! KERNEL_NET_MODE=dhcp /etc/kernel-debug/network; then')
                begin = 'if ! KERNEL_NET_MODE=dhcp /etc/kernel-debug/network; then'
            if begin not in script or end not in script:
                raise ValueError('Baseline startup script has no supported network entry point')
            script = script.replace(begin, 'read -r stamp unused < /proc/uptime\nprintf "BASELINE_NETWORK_BEGIN uptime=%s\\n" "$stamp"\n' + begin)
            script = script.replace(end, 'read -r stamp unused < /proc/uptime\nprintf "BASELINE_NETWORK_END uptime=%s\\n" "$stamp"\n' + end)
            data = script.encode()
            header[54:62] = f'{len(data):08x}'.encode()
            changed = True
        output.extend(header)
        output.extend(name)
        output.extend(b'\0' * (-len(output) % 4))
        output.extend(data)
        output.extend(b'\0' * (-len(output) % 4))
        if name == b'TRAILER!!!\0':
            break
    assert changed
    (directory / 'initramfs.cpio.gz').write_bytes(gzip.compress(output, compresslevel=1, mtime=0))
    record = json.loads((SOURCE / 'rootfs.json').read_text())
    record['archive'] = file_hash(directory / 'initramfs.cpio.gz')
    write_json(directory / 'rootfs.json', record)


def package(directory):
    image = ENVIRONMENT.environment['ROOTFS_BUILDER_IMAGE']
    command = ['container', 'run', '--rm', '--cpus', '1', '--memory', '1G',
               '--env', 'ROOTFS_IMAGE_ID=' + ENVIRONMENT.image_id(image)]
    for source, target in ((directory, '/output'), (COMMON, '/scripts/kernel'), (ROOT / 'rootfs-overlay', '/overlay')):
        command += ENVIRONMENT.mount(source, target, readonly=target != '/output')
    print(run([*command, image, '/bin/sh', '/scripts/kernel/build-rootfs.sh']).stdout.strip(), flush=True)


class Guest:
    def __init__(self, directory):
        self.directory = directory
        self.name = 'kernel-net-test-' + uuid.uuid4().hex[:8]
        self.console = None
        self.sequence = 0

    def inside(self, *arguments):
        return run(['container', 'exec', self.name, *arguments])

    def boot(self):
        command = ['container', 'run', '--rm', '--detach', '--init', '--name', self.name,
                   '--cpus', '1', '--memory', '1G', '--env', 'CPUS=1', '--env', 'MEMORY=256M',
                   '--env', 'KERNEL_SESSION_NAME=' + self.name,
                   '--label', 'kernel-debug.network-test=' + str(ROOT)]
        command += ENVIRONMENT.mount(self.directory, '/output')
        command += ENVIRONMENT.mount(COMMON, '/scripts/kernel', readonly=True)
        run([*command, IMAGE, 'sleep', 'infinity'])
        self.inside('python3', '/scripts/kernel/qemu.py', 'run')
        deadline = time.monotonic() + 70
        while 'KERNEL_DEBUG_READY' not in self.log():
            if time.monotonic() > deadline:
                raise RuntimeError(self.log()[-5000:])
            time.sleep(.1)
        self.console = subprocess.Popen(['container', 'exec', '--interactive', self.name,
                                         'python3', '/scripts/kernel/qemu.py', 'console'],
                                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def log(self):
        return (self.directory / 'console.log').read_text(errors='replace')

    def command(self, command):
        import shlex
        self.sequence += 1
        marker = 'NETWORK_TEST_' + str(self.sequence) + '_'
        before = len(self.log())
        line = '/bin/sh -ec ' + shlex.quote(command) + '; result=$?; printf "\\n' + marker + '%s\\n" "$result"\r'
        self.console.stdin.write(line.encode())
        self.console.stdin.flush()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            output = self.log()[before:]
            match = re.search(r'\n' + marker + r'(\d+)\n', output)
            if match:
                if int(match[1]):
                    raise RuntimeError(output[-5000:])
                return output
            time.sleep(.1)
        raise RuntimeError('Guest command timed out:\n' + output[-5000:])

    def cleanup(self):
        if self.console and self.console.poll() is None:
            self.console.stdin.write(b'\x1d')
            self.console.stdin.flush()
            self.console.communicate(timeout=10)
        inspection = subprocess.run(['container', 'inspect', self.name], capture_output=True, text=True)
        if inspection.returncode:
            return
        record = json.loads(inspection.stdout)[0]
        if record['configuration'].get('labels', {}).get('kernel-debug.network-test') != str(ROOT):
            raise RuntimeError('Unexpected test container owner')
        self.inside('python3', '/scripts/kernel/qemu.py', 'stop')
        run(['container', 'stop', self.name])


def timing(log, begin, end):
    started = re.search(begin + r'.*uptime=([\d.]+)', log)
    finished = re.search(end + r'.*uptime=([\d.]+)', log)
    assert started and finished, log[-3000:]
    return round(float(finished[1]) - float(started[1]), 3)


baseline = OUTPUT / 'baseline'
candidate = OUTPUT / 'candidate'
if candidate.exists():
    # Remove only prior test artifacts; these contain hardlinks, never the original files.
    shutil.rmtree(candidate)
prepare(baseline)
prepare(candidate, modules=True)
baseline_archive(baseline)
package(candidate)
result = {}
guest = Guest(baseline)
try:
    guest.boot()
    guest.command('ip -4 addr show eth0; ping -c 1 -W 3 10.0.2.2')
    result['original_dhcp_seconds'] = timing(guest.log(), 'BASELINE_NETWORK_BEGIN', 'BASELINE_NETWORK_END')
finally:
    guest.cleanup()
guest = Guest(candidate)
try:
    guest.boot()
    result['static_seconds'] = timing(guest.log(), 'KERNEL_DEBUG_NETWORK_BEGIN', 'KERNEL_DEBUG_NETWORK_READY')
    guest.command('grep -q "state=ready" /run/kernel-debug/network.status; grep -q "mode=static" /run/kernel-debug/network.status; ip -4 addr show eth0 | tee /run/address; grep -q "brd 10.0.2.255" /run/address; ip route; ping -c 1 -W 3 10.0.2.2; nslookup deb.debian.org; curl -4 -fsSI --max-time 20 http://deb.debian.org/debian/')
    print('Static IPv4, default route, DNS and external HTTP passed', flush=True)
    guest.command('ip -6 addr add fe80::1234/64 dev eth0; /etc/kernel-debug/network; /etc/kernel-debug/network; test "$(ip -4 route show default | wc -l)" -eq 1; ip -6 addr show eth0 | grep -q fe80::1234')
    guest.command('KERNEL_NET_MODE=dhcp /etc/kernel-debug/network; grep -q "mode=dhcp" /run/kernel-debug/network.status; ping -c 1 -W 3 10.0.2.2; ip -6 addr show eth0 | grep -q fe80::1234')
    print('Idempotent setup, DHCP option and preservation of IPv6 passed', flush=True)
    guest.command('if KERNEL_NET_IFACE=missing /etc/kernel-debug/network; then exit 1; fi; grep -q "state=failed" /run/kernel-debug/network.status; /etc/kernel-debug/network')
    guest.command('ps -e -o comm= > /run/processes; if grep -Eq "^(udhcpc|python3)$" /run/processes; then exit 1; fi; cat /run/processes')
    print('Visible network failure and absence of DHCP/Python daemons passed', flush=True)
    result.update(static=True, dhcp=True, ipv6_preserved=True, dns=True, http=True, failure_visible=True,
                  no_network_daemon=True, original_vm_preserved=True)
finally:
    guest.cleanup()
write_json(OUTPUT / 'results.json', result)
print(json.dumps(result, indent=2), flush=True)
