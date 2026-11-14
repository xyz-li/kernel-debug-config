"""Check Firecracker's Guest mode selection independently of the Host."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GuestModeTests(unittest.TestCase):
    def test_explicit_mode_overrides_env_file_and_invalid_modes_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'config.sh').write_bytes((ROOT / 'config.sh').read_bytes())
            (directory / '.env').write_text('GUEST_MODE=liquidmetal\n')
            for mode in ('liquidmetal', 'serial', 'ssh', 'invalid'):
                result = subprocess.run(['bash', '-c', 'set -e; source "$1"; printf "%s" "$GUEST_MODE"',
                                         'mode-test', str(directory / 'config.sh')], capture_output=True, text=True,
                                        env=dict(os.environ, FC_GUEST_MODE=mode))
                if mode == 'invalid':
                    self.assertNotEqual(result.returncode, 0)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, mode)


if __name__ == '__main__':
    unittest.main()
