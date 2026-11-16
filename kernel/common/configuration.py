"""Compose small kernel fragments and detect stale configuration profiles."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex

from manifest import normalize_config

COMMON = Path(__file__).resolve().parent


def values(environment, name):
    override = os.environ.get('KERNEL_' + name.upper())
    selected = shlex.split(override) if override is not None else environment.local.get(name, [])
    if not isinstance(selected, list) or any(not isinstance(value, str) for value in selected):
        raise ValueError(name + ' must be a list of strings')
    return selected


def fragment(environment):
    files = [COMMON / 'configs/netfilter.config']
    for feature in values(environment, 'features'):
        if feature not in ('tracing', 'diagnostics', 'network-lab'):
            raise ValueError('Unknown kernel feature: ' + feature)
        files.append(COMMON / 'configs' / (feature + '.config'))
    if environment.kind == 'debian-container':
        files.append(COMMON / 'configs/disk.config')
    for filename in values(environment, 'config_fragments'):
        path = Path(filename).expanduser()
        files.append(path if path.is_absolute() else environment.directory / path)
    text = normalize_config(files)
    for symbol in values(environment, 'modules'):
        if not re.fullmatch(r'(?:CONFIG_)?[A-Z][A-Z0-9_]*', symbol):
            raise ValueError('Invalid Kconfig module symbol: ' + symbol)
        text += 'CONFIG_' + symbol.removeprefix('CONFIG_') + '=m\n'
    # Mandatory boot/debug requirements win over optional fragments.
    text += (COMMON / 'debug.config').read_text()
    return text


def identity(environment):
    record = dict(fragment=fragment(environment), base=environment.environment['KERNEL_BASE_CONFIG'],
                  strip_modules=os.environ.get('KERNEL_STRIP_MODULES', str(environment.local.get('strip_modules', 1))))
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()


def write(environment):
    path = environment.output / 'kernel.fragment.config'
    content = fragment(environment)
    path.write_text(content)
    return identity(environment)
