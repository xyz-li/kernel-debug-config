"""Exercise the shared UART transport and SSH argument boundary."""
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'guest'


class GuestTransportTests(unittest.TestCase):
    def test_console_has_independent_input_output_history_and_cleanup(self):
        with tempfile.TemporaryDirectory(prefix='fc-console-', dir='/tmp') as temporary:
            directory = Path(temporary)
            path = directory / 'console.socket'
            tty_file = directory / 'console.tty'
            log = directory / 'console.log'
            process = subprocess.Popen([sys.executable, str(ROOT / 'console.py'), 'serve', str(path),
                                        '--tty-file', str(tty_file), '--log', str(log)], stderr=subprocess.PIPE)
            slave = None
            try:
                deadline = time.monotonic() + 5
                while not tty_file.exists() or not tty_file.read_text().strip():
                    if process.poll() is not None:
                        self.fail('Console bridge exited early: ' + process.stderr.read().decode())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.01)
                slave = os.open(tty_file.read_text().strip(), os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                os.write(slave, b'guest booted\n')
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(3)
                    client.connect(str(path))
                    self.assertEqual(client.recv(4096), b'guest booted\n')
                    client.sendall(b'echo uart-input\n')
                    self.assertTrue(select.select([slave], [], [], 3)[0])
                    self.assertEqual(os.read(slave, 4096), b'echo uart-input\n')
                    os.write(slave, b'UART_OK\n')
                    self.assertEqual(client.recv(4096), b'UART_OK\n')
                # A subsequent console gets the boot history without restarting the VM.
                deadline = time.monotonic() + 3
                while True:
                    with socket.socket(socket.AF_UNIX) as client:
                        client.settimeout(1)
                        client.connect(str(path))
                        data = client.recv(4096)
                    if data:
                        self.assertEqual(data, b'guest booted\nUART_OK\n')
                        break
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.01)
                self.assertEqual(log.read_bytes(), b'guest booted\nUART_OK\n')
            finally:
                if slave is not None:
                    os.close(slave)
                process.terminate()
                _, errors = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, errors.decode())
            self.assertFalse(path.exists())
            self.assertFalse(tty_file.exists())


    def test_ssh_exec_preserves_arguments_and_uses_dedicated_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            identity = directory / "private key with ' quote"
            known_hosts = directory / 'known hosts'
            identity.write_text('fixture\n')
            known_hosts.write_text('fixture\n')
            fake_ssh = directory / 'ssh'
            fake_ssh.write_text('#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            fake_ssh.chmod(0o755)
            arguments = ['python3', '-c', 'import sys; print(sys.argv[1:])', '', 'two words', "a'b", '$HOME; false', 'line\none']
            result = subprocess.run(['bash', '-c', 'source "$1"; shift; guest_ssh "$@"',
                                     'ssh-test', str(ROOT / 'ssh.sh'), *arguments], check=True, capture_output=True,
                                    text=True, env=dict(os.environ, PATH=str(directory) + os.pathsep + os.environ['PATH'],
                                    SSH_IDENTITY=str(identity), SSH_KNOWN_HOSTS=str(known_hosts), SSH_PORT='2222', GUEST_IP='172.16.51.2'))
            actual = json.loads(result.stdout)
            self.assertEqual(actual[actual.index('-i') + 1], str(identity))
            self.assertIn('IdentityAgent=none', actual)
            self.assertIn('StrictHostKeyChecking=yes', actual)
            self.assertEqual(actual[-2], 'root@172.16.51.2')
            executed = subprocess.run(['sh', '-c', actual[-1]], check=True, capture_output=True, text=True)
            self.assertEqual(executed.stdout.strip(), repr(arguments[3:]))


    def test_ssh_keys_with_comments_are_reused_and_host_key_is_pinned(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            env = dict(os.environ, WORKDIR=str(directory), SSH_IDENTITY=str(directory / 'ssh/client key'),
                       SSH_HOST_KEY=str(directory / 'ssh/guest host key'), SSH_KNOWN_HOSTS=str(directory / 'ssh/known_hosts'),
                       GUEST_IP='172.16.51.2', SSH_PORT='2222')
            command = ['bash', '-c', 'set -e; fail() { echo "$*" >&2; exit 1; }; source "$1"; ensure_ssh_keys',
                       'keys-test', str(ROOT / 'ssh.sh')]
            subprocess.run(command, env=env, check=True, capture_output=True)
            identity = Path(env['SSH_IDENTITY'])
            original = identity.read_bytes()
            subprocess.run(command, env=env, check=True, capture_output=True)
            self.assertEqual(identity.read_bytes(), original)
            self.assertEqual(identity.stat().st_mode & 0o777, 0o600)
            host_key = ' '.join(Path(env['SSH_HOST_KEY'] + '.pub').read_text().split()[:2])
            self.assertIn(f'[172.16.51.2]:2222 {host_key}', Path(env['SSH_KNOWN_HOSTS']).read_text())
            Path(str(identity) + '.pub').write_text('ssh-ed25519 invalid\n')
            result = subprocess.run(command, env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'Private/public key mismatch', result.stderr)


if __name__ == '__main__':
    unittest.main()
