#!/usr/bin/env python3
"""Move ignored local state after updating from an older repository layout."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat

RELOCATIONS = {
    'environments/fc': 'runtimes/fc',
    'environments/cloud-hypervisor': 'runtimes/ch',
    'runtimes/firecracker': 'runtimes/fc',
    'runtimes/cloud-hypervisor': 'runtimes/ch',
    'environments/gvisor': 'runtimes/gv',
    'runtimes/gvisor': 'runtimes/gv',
    'environments/kata': 'runtimes/kata',
    'environments/common': 'runtimes/common',
    'one_container': 'kernel/single-container',
    'multi_containers': 'kernel/multi-container',
    'kernel_common': 'kernel/common',
    'vscode/kernel_workspace.py': 'kernel/common/workspace.py',
    'vscode': 'kernel/vscode',
    'environments': 'runtimes',
    'net': 'network',
}
STATE_ROOTS = ('environments/fc', 'environments/cloud-hypervisor', 'environments/gvisor',
               'environments/kata', 'environments/common', 'one_container', 'multi_containers',
               'runtimes/firecracker', 'runtimes/cloud-hypervisor', 'runtimes/gvisor')
METADATA = ('debug.local.code-workspace', 'config.local.json', 'source.local.json',
            'compile_commands.json', 'compile_commands.linux.json')


def rewrite_paths(text, repo):
    for old, new in sorted(RELOCATIONS.items(), key=lambda item: -len(item[0])):
        text = re.sub(re.escape(str(repo / old)) + r'''(?=$|[/"'\s])''',
                      lambda _match: str(repo / new), text)
    return text


def write_text(path, text):
    temporary = path.with_name(path.name + '.layout.part')
    temporary.write_text(text)
    temporary.chmod(stat.S_IMODE(path.stat().st_mode))
    temporary.replace(path)


def migrate(repo):
    repo = Path(repo).resolve()
    moves = []
    destinations = {}
    for old in STATE_ROOTS:
        for name in ('.env', 'bin', 'output'):
            source, target = repo / old / name, repo / RELOCATIONS[old] / name
            if not source.exists():
                continue
            if target in destinations:
                raise ValueError(f'Both {destinations[target]} and {source} target {target}; resolve the conflict first.')
            destinations[target] = source
            if target.exists():
                if not (source.is_dir() and target.is_dir() and
                        all(p.name == '.gitkeep' for p in target.iterdir())):
                    raise ValueError(f'Both {source} and {target} contain local state; resolve the conflict first.')
            moves.append((source, target))
    # Check every destination before moving anything, including individual files.
    for source, target in moves:
        if target.exists():
            for child in source.iterdir():
                if (target / child.name).exists() and child.name != '.gitkeep':
                    raise ValueError(f'Local state conflict: {target / child.name}')
    for source, target in moves:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            for child in source.iterdir():
                if child.name == '.gitkeep' and (target / child.name).exists():
                    child.unlink()
                else:
                    child.rename(target / child.name)
            source.rmdir()
        else:
            source.rename(target)

    updated = 0
    for old in STATE_ROOTS:
        directory = repo / RELOCATIONS[old]
        env = directory / '.env'
        if env.is_file():
            before = env.read_text()
            after = rewrite_paths(before, repo)
            if before != after:
                write_text(env, after)
                updated += 1
        for name in METADATA:
            path = directory / 'output' / name
            if not path.is_file():
                continue
            before = path.read_text()
            data = json.loads(rewrite_paths(before, repo))
            if name == 'config.local.json' and old in ('one_container', 'multi_containers'):
                if data.get('layout_version') != 2 and (path.parent / 'images.local.json').exists():
                    suffix = hashlib.sha256(str(repo / old).encode()).hexdigest()[:8]
                    data.setdefault('project', f'kernel-debug-{old.replace("_", "-")}-{suffix}')
                data['layout_version'] = 2
            if name == 'debug.local.code-workspace':
                labels = {
                    'runtimes/fc': {'firecracker-debug': 'fc-debug', 'fc-source': 'firecracker-source'},
                    'runtimes/ch': {'cloud-hypervisor-debug': 'ch-debug'},
                    'runtimes/gv': {'gvisor-debug': 'gv-debug'},
                }.get(RELOCATIONS[old], {})
                for folder in data.get('folders', []):
                    folder['name'] = labels.get(folder['name'], folder['name'])
            after = json.dumps(data, indent=2) + '\n'
            if before != after:
                write_text(path, after)
                updated += 1
    return len(moves), updated


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    try:
        moved, updated = migrate(args.repo)
    except (OSError, ValueError) as error:
        raise SystemExit(f'Layout migration stopped: {error}')
    print(f'Local state migration complete: {moved} items moved, {updated} metadata files updated.')
