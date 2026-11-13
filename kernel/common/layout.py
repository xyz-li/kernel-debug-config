"""Canonical kernel environments and the aliases accepted by older commands."""
from pathlib import Path

KERNEL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = KERNEL_ROOT.parent
SERVICES = {'single-container': 'kernel-dev', 'multi-container': 'kernel-builder'}
WORKSPACES = {'single-container': 'one-container.code-workspace',
              'multi-container': 'multi-containers.code-workspace'}
ALIASES = {'one_container': 'single-container', 'multi_containers': 'multi-container'}


def canonical(kind):
    kind = ALIASES.get(kind, kind)
    if kind not in SERVICES:
        raise ValueError(f'Unknown kernel environment: {kind}')
    return kind
