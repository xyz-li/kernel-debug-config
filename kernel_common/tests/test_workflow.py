"""Check cache invalidation, ownership safety and VSCode orchestration contracts."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import dev
import manifest
import qemu


class WorkflowTests(unittest.TestCase):
    def test_config_comments_are_removed_and_required_fragment_wins(self):
        with tempfile.TemporaryDirectory() as temporary:
            first, second = [Path(temporary) / name for name in ('user', 'required')]
            first.write_text('CONFIG_FTRACE=y # tracing\nCONFIG_LOCALVERSION=" # keep spaces" # comment\nCONFIG_DEBUG_INFO=n\n')
            second.write_text('CONFIG_DEBUG_INFO=y\n# CONFIG_RANDOMIZE_BASE is not set # debug\n')
            actual = manifest.normalize_config([first, second])
            self.assertIn('CONFIG_FTRACE=y\n', actual)
            self.assertIn('CONFIG_LOCALVERSION=" # keep spaces"\n', actual)
            self.assertEqual(actual.count('CONFIG_DEBUG_INFO='), 1)
            self.assertIn('CONFIG_DEBUG_INFO=y\n', actual)
            self.assertIn('# CONFIG_RANDOMIZE_BASE is not set\n', actual)

    def test_rootfs_cache_ignores_kernel_only_changes_but_tracks_modules_overlay_and_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            overlay = output / 'overlay'
            overlay.mkdir()
            module_data = dict(release='6.1-test', modules='modules-v1', image='kernel-v1')
            manifest.write_json(output / 'kernel.json', module_data)
            original = manifest.rootfs_fingerprint(output, ROOT, overlay, 'alpine-v1')
            module_data['image'] = 'kernel-v2'
            manifest.write_json(output / 'kernel.json', module_data)
            self.assertEqual(original, manifest.rootfs_fingerprint(output, ROOT, overlay, 'alpine-v1'))
            self.assertNotEqual(original, manifest.rootfs_fingerprint(output, ROOT, overlay, 'alpine-v2'))
            (overlay / 'test.sh').write_text('echo overlay\n')
            changed = manifest.rootfs_fingerprint(output, ROOT, overlay, 'alpine-v1')
            self.assertNotEqual(original, changed)
            os.utime(overlay / 'test.sh', (0, 0))
            self.assertEqual(changed, manifest.rootfs_fingerprint(output, ROOT, overlay, 'alpine-v1'))
            (overlay / 'test.sh').chmod(0o755)
            self.assertNotEqual(changed, manifest.rootfs_fingerprint(output, ROOT, overlay, 'alpine-v1'))
            module_data['modules'] = 'modules-v2'
            manifest.write_json(output / 'kernel.json', module_data)
            self.assertNotEqual(changed, manifest.rootfs_fingerprint(output, ROOT, overlay, 'alpine-v1'))

    def test_stale_pid_never_kills_an_unrelated_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            paths = {name: directory / name.lower() for name in ('STATE', 'QMP', 'GDB', 'CONSOLE')}
            manifest.write_json(paths['STATE'], dict(pid=os.getpid(), name='not-this-process'))
            with patch.multiple(qemu, **paths), patch('qemu.os.kill') as kill, contextlib.redirect_stdout(io.StringIO()):
                qemu.stop()
            kill.assert_not_called()
            self.assertFalse(paths['STATE'].exists())

    def test_running_vm_is_checked_before_image_rebuild_or_container_recreation(self):
        environment = object.__new__(dev.Environment)
        environment.service = 'kernel-dev'
        with (patch.object(environment, 'call', return_value=subprocess.CompletedProcess([], 0, stdout='container\n')),
              patch.object(environment, 'qemu', return_value=subprocess.CompletedProcess([], 0, stdout='{"running":true}')),
              patch.object(environment, 'up') as up):
            with self.assertRaisesRegex(ValueError, 'Stop the current debug session'):
                environment.build()
            up.assert_not_called()

    def test_both_workspaces_build_start_and_cleanup_automatically(self):
        for kind in ('one_container', 'multi_containers'):
            directory = ROOT.parent / kind / '.vscode'
            launch = json.loads((directory / 'launch.json').read_text())['configurations']
            tasks = {task['label']: task for task in json.loads((directory / 'tasks.json').read_text())['tasks']}
            automatic, fast, attach = launch
            self.assertEqual(tasks[automatic['preLaunchTask']]['args'], ['debug'])
            self.assertEqual(tasks[automatic['postDebugTask']]['args'], ['stop'])
            self.assertEqual(tasks[fast['preLaunchTask']]['args'], ['start'])
            self.assertNotIn('postDebugTask', attach)
            self.assertEqual(automatic['customLaunchSetupCommands'][0]['text'], '-file-exec-and-symbols /output/vmlinux')
            self.assertEqual(automatic['customLaunchSetupCommands'][1]['text'], '-target-select remote /cache/run/gdb.sock')
            self.assertEqual(automatic['customLaunchSetupCommands'][-1]['text'], '-break-insert -h -f start_kernel')
            self.assertEqual(automatic['sourceFileMap']['/cache/source'], '${workspaceFolder:kernel-source}')

    def test_fast_debug_rejects_artifacts_from_a_different_source_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = object.__new__(dev.Environment)
            environment.output = Path(temporary)
            environment.source = Path('/new/linux')
            manifest.write_json(environment.output / 'source.local.json', dict(source='/old/linux'))
            with patch.object(environment, 'refuse_running'), patch.object(environment, 'up') as up:
                with self.assertRaisesRegex(ValueError, 'do not match this source binding'):
                    environment.debug(rebuild=False)
                up.assert_not_called()

    def test_rootfs_validates_archive_content_and_rejects_stale_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            archive = output / 'initramfs.cpio.gz'
            archive.write_bytes(b'archive-v1')
            manifest.write_json(output / 'rootfs.json', dict(fingerprint='inputs-v1', archive=manifest.file_hash(archive)))
            self.assertTrue(manifest.rootfs_valid(output, 'inputs-v1'))
            self.assertFalse(manifest.rootfs_valid(output, 'inputs-v2'))
            archive.write_bytes(b'archive-v2')
            self.assertFalse(manifest.rootfs_valid(output, 'inputs-v1'))

    def test_bind_keeps_cli_source_workspace_and_local_preferences_in_sync(self):
        import shutil
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'vscode').mkdir()
            shutil.copy2(ROOT.parent / 'vscode/kernel_workspace.py', root / 'vscode/kernel_workspace.py')
            environment = root / 'one_container'
            environment.mkdir()
            shutil.copy2(ROOT.parent / 'one_container/one-container.code-workspace', environment / 'one-container.code-workspace')
            (environment / 'output').mkdir()
            manifest.write_json(environment / 'output/config.local.json', dict(jobs=3))
            source = root / "source with ' quote"
            (source / 'init').mkdir(parents=True)
            (source / 'Makefile').write_text('VERSION = 6\n')
            (source / 'init/main.c').touch()
            subprocess.run([sys.executable, str(root / 'vscode/kernel_workspace.py'), 'one_container', str(source)],
                           check=True, capture_output=True)
            config = json.loads((environment / 'output/config.local.json').read_text())
            workspace = json.loads((environment / 'output/debug.local.code-workspace').read_text())
            self.assertEqual(config, dict(jobs=3, source=str(source.resolve())))
            self.assertEqual(workspace['folders'][1]['path'], config['source'])

    def test_macos_source_image_mounts_once_and_never_for_an_unrelated_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            mount = root / 'mount'
            environment = object.__new__(dev.Environment)
            environment.kind = 'one_container'
            environment.source = mount / 'linux'
            environment.local = dict(source_image=str(root / 'source.sparsebundle'), source_mount=str(mount))
            environment.environment = {'JOBS': '2'}

            def mounted(*args, **kwargs):
                (environment.source / 'init').mkdir(parents=True)
                (environment.source / 'Makefile').touch()
                (environment.source / 'init/main.c').touch()

            with (patch('dev.sys.platform', 'darwin'), patch('dev.os.path.ismount', return_value=False),
                  patch('dev.subprocess.run', side_effect=mounted) as run):
                environment.validate_source()
                environment.validate_source()
                run.assert_called_once_with(['hdiutil', 'attach', str(root / 'source.sparsebundle'),
                                             '-mountpoint', str(mount), '-nobrowse'], check=True)
                environment.source = root / 'unrelated'
                with self.assertRaisesRegex(ValueError, 'Bind Linux sources first'):
                    environment.validate_source()
                self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
