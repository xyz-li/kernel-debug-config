"""Check CH-specific boot requirements, downloads and the GDB inferior wrapper."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ch_guest', ROOT / 'guest.py')
guest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guest)


def configuration(directory):
    result = subprocess.run(['bash', '-c', 'source "$1"; python3 -c "import json,os; print(json.dumps(dict(os.environ)))"',
                             'config-test', str(ROOT / 'config.sh')], check=True, capture_output=True, text=True,
                            env=dict(os.environ, WORKDIR=str(directory), CH_GUEST_MODE='serial'))
    return json.loads(result.stdout)


class GuestTests(unittest.TestCase):
    def test_macos_transport_preserves_shell_arguments_and_selected_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory)
            for name, script in {
                'uname': '#!/bin/sh\nprintf "Darwin\\n"\n',
                'container': '#!/usr/bin/env python3\nimport json,sys; print(json.dumps(sys.argv[1:]))\n',
            }.items():
                (tools / name).write_text(script)
                (tools / name).chmod(0o755)
            arguments = ['exec', 'sh', '-c', 'printf "%s" "$1"', 'argv0', '', "a'b", '$HOME; false', 'line\none']
            result = subprocess.run(['bash', str(ROOT / 'dev.sh'), '--mode', 'ssh', *arguments],
                                    check=True, capture_output=True, text=True,
                                    env=dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH']))
            actual = json.loads(result.stdout)
            encoded = next(a.split('=', 1)[1] for a in actual if a.startswith('CH_ARGS_BASE64='))
            self.assertEqual(json.loads(base64.b64decode(encoded)), arguments)
            self.assertIn('CH_GUEST_MODE=ssh', actual)
            self.assertNotIn('-it', actual)

    def test_ch_boot_uses_pl011_pci_and_independent_run_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            env = configuration(directory)
            args = guest.arguments(env)
            self.assertIn('console=ttyAMA0 root=/dev/vda rw rootwait nokaslr panic=1', args)
            self.assertNotIn('pci=off', ' '.join(args))
            self.assertIn(f'path={directory}/rootfs-run.ext4,image_type=raw', args)
            self.assertNotIn(env['BASE_ROOTFS'], args)
            self.assertNotIn('--gdb', args)
            env.update(ENABLE_NETWORK='0', GUEST_DEBUG='1', VCPUS='4')
            args = guest.arguments(env)
            self.assertNotIn('--net', args)
            self.assertIn('boot=1', args)
            self.assertEqual(args[-2:], ['--gdb', f'path={directory}/gdb.socket'])

    def test_invalid_configuration_is_rejected_before_disk_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            env = configuration(directory)
            for overrides in ({'GUEST_MODE': 'ssh', 'ENABLE_NETWORK': '0'}, {'VCPUS': '0'},
                              {'GUEST_IP': env['HOST_IP']}, {'GUEST_MAC': 'ff:00:00:00:00:01'},
                              {'TAP_DEV': 'x' * 16}, {'WORKDIR': '/'}, {'WORKDIR': '/usr/..'}, {'MEMORY_MIB': '64'},
                              {'KERNEL': '/tmp/kernel,other=path'},
                              {'BASE_ROOTFS': f'{directory}/rootfs-run.ext4'}):
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    guest.arguments(dict(env, **overrides))

    def test_kernel_download_is_atomic_and_sha256_checked(self):
        image = bytearray(4096)
        image[56:60] = b'ARM\x64'
        with tempfile.TemporaryDirectory() as directory:
            env = configuration(directory)
            env.update(KERNEL=f'{directory}/Image', KERNEL_URL='https://example.invalid/Image',
                       KERNEL_SHA256='0' * 64)
            with patch.object(guest.urllib.request, 'urlopen', return_value=io.BytesIO(image)):
                with self.assertRaisesRegex(ValueError, 'SHA256'):
                    guest.kernel(env)
            self.assertFalse(Path(env['KERNEL']).exists())
            self.assertFalse(Path(env['KERNEL'] + '.part').exists())
            env['KERNEL_SHA256'] = hashlib.sha256(image).hexdigest()
            with patch.object(guest.urllib.request, 'urlopen', return_value=io.BytesIO(image)):
                guest.kernel(env)
            self.assertEqual(Path(env['KERNEL']).read_bytes(), image)
            with patch.object(guest.urllib.request, 'urlopen', side_effect=AssertionError('Cache must avoid network')):
                guest.kernel(env)
            Path(env['KERNEL']).write_bytes(b'not a raw Image')
            with self.assertRaisesRegex(ValueError, 'raw ARM64'):
                guest.kernel(env)

    def test_gdb_wrapper_preserves_prepared_arguments_and_env_overrides(self):
        with tempfile.TemporaryDirectory(prefix="ch ' ") as directory:
            env = configuration(directory)
            env['KERNEL'] = directory + '/kernel with spaces'
            args = guest.arguments(env)
            Path(directory, 'args.json').write_text(json.dumps(args))
            capture = Path(directory, 'capture.py')
            capture.write_text('import json,sys; print(json.dumps(sys.argv[1:]))\n')
            result = subprocess.run(['bash', str(ROOT / 'vm-exec.sh'), 'python3', str(capture)],
                                    env=env, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout), args)
            self.assertTrue(Path(directory, 'cloud-hypervisor.pid').read_text().strip().isdigit())


if __name__ == '__main__':
    unittest.main()
