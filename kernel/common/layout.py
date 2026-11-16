"""Canonical kernel environments and the aliases accepted by older commands."""
from pathlib import Path

KERNEL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = KERNEL_ROOT.parent
SERVICES = {'apple-container': 'kernel-builder', 'debian-container': 'kernel-builder'}
WORKSPACES = {'apple-container': 'apple-container.code-workspace',
              'debian-container': 'debian-container.code-workspace'}
ALIASES = {'one_container': 'apple-container', 'multi_containers': 'apple-container',
           'single-container': 'apple-container', 'multi-container': 'apple-container'}


def canonical(kind):
    kind = ALIASES.get(kind, kind)
    if kind not in SERVICES:
        raise ValueError(f'Unknown kernel environment: {kind}')
    return kind
