#!/usr/bin/env python3
"""Create a private workspace that binds container tasks and GDB to one kernel tree."""
import argparse
import json
from pathlib import Path
from layout import ALIASES, KERNEL_ROOT, SERVICES, WORKSPACES, canonical
from sources import tree_version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', choices=(*SERVICES, *ALIASES))
    parser.add_argument('source', type=Path, help='Linux kernel source directory')
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    if not (source / 'Makefile').is_file() or not (source / 'init/main.c').is_file():
        parser.error('Expected Linux kernel sources containing Makefile and init/main.c')
    upper = source / 'include/uapi/linux/netfilter/xt_MARK.h'
    lower = source / 'include/uapi/linux/netfilter/xt_mark.h'
    if upper.exists() and lower.exists() and upper.samefile(lower):
        parser.error('Linux source has case-collapsed headers (xt_MARK.h / xt_mark.h). Use a case-sensitive source filesystem.')
    kind = canonical(args.environment)
    directory = KERNEL_ROOT / kind
    template = directory / WORKSPACES[kind]
    data = json.loads(template.read_text())
    data['folders'] = [{'name': 'kernel-config', 'path': '..'},
                       {'name': 'kernel-source', 'path': str(source)}]
    output = directory / 'output/debug.local.code-workspace'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(data, indent=2) + '\n')
    settings = directory / 'output/config.local.json'
    local = json.loads(settings.read_text()) if settings.exists() else {}
    local['source'] = str(source)
    actual = tree_version(source)
    if actual:
        local['kernel_version'] = actual
    local['layout_version'] = 2
    source_image = source.parent.parent / 'source.sparsebundle'
    if source_image.exists():
        local.update(source_image=str(source_image), source_mount=str(source.parent))
    elif local.get('source_mount') and not source.is_relative_to(Path(local['source_mount'])):
        local.pop('source_image', None)
        local.pop('source_mount', None)
    settings.write_text(json.dumps(local, indent=2) + '\n')
    shared = KERNEL_ROOT / 'output'
    shared.mkdir(exist_ok=True)
    (shared / 'source.local.json').write_text(json.dumps({key: local[key] for key in
        ('source', 'source_image', 'source_mount') if key in local}, indent=2) + '\n')
    print(f'Open in VSCode: {output}')


if __name__ == '__main__':
    main()
