"""Check that terminating a bridge cannot leave its Delve child or lock behind."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SERVER = Path(__file__).resolve().parents[1] / 'dlv_server.py'


class DelveLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        fake = self.root / 'dlv'
        fake.write_text('''#!/usr/bin/env python3
import os, pathlib, signal, time
marker = pathlib.Path(os.environ['TEST_DLV_MARKER'])
def stopped(*_):
    marker.write_text('detached')
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stopped)
print('fake-delve-ready', flush=True)
while True:
    time.sleep(10)
''')
        fake.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ['PATH'],
                        DEBUG_DLV_STDIN='1', TEST_DLV_MARKER=str(self.root / 'detached'))

    def start(self):
        process = subprocess.Popen([sys.executable, str(SERVER), str(self.root), '38697', 'dap'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=self.env, text=True)
        self.addCleanup(self.close, process)
        self.assertEqual(process.stdout.readline().strip(), 'fake-delve-ready')
        return process

    @staticmethod
    def close(process):
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        process.stdout.close()
        process.stderr.close()

    def test_bridge_eof_detaches_and_allows_the_next_session(self):
        for _ in range(2):
            marker = self.root / 'detached'
            marker.unlink(missing_ok=True)
            process = self.start()
            process.stdin.close()
            self.assertEqual(process.wait(timeout=10), 0)
            self.assertEqual(marker.read_text(), 'detached')

    def test_task_sigterm_detaches_its_child(self):
        process = self.start()
        process.terminate()
        self.assertEqual(process.wait(timeout=10), 0)
        self.assertEqual((self.root / 'detached').read_text(), 'detached')

    def test_an_active_session_cannot_be_replaced(self):
        active = self.start()
        conflict = subprocess.run([sys.executable, str(SERVER), str(self.root), '38697', 'dap'],
                                  input='', capture_output=True, text=True, env=self.env, timeout=5)
        self.assertNotEqual(conflict.returncode, 0)
        self.assertIn('Another Delve session is active', conflict.stderr)
        self.assertIsNone(active.poll())


if __name__ == '__main__':
    unittest.main()
