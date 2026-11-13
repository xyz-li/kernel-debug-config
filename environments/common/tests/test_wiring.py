"""Configuration wiring checks; these do not pretend to run upstream runtimes."""
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BindingTests(unittest.TestCase):
    def test_nested_environment_defaults_keep_sibling_checkouts(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            environments = parent / 'config-repo/environments'
            for kind in ('common', 'fc', 'gvisor', 'kata'):
                (environments / kind).mkdir(parents=True)
            for relative in ('common/config.sh', 'fc/config.sh'):
                shutil.copy2(ROOT / relative, environments / relative)
            clean_env = dict(os.environ)
            for key in ('FC_SOURCE', 'AGENT_SOURCE', 'SOURCE_DIR', 'HOST_KERNEL'):
                clean_env.pop(key, None)
            fc = subprocess.run(['bash', '-c', 'source "$1"; printf "%s\\n" "$FC_SOURCE" "$AGENT_SOURCE" "$HOST_KERNEL"',
                                 'defaults-test', str(environments / 'fc/config.sh')],
                                check=True, capture_output=True, text=True, env=clean_env)
            self.assertEqual(fc.stdout.splitlines(), [str(parent / 'firecracker'), str(parent / 'guest-agent'),
                                                      str(parent / 'containerization/kernel/vmlinux-arm64')])
            for kind, checkout in [('gvisor', 'gvisor'), ('kata', 'kata-containers')]:
                common = subprocess.run(['bash', '-c', 'source "$1"; printf "%s\\n" "$SOURCE_DIR" "$HOST_KERNEL"',
                                         'defaults-test', str(environments / 'common/config.sh')],
                                        check=True, capture_output=True, text=True, env=dict(clean_env, DEBUG_KIND=kind))
                self.assertEqual(common.stdout.splitlines(), [str(parent / checkout),
                                  str(parent / 'containerization/kernel/vmlinux-arm64')])

    def test_binding_preserves_settings_and_handles_quotes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'common').mkdir()
            shutil.copy2(ROOT / 'common/bind.py', root / 'common/bind.py')
            for kind, marker, key in [('fc', 'src/firecracker/Cargo.toml', 'FC_SOURCE'),
                                      ('gvisor', '.bazelversion', 'SOURCE_DIR'),
                                      ('kata', 'src/agent/Cargo.toml', 'SOURCE_DIR'),
                                      ('cloud-hypervisor', 'vmm/src/lib.rs', 'CH_SOURCE')]:
                directory = root / kind
                directory.mkdir()
                (directory / '.env').write_text('MACHINE=keep-this-machine\n')
                source = root / f"{kind} source with ' quote"
                (source / marker).parent.mkdir(parents=True, exist_ok=True)
                (source / marker).write_text('fixture\n')
                subprocess.run(['python3', str(root / 'common/bind.py'), kind, str(source)], check=True, capture_output=True)
                result = subprocess.run(['bash', '-c', f'source "$1"; printf "%s\\n" "${{{key}}}" "$MACHINE"',
                                         'binding-test', str(directory / '.env')], check=True, text=True, capture_output=True)
                self.assertEqual(result.stdout.splitlines(), [str(source.resolve()), 'keep-this-machine'])
                self.assertEqual((directory / '.env').stat().st_mode & 0o777, 0o600)
                workspace = json.loads((directory / 'output/debug.local.code-workspace').read_text())
                self.assertEqual(workspace['folders'][1]['path'], str(source.resolve()))
                self.assertEqual([folder['name'] for folder in workspace['folders']],
                                 [f'{kind}-debug', f'{kind}-source'])
                self.assertEqual((directory / 'output' / workspace['folders'][0]['path']).resolve(),
                                 directory.resolve())
                self.assertEqual((source / marker).read_text(), 'fixture\n')

    def test_invalid_checkout_does_not_write_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(['python3', str(ROOT / 'common/bind.py'), 'gvisor', temporary], capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_remote_arguments_preserve_empty_spaces_quotes_and_newlines(self):
        arguments = ['run', '', 'two words', 'quote\'"', 'line\none', '$HOME; echo no']
        encoded = base64.b64encode(json.dumps(arguments).encode()).decode()
        result = subprocess.run(['bash', '-c', 'source "$1"; decode_args; printf "%s\\0" "${DECODED_ARGS[@]}"',
                                 'decoder-test', str(ROOT / 'common/config.sh')], capture_output=True, check=True,
                                env=dict(os.environ, DEBUG_KIND='gvisor', DEBUG_ARGS_BASE64=encoded))
        self.assertEqual(result.stdout.split(b'\0')[:-1], [a.encode() for a in arguments])

    def test_launch_templates_reference_real_wrappers(self):
        for kind in ('fc', 'gvisor', 'kata', 'cloud-hypervisor'):
            launch = json.loads((ROOT / kind / '.vscode/launch.json').read_text())
            tasks = json.loads((ROOT / kind / '.vscode/tasks.json').read_text())
            labels = {task['label'] for task in tasks['tasks']}
            for config in launch['configurations']:
                if 'preLaunchTask' in config:
                    self.assertIn(config['preLaunchTask'], labels)
                pipe = config.get('pipeTransport')
                if pipe:
                    wrapper = pipe['pipeProgram'].replace('${workspaceFolder}', str(ROOT / kind))
                    self.assertTrue(Path(wrapper).is_file(), wrapper)

    def test_f5_task_dependencies_build_before_launch_and_preserve_attach_symbols(self):
        for kind in ('fc', 'gvisor', 'kata', 'cloud-hypervisor'):
            directory = ROOT / kind
            tasks_file = json.loads((directory / '.vscode/tasks.json').read_text())
            tasks = {task['label']: task for task in tasks_file['tasks']}

            def commands(label, ancestors=()):
                self.assertNotIn(label, ancestors, f'Task dependency cycle: {ancestors} -> {label}')
                self.assertIn(label, tasks)
                task = tasks[label]
                dependencies = task.get('dependsOn', [])
                if isinstance(dependencies, str):
                    dependencies = [dependencies]
                if len(dependencies) > 1:
                    self.assertEqual(task.get('dependsOrder'), 'sequence', label)
                result = []
                for dependency in dependencies:
                    result.extend(commands(dependency, ancestors + (label,)))
                if 'command' in task:
                    options = dict(tasks_file.get('options', {}), **task.get('options', {}))
                    self.assertEqual(options.get('cwd'), '${workspaceFolder}', label)
                    result.append(task['command'])
                return result

            for label in tasks:
                commands(label)
            launch = json.loads((directory / '.vscode/launch.json').read_text())
            for config in launch['configurations']:
                chain = commands(config['preLaunchTask']) if 'preLaunchTask' in config else []
                if config['request'] == 'attach':
                    self.assertFalse(any(command.startswith('./dev.sh build') for command in chain), config['name'])
                    if kind == 'gvisor':
                        self.assertEqual(chain, ['./dev.sh dap'])
                    continue
                self.assertTrue(chain and chain[0].startswith('./dev.sh build'), config['name'])
                if kind == 'gvisor':
                    self.assertEqual(chain, ['./dev.sh build', './dev.sh dap'])
                    dap = tasks['gVisor: Start Delve DAP']
                    self.assertTrue(dap['isBackground'])
                    ready = dap['problemMatcher']['background']['endsPattern']
                    self.assertRegex('DAP server listening at: 127.0.0.1:38697', ready)
                    self.assertIsNone(re.search(ready, 'DAP bridge listening at 127.0.0.1:38697'))
                if config['name'] == 'Kata: Standalone Agent RPC':
                    self.assertEqual(chain, ['./dev.sh build agent', './dev.sh bundle'])
                if config['name'] == 'Kata: shim-ctl real VM':
                    self.assertEqual(chain, ['./dev.sh build runtime', './dev.sh bundle', './dev.sh vm-check'])

    def test_public_workspaces_resolve_configuration_and_named_source_folders(self):
        for kind, filename, checkout in [('fc', 'firecracker', 'firecracker'),
                                         ('gvisor', 'gvisor', 'gvisor'), ('kata', 'kata', 'kata-containers'),
                                         ('cloud-hypervisor', 'cloud-hypervisor', 'cloud-hypervisor')]:
            directory = ROOT / kind
            workspace = json.loads((directory / f'{filename}.code-workspace').read_text())
            folders = {folder['name']: (directory / folder['path']).resolve() for folder in workspace['folders']}
            self.assertEqual(folders[f'{kind}-debug'], directory)
            self.assertEqual(folders[f'{kind}-source'], ROOT.parent.parent / checkout)
            launch = (directory / '.vscode/launch.json').read_text()
            for name in re.findall(r'\$\{workspaceFolder:([^}]+)\}', launch):
                self.assertIn(name, folders)


if __name__ == '__main__':
    unittest.main()
