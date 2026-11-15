"""Check moved entrypoints and safe, repeatable migration of private local state."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('migrate_layout', ROOT / 'tools/migrate_layout.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class LayoutTests(unittest.TestCase):
    def test_local_state_paths_modes_preferences_and_cache_identity_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            old = repo / 'one_container/output'
            old.mkdir(parents=True)
            (old / 'config.local.json').write_text(json.dumps(dict(source=str(old / 'kernel-source/linux'), jobs=3)))
            (old / 'images.local.json').write_text('{}')
            fc = repo / 'environments/fc'
            fc.mkdir(parents=True)
            env = fc / '.env'
            env.write_text(f"FC_BIN='{fc}/bin/firecracker-debug'\nKEEP='$HOME; literal'\n")
            env.chmod(0o600)
            (fc / 'output').mkdir()
            (fc / 'output/debug.local.code-workspace').write_text(json.dumps(dict(folders=[dict(name='fc-debug', path='..'), dict(name='fc-source', path='/external/firecracker')], settings={})))
            moved, updated = migration.migrate(repo)
            self.assertEqual(moved, 3)
            self.assertGreater(updated, 0)
            config = json.loads((repo / 'kernel/single-container/output/config.local.json').read_text())
            self.assertEqual(config['source'], str(repo / 'kernel/single-container/output/kernel-source/linux'))
            self.assertEqual(config['jobs'], 3)
            suffix = hashlib.sha256(str(repo / 'one_container').encode()).hexdigest()[:8]
            self.assertEqual(config['project'], 'kernel-debug-one-container-' + suffix)
            target = repo / 'runtimes/fc/.env'
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertIn("KEEP='$HOME; literal'", target.read_text())
            self.assertIn(str(repo / 'runtimes/fc/bin/firecracker-debug'), target.read_text())
            workspace = json.loads((target.parent / 'output/debug.local.code-workspace').read_text())
            self.assertEqual(workspace['folders'][0]['name'], 'fc-debug')
            self.assertEqual(workspace['folders'][1]['name'], 'firecracker-source')
            self.assertEqual(workspace['folders'][1]['path'], '/external/firecracker')
            self.assertEqual(migration.migrate(repo), (0, 0))

    def test_conflict_is_reported_before_any_state_is_moved(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            for relative in ('environments/fc', 'environments/kata', 'runtimes/kata'):
                directory = repo / relative
                directory.mkdir(parents=True)
                (directory / '.env').write_text(relative)
            with self.assertRaisesRegex(ValueError, 'Both'):
                migration.migrate(repo)
            self.assertTrue((repo / 'environments/fc/.env').exists())
            self.assertFalse((repo / 'runtimes/fc/.env').exists())
            self.assertEqual((repo / 'runtimes/kata/.env').read_text(), 'runtimes/kata')

    def test_long_runtime_directories_and_nested_source_paths_migrate_to_short_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            for old, new, key in [('firecracker', 'fc', 'FC_SOURCE'), ('cloud-hypervisor', 'ch', 'CH_SOURCE'),
                                  ('gvisor', 'gv', 'SOURCE_DIR')]:
                directory = repo / 'runtimes' / old
                (directory / 'output/upstream').mkdir(parents=True)
                (directory / 'output/upstream/source').write_text('upstream source')
                (directory / 'bin').mkdir()
                (directory / 'bin/artifact').write_bytes(b'local binary')
                (directory / '.env').write_text(f"{key}='{directory}/output/upstream'\nMACHINE=keep-host\n")
                (directory / '.env').chmod(0o600)
                (directory / 'output/debug.local.code-workspace').write_text(json.dumps(dict(
                    folders=[dict(name=old + '-debug', path='..'),
                             dict(name=old + '-source', path=str(directory / 'output/upstream'))],
                    settings={'editor.tabSize': 3})))
            self.assertEqual(migration.migrate(repo), (9, 6))
            for old, new in [('firecracker', 'fc'), ('cloud-hypervisor', 'ch'), ('gvisor', 'gv')]:
                directory = repo / 'runtimes' / new
                self.assertFalse((repo / 'runtimes' / old / 'output').exists())
                self.assertEqual((directory / 'output/upstream/source').read_text(), 'upstream source')
                self.assertEqual((directory / 'bin/artifact').read_bytes(), b'local binary')
                self.assertEqual((directory / '.env').stat().st_mode & 0o777, 0o600)
                self.assertIn(str(directory / 'output/upstream'), (directory / '.env').read_text())
                self.assertIn('MACHINE=keep-host', (directory / '.env').read_text())
                workspace = json.loads((directory / 'output/debug.local.code-workspace').read_text())
                self.assertEqual(workspace['folders'], [dict(name=new + '-debug', path='..'),
                                                       dict(name=old + '-source', path=str(directory / 'output/upstream'))])
                self.assertEqual(workspace['settings'], {'editor.tabSize': 3})
            self.assertEqual(migration.migrate(repo), (0, 0))

    def test_two_legacy_layouts_cannot_overwrite_the_same_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            for relative in ('environments/fc', 'runtimes/firecracker'):
                directory = repo / relative
                directory.mkdir(parents=True)
                (directory / '.env').write_text(relative)
            with self.assertRaisesRegex(ValueError, 'Both'):
                migration.migrate(repo)
            self.assertFalse((repo / 'runtimes/fc/.env').exists())
            for relative in ('environments/fc', 'runtimes/firecracker'):
                self.assertEqual((repo / relative / '.env').read_text(), relative)

    def test_gitkeep_does_not_block_migrating_existing_binaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            source = repo / 'environments/fc/bin'
            target = repo / 'runtimes/fc/bin'
            source.mkdir(parents=True)
            target.mkdir(parents=True)
            (target / '.gitkeep').touch()
            (source / 'firecracker-debug').write_bytes(b'local artifact')
            migration.migrate(repo)
            self.assertEqual((target / 'firecracker-debug').read_bytes(), b'local artifact')

    def test_runtime_workspaces_keep_sibling_upstream_sources(self):
        for kind, template, source in [('fc', 'firecracker', 'firecracker'), ('ch', 'cloud-hypervisor', 'cloud-hypervisor'), ('kata', 'kata', 'kata-containers'), ('gv', 'gvisor', 'gvisor'), ('qemu', 'qemu', 'qemu')]:
            directory = ROOT / 'runtimes' / kind
            workspace = json.loads((directory / f'{template}.code-workspace').read_text())
            folders = {folder['name']: (directory / folder['path']).resolve() for folder in workspace['folders']}
            self.assertEqual(folders[template + '-source'], ROOT.parent / source)

    def test_kernel_defaults_and_legacy_kind_aliases_resolve_to_new_layout(self):
        for kind, template in [('single-container', 'one-container'), ('multi-container', 'multi-containers'),
                               ('apple-container', 'apple-container'), ('debian-container', 'debian-container')]:
            directory = ROOT / 'kernel' / kind
            workspace = json.loads((directory / f'{template}.code-workspace').read_text())
            self.assertEqual((directory / workspace['folders'][1]['path']).resolve(), ROOT / 'linux-source')
            result = subprocess.run([str(directory / 'dev.sh'), '--help'], check=True, capture_output=True, text=True)
            self.assertIn(kind, result.stdout)
        for alias in ('one_container', 'multi_containers'):
            subprocess.run(['python3', str(ROOT / 'kernel/common/dev.py'), alias, '--help'], check=True, capture_output=True)

    def test_shared_guest_tools_are_not_owned_by_another_runtime(self):
        for kind, launcher in [('fc', 'run-firecracker.sh'), ('ch', 'run-cloud-hypervisor.sh')]:
            text = (ROOT / 'runtimes' / kind / launcher).read_text()
            self.assertIn('../common/guest/console.py', text)
            self.assertIn('../common/guest/ssh.sh', text)
        self.assertTrue((ROOT / 'runtimes/common/host/Dockerfile').is_file())

    def test_host_build_and_firecracker_alias_use_the_shared_build_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            fake = Path(temporary) / 'container'
            fake.write_text('#!/usr/bin/env python3\nimport json,sys; print(json.dumps(sys.argv[1:]))\n')
            fake.chmod(0o755)
            env = dict(os.environ, PATH=temporary + os.pathsep + os.environ['PATH'])
            for script, command in [('runtimes/common/host/dev.sh', 'build'), ('runtimes/fc/dev.sh', 'host-build')]:
                result = subprocess.run([str(ROOT / script), command], env=env, check=True, capture_output=True, text=True)
                args = json.loads(result.stdout)
                self.assertEqual(args[0], 'build')
                self.assertEqual(Path(args[-1]), ROOT / 'runtimes/common/host')
                self.assertEqual(Path(args[args.index('--file') + 1]), ROOT / 'runtimes/common/host/Dockerfile')

    def test_shared_host_defaults_are_read_before_runtime_overrides(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'repo/runtimes'
            (root / 'common').mkdir(parents=True)
            (root / 'common/.env').write_text('MACHINE=shared-host\n')
            for kind in ('fc', 'ch'):
                directory = root / kind
                directory.mkdir()
                shutil.copy2(ROOT / 'runtimes' / kind / 'config.sh', directory / 'config.sh')
                command = ['bash', '-c', 'set -e; source "$1"; printf "%s" "$MACHINE"', 'config-test', str(directory / 'config.sh')]
                shared = subprocess.run(command, check=True, capture_output=True, text=True)
                self.assertEqual(shared.stdout, 'shared-host')
                (directory / '.env').write_text('MACHINE=runtime-host\n')
                overridden = subprocess.run(command, check=True, capture_output=True, text=True)
                self.assertEqual(overridden.stdout, 'runtime-host')


if __name__ == '__main__':
    unittest.main()
