#!/usr/bin/env python3
"""Boot Debian twice and verify networking, apt, persistent files and clean shutdown."""
import json
from pathlib import Path
import re
import shlex
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[2] / 'debian-container'
OUTPUT = ROOT / 'output'
CONSOLE = OUTPUT / 'console.log'
console = None
sequence = 0


def cli(command, check=True):
    return subprocess.run([str(ROOT / 'dev.sh'), command], check=check, text=True, capture_output=True, timeout=30)


def status():
    return json.loads(cli('status').stdout)


def boot():
    global console
    print(cli('boot').stdout.strip(), flush=True)
    deadline = time.monotonic() + 60
    while 'KERNEL_DEBUG_READY' not in CONSOLE.read_text(errors='replace'):
        if time.monotonic() > deadline:
            raise RuntimeError(CONSOLE.read_text(errors='replace')[-5000:])
        time.sleep(.1)
    console = subprocess.Popen([str(ROOT / 'dev.sh'), 'console'], stdin=subprocess.PIPE,
                               stdout=open(OUTPUT / 'persistence-console.log', 'ab'), stderr=subprocess.PIPE)


def guest(command, timeout=30):
    global sequence
    sequence += 1
    prefix = 'ROOTFS_RESULT_' + str(sequence) + '_'
    before = len(CONSOLE.read_text(errors='replace'))
    line = '/bin/sh -ec ' + shlex.quote(command) + '; result=$?; printf "\\n' + prefix + '%s\\n" "$result"\r'
    console.stdin.write(line.encode())
    console.stdin.flush()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = CONSOLE.read_text(errors='replace')[before:]
        match = re.search(r'\n' + prefix + r'(\d+)\n', text)
        if match:
            if int(match[1]):
                raise RuntimeError(text[-6000:])
            return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
        if console.poll() is not None:
            raise RuntimeError('Guest console exited: ' + console.stderr.read().decode())
        time.sleep(.1)
    raise RuntimeError('Guest command timed out:\n' + text[-6000:])


def disconnect_console():
    global console
    if console and console.poll() is None:
        console.stdin.write(b'\x1d')
        console.stdin.flush()
        console.communicate(timeout=10)
    console = None


def clean_stop():
    disconnect_console()
    print(cli('stop').stdout.strip(), flush=True)
    assert not status()['running']
    with open(OUTPUT / 'rootfs.ext4', 'rb') as disk:
        disk.seek(1024 + 58)
        assert int.from_bytes(disk.read(2), 'little') & 1, 'Root filesystem did not shut down cleanly'


if status()['running']:
    raise SystemExit('Stop the Debian guest before this test; it must not interrupt an active user session.')
token = uuid.uuid4().hex
try:
    boot()
    versions = guest('cat /etc/os-release; uname -r; cat /proc/mounts | grep " / "; free -m')
    assert 'Debian GNU/Linux 13' in versions and ' ext4 ' in versions, versions
    memory = guest("awk '/MemTotal:|MemAvailable:/{print}' /proc/meminfo")
    print('Debian disk boot at 1 CPU / 256 MiB passed', flush=True)
    network = guest("ip -4 addr show eth0; ip route; ping -c 1 -W 3 10.0.2.2; getent ahostsv4 deb.debian.org; curl -4 -fsSI --max-time 25 https://deb.debian.org/debian/", timeout=45)
    assert 'inet 10.0.2.15/24' in network and '200' in network, network
    print('DHCP, gateway ping, DNS and external HTTPS passed', flush=True)
    print('Installing a small Debian package to verify apt and persistence', flush=True)
    guest('apt-get -o Acquire::Retries=2 update && apt-get install -y --no-install-recommends netcat-openbsd && apt-get clean && rm -rf /var/lib/apt/lists/*', timeout=240)
    guest(f'printf "{token}\\n" > /root/.kernel-persistence-test; printf "{token}\\n" > /etc/kernel-debug/persistence-test; command -v nc')
    # No manual sync: dev.sh stop must arrange it through the guest control port.
    clean_stop()
    boot()
    guest(f'test "$(cat /root/.kernel-persistence-test)" = {token}; test "$(cat /etc/kernel-debug/persistence-test)" = {token}; dpkg-query -W netcat-openbsd; command -v nc; ping -c 1 -W 3 10.0.2.2')
    print('Root files, /etc configuration and installed package survived restart', flush=True)
    guest('fstrim / || true')
    clean_stop()
    record = dict(distro='Debian 13', memory='256M', cpus=1, network=True, dns=True, https=True,
                  apt=True, files_persist=True, package_persists=True, clean_shutdown=True,
                  memory_observation=memory)
    (OUTPUT / 'persistence-smoke.json').write_text(json.dumps(record, indent=2) + '\n')
finally:
    disconnect_console()
    cli('stop', check=False)
print('Persistent Debian guest verification passed', flush=True)
