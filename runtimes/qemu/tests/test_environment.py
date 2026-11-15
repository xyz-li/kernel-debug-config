"""Keep persistent guest imports independent and sparse."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qemu_runtime_environment', ROOT / 'environment.py')
environment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(environment)


class GuestImportTests(unittest.TestCase):
    def disk(self, path, identity, data=b'user data', clean=True):
        content = bytearray(8192)
        content[1024+56:1024+58] = b'\x53\xef'
        content[1024+58:1024+60] = (1 if clean else 0).to_bytes(2, 'little')
        content[1024+104:1024+120] = uuid.UUID(identity).bytes
        content[4096:4096+len(data)] = data
        path.write_bytes(content)

    def test_reimport_updates_kernel_without_replacing_runtime_user_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            source, target = parent / 'source', parent / 'target'
            source.mkdir(); target.mkdir()
            self.disk(source / 'rootfs.ext4', str(uuid.uuid4()), b'base data')
            identity = str(uuid.uuid4())
            self.disk(target / 'rootfs.ext4', identity, b'new runtime user files')
            original = (target / 'rootfs.ext4').read_bytes()
            for name in ('Image', 'vmlinux', 'kernel.config', 'kernel.json', 'initramfs.cpio.gz'):
                (source / name).write_bytes(b'new matching artifact')
            (source / 'rootfs.json').write_text(json.dumps(dict(release='matching-release', disk_uuid='source')))
            runtime = object.__new__(environment.Runtime)
            runtime.output = target
            with (patch.object(runtime, 'up'), patch.object(runtime, 'refuse_running'),
                  contextlib.redirect_stdout(io.StringIO())):
                runtime.import_guest(source)
            self.assertEqual((target / 'rootfs.ext4').read_bytes(), original)
            self.assertEqual((target / 'Image').read_bytes(), b'new matching artifact')
            self.assertEqual(json.loads((target / 'rootfs.json').read_text())['disk_uuid'], identity)

    def test_dirty_source_disk_is_not_imported(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source'; source.mkdir()
            target = Path(temporary) / 'target'; target.mkdir()
            self.disk(source / 'rootfs.ext4', str(uuid.uuid4()), clean=False)
            runtime = object.__new__(environment.Runtime)
            runtime.output = target
            with patch.object(runtime, 'refuse_running'), patch.object(runtime, 'up') as up:
                with self.assertRaisesRegex(ValueError, 'not shut down cleanly'):
                    runtime.import_guest(source)
                up.assert_not_called()
            self.assertFalse((target / 'rootfs.ext4').exists())

    def test_portable_disk_copy_keeps_contents_and_zero_tail_sparse(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = (Path(temporary) / name for name in ('source', 'target'))
            with source.open('wb') as stream:
                stream.write(b'header')
                stream.seek(8 * 1024 * 1024)
                stream.write(b'last data')
                stream.truncate(16 * 1024 * 1024)
            with patch.object(environment.sys, 'platform', 'linux'):
                environment.clone_disk(source, target)
            self.assertEqual(source.read_bytes(), target.read_bytes())
            # Some macOS filesystems allocate seek/truncate gaps; only require
            # physical sparseness when this filesystem supports creating it.
            if source.stat().st_blocks * 512 < source.stat().st_size:
                self.assertLess(target.stat().st_blocks * 512, 4 * 1024 * 1024)


if __name__ == '__main__':
    unittest.main()
