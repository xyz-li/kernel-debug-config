#!/usr/bin/env python3
"""Boot an isolated Guest and verify nftables, both iptables backends and real NAT."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

COMMON = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(COMMON))
from apple import AppleEnvironment
from isolated_apple import IsolatedApple

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--artifacts', type=Path, required=True)
parser.add_argument('--install-tools', action='store_true', help='Install firewall tools into a disposable Debian copy')
args = parser.parse_args()
environment = AppleEnvironment()
test = IsolatedApple(environment.directory, environment.source, artifacts=args.artifacts.resolve())
console = None


def command(text, timeout=45):
    log = test.output / 'console.log'
    start = len(log.read_text(errors='replace'))
    script = '/bin/sh -ec ' + shlex.quote(text) + '; result=$?; printf "\\nNETFILTER_RESULT_%s\\n" "$result"\r'
    console.stdin.write(script.encode()); console.stdin.flush()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        output = log.read_text(errors='replace')[start:]
        match = re.search(r'\nNETFILTER_RESULT_(\d+)\n', output)
        if match:
            if int(match[1]): raise RuntimeError(output[-7000:])
            print(output[-6000:], flush=True)
            return
        time.sleep(.1)
    raise RuntimeError('Guest command timed out:\n' + output[-7000:])


try:
    test.prepare({'pipeTransport': {}, 'customLaunchSetupCommands': []}, paused=False)
    deadline = time.monotonic() + 90
    log = test.output / 'console.log'
    while 'KERNEL_DEBUG_READY' not in log.read_text(errors='replace'):
        if time.monotonic() > deadline: raise RuntimeError(log.read_text(errors='replace')[-7000:])
        time.sleep(.1)
    console = subprocess.Popen(test.exec_command('python3', '/scripts/kernel/qemu.py', 'console', interactive=True),
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if args.install_tools:
        command('apt-get update && apt-get install -y --no-install-recommends iptables nftables', timeout=180)
    command('uname -r; nft --version; iptables-legacy --version; iptables-nft --version; '
            'modprobe nf_tables; modprobe iptable_filter; modprobe iptable_nat; modprobe ip6table_filter; modprobe veth; '
            'ip6tables-legacy -L; ip6tables-nft -L; ping -c 1 -W 3 10.0.2.2; free -m; lsmod')
    command('nft add table inet debug_filter; '
            "nft 'add chain inet debug_filter output { type filter hook output priority 0; policy accept; }'; "
            'nft add rule inet debug_filter output ip daddr 10.0.2.2 icmp type echo-request counter drop; '
            'if ping -c 1 -W 1 10.0.2.2; then exit 1; fi; '
            "nft list chain inet debug_filter output | grep -E 'packets [1-9]'; "
            'nft delete table inet debug_filter; ping -c 1 -W 3 10.0.2.2')
    command('iptables-legacy -I OUTPUT 1 -d 10.0.2.2 -p icmp -j DROP; '
            'if ping -c 1 -W 1 10.0.2.2; then exit 1; fi; iptables-legacy -L OUTPUT -nv; '
            'iptables-legacy -D OUTPUT -d 10.0.2.2 -p icmp -j DROP; '
            'iptables-nft -N DEBUG_TEST; iptables-nft -A DEBUG_TEST -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT; '
            'iptables-nft -F DEBUG_TEST; iptables-nft -X DEBUG_TEST')
    command('ip netns add debug_ns; ip link add debug_host type veth peer name debug_guest; '
            'ip link set debug_guest netns debug_ns; ip addr add 172.30.0.1/24 dev debug_host; ip link set debug_host up; '
            'ip -n debug_ns addr add 172.30.0.2/24 dev debug_guest; ip -n debug_ns link set lo up; '
            'ip -n debug_ns link set debug_guest up; ip -n debug_ns route add default via 172.30.0.1; '
            'sysctl -w net.ipv4.ip_forward=1; '
            'iptables-legacy -t nat -A POSTROUTING -s 172.30.0.0/24 -o eth0 -j MASQUERADE; '
            'ip netns exec debug_ns ping -c 1 -W 3 10.0.2.2; iptables-legacy -t nat -L POSTROUTING -nv; '
            'iptables-legacy -t nat -D POSTROUTING -s 172.30.0.0/24 -o eth0 -j MASQUERADE; '
            'nft add table ip debug_nat; '
            "nft 'add chain ip debug_nat postrouting { type nat hook postrouting priority 100; policy accept; }'; "
            'nft add rule ip debug_nat postrouting ip saddr 172.30.0.0/24 oifname eth0 counter masquerade; '
            'ip netns exec debug_ns ping -c 1 -W 3 10.0.2.2; '
            "nft list chain ip debug_nat postrouting | grep -E 'packets [1-9]'; "
            'nft delete table ip debug_nat; ip link del debug_host; ip netns del debug_ns')
    command('curl -4 -fsSI --max-time 30 http://deb.debian.org/debian/; cat /proc/meminfo | head -3')
    (test.output / 'netfilter-results.json').write_text(json.dumps(dict(nft_filter=True, iptables_legacy=True,
        iptables_nft=True, ipv6=True, namespaces=True, nft_nat=True, iptables_nat=True, http=True), indent=2)+'\n')
    print('Isolated filtering, counters, iptables compatibility and namespace NAT passed', flush=True)
finally:
    if console and console.poll() is None:
        console.stdin.write(b'\x1d'); console.stdin.flush()
        console.communicate(timeout=10)
    test.cleanup()
