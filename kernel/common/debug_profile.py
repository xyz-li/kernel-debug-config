#!/usr/bin/env python3
"""Apply GCC local-variable debugging flags only to selected cached C files."""
import argparse
from pathlib import Path
import re
import shlex
import stat

from manifest import write_json

FLAGS = ['-Og', '-g3', '-fno-ipa-sra', '-fvar-tracking-assignments']
BEGIN = '# kernel-debug local variables: begin'
END = '# kernel-debug local variables: end'


def sources(values):
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError('debug_sources must be a list of relative C source paths')
    for value in values:
        path = Path(value)
        if (not re.fullmatch(r'[A-Za-z0-9_./-]+\.c', value) or path.is_absolute() or
                any(part in ('.', '..') for part in value.split('/'))):
            raise ValueError('Invalid debug source path: ' + value)
    return sorted(set(values))


def apply(source, selected):
    selected = sources(selected)
    compiler_flags = FLAGS
    grouped = {}
    for name in selected:
        file = source / name
        if not file.is_file() or not file.resolve().is_relative_to(source.resolve()):
            raise ValueError('Debug source is not inside the source tree: ' + name)
        makefile = file.parent / 'Kbuild'
        if not makefile.is_file():
            makefile = file.parent / 'Makefile'
        if not makefile.is_file():
            raise ValueError('No local Kbuild/Makefile for debug source: ' + name)
        grouped.setdefault(makefile, []).append(file.with_suffix('.o').name)
    for makefile, objects in grouped.items():
        original = makefile.read_text()
        original = re.sub(r'\n?' + re.escape(BEGIN) + r'\n.*?' + re.escape(END) + r'\n?', '\n', original, flags=re.S)
        lines = [BEGIN] + ['CFLAGS_' + name + ' += ' + ' '.join(compiler_flags) for name in objects] + [END]
        temporary = makefile.with_name(makefile.name + '.debug-part')
        temporary.write_text(original.rstrip() + '\n\n' + '\n'.join(lines) + '\n')
        temporary.chmod(stat.S_IMODE(makefile.stat().st_mode))
        temporary.replace(makefile)


def record(build, output, selected):
    selected = sources(selected)
    compiler_flags = FLAGS
    for name in selected:
        file = Path(name)
        command_file = build / file.parent / ('.' + file.stem + '.o.cmd')
        if not command_file.exists():
            raise ValueError('Selected source was not compiled; check its Kconfig: ' + name)
        command = next((line.split(':=', 1)[1] for line in command_file.read_text().splitlines()
                        if ':=' in line and line.split(':=', 1)[0].strip().startswith(('cmd_', 'savedcmd_'))), '')
        arguments = shlex.split(command)
        optimization = [argument for argument in arguments if re.fullmatch(r'-O(?:[0-3gsz]|fast)', argument)]
        if not optimization or optimization[-1] != compiler_flags[0] or not all(flag in arguments for flag in compiler_flags):
            raise ValueError('Local-variable flags did not take effect for ' + name)
    write_json(output / 'debug-profile.json', dict(sources=selected, flags=compiler_flags if selected else []))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('apply', 'record'))
    parser.add_argument('directory', type=Path)
    parser.add_argument('arguments', nargs='*')
    args = parser.parse_args()
    try:
        if args.action == 'apply':
            apply(args.directory, args.arguments)
        else:
            record(args.directory, Path(args.arguments[0]), args.arguments[1:])
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
