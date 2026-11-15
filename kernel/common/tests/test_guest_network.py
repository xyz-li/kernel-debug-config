"""Check network modes and visible failures without changing the host network."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GuestNetworkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for path in ('etc/kernel-debug', 'proc', 'bin'):
            (self.root / path).mkdir(parents=True)
        (self.root / 'proc/uptime').write_text('1.00 0.00\n')
        shutil.copy2(ROOT / 'guest-udhcpc', self.root / 'etc/kernel-debug/udhcpc')
        stub = '''#!/usr/bin/env python3
import json,os,subprocess,sys
from pathlib import Path
arguments=sys.argv[1:]
with open(os.environ['NETWORK_TEST_LOG'],'a') as log:
    log.write(json.dumps([Path(sys.argv[0]).name,*arguments])+'\\n')
if Path(sys.argv[0]).name=='ip' and arguments[:2]==['link','show'] and os.environ.get('FAIL_INTERFACE'):
    raise SystemExit(1)
if Path(sys.argv[0]).name=='busybox' and arguments[0]=='udhcpc':
    if os.environ.get('FAIL_DHCP'): raise SystemExit(1)
    if os.environ.get('SKIP_CALLBACK'): raise SystemExit(0)
    callback=arguments[arguments.index('-s')+1]
    environment=dict(os.environ,interface='eth0',ip='10.0.2.15',subnet='255.255.255.0',router='10.0.2.2',dns='10.0.2.3')
    raise SystemExit(subprocess.run(['/bin/sh',callback,'bound'],env=environment).returncode)
'''
        for name in ('ip', 'busybox'):
            path = self.root / 'bin' / name
            path.write_text(stub)
            path.chmod(0o755)
        self.log = self.root / 'commands.jsonl'
        self.environment = dict(os.environ, KERNEL_DEBUG_ROOT=str(self.root), NETWORK_TEST_LOG=str(self.log),
                                PATH=str(self.root / 'bin') + os.pathsep + os.environ['PATH'])

    def run_network(self, mode='static', **extra):
        return subprocess.run(['/bin/sh', str(ROOT / 'guest-network')], text=True, capture_output=True,
                              env=dict(self.environment, KERNEL_NET_MODE=mode, **extra))

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def status(self):
        return (self.root / 'run/kernel-debug/network.status').read_text()

    def test_static_network_needs_no_dhcp_or_python_and_preserves_ipv6(self):
        result = self.run_network()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('KERNEL_DEBUG_NETWORK_READY mode=static', result.stdout)
        self.assertIn('state=ready', self.status())
        self.assertEqual((self.root / 'etc/resolv.conf').read_text(), 'nameserver 10.0.2.3\n')
        commands = self.commands()
        self.assertTrue(all(command[0] == 'ip' for command in commands))
        self.assertIn(['ip', '-4', 'address', 'replace', '10.0.2.15/24', 'broadcast', '+', 'dev', 'eth0'], commands)
        self.assertTrue(all(command[1] == '-4' for command in commands if 'flush' in command))

    def test_dhcp_waits_for_a_successful_configuration_callback(self):
        result = self.run_network('dhcp')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('KERNEL_DEBUG_NETWORK_READY mode=dhcp', result.stdout)
        self.assertIn('state=ready', self.status())
        self.assertEqual((self.root / 'run/kernel-debug/dhcp.bound').read_text(), '10.0.2.15\n')
        self.assertEqual((self.root / 'etc/resolv.conf').read_text(), 'nameserver 10.0.2.3\n')

    def test_dhcp_timeout_and_callback_failure_are_not_reported_ready(self):
        for settings, reason in [({'FAIL_DHCP': '1'}, 'dhcp-timeout'),
                                 ({'SKIP_CALLBACK': '1'}, 'dhcp-callback-failed')]:
            with self.subTest(reason=reason):
                result = self.run_network('dhcp', **settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('NETWORK_READY', result.stdout)
                self.assertIn('reason=' + reason, self.status())
                self.assertIn('KERNEL_DEBUG_NETWORK_FAILED', result.stderr)

    def test_missing_interface_is_visible(self):
        result = self.run_network(FAIL_INTERFACE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('reason=interface-unavailable', self.status())
        self.assertIn('KERNEL_DEBUG_NETWORK_FAILED', result.stderr)

    def test_boot_configuration_can_select_dhcp_and_explicit_environment_wins(self):
        (self.root / 'etc/kernel-debug/network.conf').write_text('KERNEL_NET_MODE=dhcp\n')
        result = subprocess.run(['/bin/sh', str(ROOT / 'guest-network')], text=True, capture_output=True,
                                env=self.environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('mode=dhcp', self.status())
        result = self.run_network('static')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('mode=static', self.status())

    def test_disabled_network_only_leaves_loopback_up(self):
        result = self.run_network('off')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('state=disabled', self.status())
        self.assertNotIn('NETWORK_READY', result.stdout)
        self.assertFalse(any(command[0] == 'busybox' for command in self.commands()))
        self.assertFalse(any('address' in command or 'route' in command for command in self.commands()))


if __name__ == '__main__':
    unittest.main()
