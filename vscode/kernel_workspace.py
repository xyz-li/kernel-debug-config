#!/usr/bin/env python3
"""Create a private workspace that binds Docker tasks and GDB to one kernel tree."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', choices=('one_container', 'multi_containers'))
    parser.add_argument('source', type=Path, help='Linux kernel source directory')
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    if not (source / 'Makefile').is_file() or not (source / 'init/main.c').is_file():
        parser.error('Expected Linux kernel sources containing Makefile and init/main.c')
    upper = source / 'include/uapi/linux/netfilter/xt_MARK.h'
    lower = source / 'include/uapi/linux/netfilter/xt_mark.h'
    if upper.exists() and lower.exists() and upper.samefile(lower):
        parser.error('Linux source has case-collapsed headers (xt_MARK.h / xt_mark.h). Use a case-sensitive source filesystem.')
    directory = Path(__file__).resolve().parent.parent / args.environment
    template = directory / (args.environment.replace('_', '-') + '.code-workspace')
    data = json.loads(template.read_text())
    data['folders'] = [{'name': 'kernel-config', 'path': '..'},
                       {'name': 'kernel-source', 'path': str(source)}]
    output = directory / 'output/debug.local.code-workspace'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(data, indent=2) + '\n')
    settings = directory / 'output/config.local.json'
    local = json.loads(settings.read_text()) if settings.exists() else {}
    local['source'] = str(source)
    settings.write_text(json.dumps(local, indent=2) + '\n')
    print(f'Open in VSCode: {output}')


if __name__ == '__main__':
    main()
