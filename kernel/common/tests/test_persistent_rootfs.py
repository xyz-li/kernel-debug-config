"""Validate persistent disk ownership and refusal to discard unsynced data."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import debian
import manifest
import qemu


class PersistentRootfsTests(unittest.TestCase):
    def disk(self, path, identity):
        data = bytearray(4096)
        data[1024+56:1024+58] = b'\x53\xef'
        data[1024+104:1024+120] = uuid.UUID(identity).bytes
        data[3072:3081] = b'user data'
        path.write_bytes(data)

    def test_ext4_disk_identity_is_independent_of_user_file_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'rootfs.ext4'
            identity = str(uuid.uuid4())
            self.disk(path, identity)
            self.assertEqual(manifest.disk_uuid(path), identity)
            with path.open('r+b') as stream:
                stream.seek(3072)
                stream.write(b'updated user data')
            self.assertEqual(manifest.disk_uuid(path), identity)
            path.write_bytes(b'not an ext4 disk')
            with self.assertRaises(ValueError):
                manifest.disk_uuid(path)

    def test_cached_rootfs_does_not_rewrite_the_persistent_disk(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            identity = str(uuid.uuid4())
            self.disk(output / 'rootfs.ext4', identity)
            original = (output / 'rootfs.ext4').read_bytes()
            (output / 'rootfs.uuid').write_text(identity+'\n')
            (output / 'kernel.config').write_text('\n'.join('CONFIG_'+key+'=y' for key in
                ('BLOCK','VIRTIO_BLK','EXT4_FS','FILE_LOCKING','VIRTIO_CONSOLE','RTC_CLASS','RTC_DRV_PL031','RTC_HCTOSYS')))
            manifest.write_json(output / 'kernel.json', dict(release='test',modules='matching'))
            (output / 'initramfs.cpio.gz').write_bytes(b'bootstrap')
            manifest.write_json(output / 'rootfs.json', dict(fingerprint='same',archive=manifest.file_hash(output/'initramfs.cpio.gz')))
            environment = object.__new__(debian.DebianEnvironment)
            environment.output = environment.directory = environment.overlay = output
            environment.environment = {'ROOTFS_BUILDER_IMAGE':'debian-test'}
            with (patch.object(environment,'image_id',return_value='image'),
                  patch('debian.disk_fingerprint',return_value='same'), patch.object(environment,'cli') as cli,
                  contextlib.redirect_stdout(io.StringIO())):
                environment.package_rootfs(False)
                cli.assert_not_called()
            self.assertEqual((output/'rootfs.ext4').read_bytes(),original)

    def test_missing_built_in_storage_driver_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary)/'config'
            config.write_text('CONFIG_BLOCK=y\nCONFIG_VIRTIO_BLK=m\nCONFIG_EXT4_FS=y\nCONFIG_VIRTIO_CONSOLE=y\n')
            with self.assertRaisesRegex(ValueError,'VIRTIO_BLK'):
                manifest.validate_disk_config(config)

    def test_stop_refuses_to_power_off_unsynced_persistent_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)
            (output/'console.log').write_text('KERNEL_DEBUG_READY\n')
            with (patch.object(qemu,'OUTPUT',output),patch.object(qemu,'state',return_value={'persistent':True}),
                  patch.object(qemu,'qmp',return_value={'status':'running'}) as qmp,
                  patch('qemu.socket.socket',side_effect=OSError('control unavailable')),
                  patch('qemu.os.kill') as kill,patch.object(qemu,'clear') as clear):
                with self.assertRaisesRegex(RuntimeError,'Refusing to power off unsynced data'):
                    qemu.stop()
                qmp.assert_called_once_with('query-status')
                kill.assert_not_called()
                clear.assert_not_called()

    def test_stop_cannot_bypass_disk_sync_during_early_boot(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / 'console.log').write_text('Mounting persistent root disk\n')
            with (patch.object(qemu, 'OUTPUT', output), patch.object(qemu, 'state', return_value={'persistent': True}),
                  patch.object(qemu, 'qmp', return_value={'status': 'running'}) as qmp,
                  patch('qemu.time.monotonic', side_effect=[0, 11]), patch('qemu.os.kill') as kill,
                  patch.object(qemu, 'clear') as clear):
                with self.assertRaisesRegex(RuntimeError, 'Refusing to power off unsynced data'):
                    qemu.stop()
                qmp.assert_called_once_with('query-status')
                kill.assert_not_called()
                clear.assert_not_called()


if __name__=='__main__':
    unittest.main()
