"""Check Apple container ownership, mounts and debugger input isolation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import apple
import dev


class AppleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        (root / 'apple-container').mkdir()
        with patch.object(dev, 'KERNEL_ROOT', root):
            self.environment = apple.AppleEnvironment()

    def tearDown(self):
        self.temporary.cleanup()

    def test_shared_cli_selects_the_apple_backend(self):
        with patch('apple.AppleEnvironment', return_value=self.environment) as backend:
            self.assertIs(dev.make_environment('apple-container'), self.environment)
            backend.assert_called_once_with('apple-container')

    def test_only_the_mi_debugger_gets_interactive_input(self):
        environment = self.environment
        mi = environment.pipe_arguments(['/usr/bin/gdb-multiarch', '--interpreter=mi'])
        control = environment.pipe_arguments(['kill -5 1234'])
        self.assertEqual(mi[:4], ['container', 'exec', '--interactive', environment.builder])
        self.assertEqual(mi[4:], ['/usr/bin/gdb-multiarch', '--interpreter=mi'])
        self.assertEqual(control, ['container', 'exec', environment.builder, '/bin/false'])

    def test_control_pipe_cannot_consume_adapter_input(self):
        environment = self.environment
        with patch('apple.os.dup2') as duplicate, patch('apple.os.execvpe') as execute:
            environment.pipe(['kill -5 1234'])
            duplicate.assert_called_once()
            self.assertEqual(duplicate.call_args.args[1], 0)
            self.assertEqual(execute.call_args.args[0], 'container')
        with patch('apple.os.dup2') as duplicate, patch('apple.os.execvpe'):
            environment.pipe(['/usr/bin/gdb-multiarch', '--interpreter=mi2'])
            duplicate.assert_not_called()

    def test_unowned_container_cannot_be_managed(self):
        environment = self.environment
        record = dict(id=environment.builder, configuration=dict(labels={}), status=dict(state='running'))
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps([record]))
        with patch.object(environment, 'cli', return_value=result):
            with self.assertRaisesRegex(ValueError, 'not owned'):
                environment.current()

    def test_mount_paths_preserve_spaces_and_quotes_as_data(self):
        self.assertEqual(self.environment.mount("/source with ' quote", '/kernel', readonly=True),
                         ['--mount', "type=bind,source=/source with ' quote,target=/kernel,readonly"])
        with self.assertRaisesRegex(ValueError, 'commas'):
            self.environment.mount('/source,invalid', '/kernel')

    def test_existing_native_volume_is_reused_only_for_its_owner(self):
        environment = self.environment
        name = environment.project + '-kernel-cache'
        record = dict(id=name, configuration=dict(name=name, labels={'kernel-debug.owner': environment.owner}))
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps([record]))
        with patch.object(environment, 'cli', return_value=result) as cli:
            self.assertEqual(environment.volume('kernel-cache', '24G'), name)
            cli.assert_called_once_with(['volume', 'list', '--format', 'json'], True)
        record['configuration']['labels'] = {}
        result.stdout = json.dumps([record])
        with patch.object(environment, 'cli', return_value=result):
            with self.assertRaisesRegex(ValueError, 'not owned'):
                environment.volume('kernel-cache', '24G')

    def test_rootfs_uses_the_recorded_image_and_a_separate_native_volume(self):
        environment = self.environment
        with (patch.object(environment, 'image_id', return_value='image-digest'),
              patch.object(environment, 'volume', return_value='private-rootfs-cache') as volume,
              patch.object(environment, 'cli') as cli):
            environment.package_rootfs(force=True)
        arguments = cli.call_args.args[0]
        self.assertEqual(arguments[:2], ['run', '--rm'])
        self.assertIn('ROOTFS_IMAGE_ID=image-digest', arguments)
        self.assertIn('ROOTFS_FORCE=1', arguments)
        self.assertIn('type=volume,source=private-rootfs-cache,target=/cache', arguments)
        volume.assert_called_once_with('rootfs-cache', '4G')

    def test_a_stale_container_spec_never_recreates_a_running_vm(self):
        environment = self.environment
        current = dict(configuration=dict(labels={'kernel-debug.spec': 'old'}), status=dict(state='running'))
        with (patch.object(environment, 'images'), patch.object(environment, 'image_id', return_value='image'),
              patch.object(environment, 'current', return_value=current),
              patch.object(environment, 'qemu', return_value=subprocess.CompletedProcess([], 0, stdout='{"running":true}')),
              patch.object(environment, 'cli') as cli):
            with self.assertRaisesRegex(ValueError, 'Stop the current debug session'):
                environment.up()
            cli.assert_not_called()


if __name__ == '__main__':
    unittest.main()
