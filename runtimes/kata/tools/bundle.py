#!/usr/bin/env python3
"""Make an isolated OCI test bundle; never replaces an existing bundle."""
import json
from pathlib import Path
import shutil
import sys

bundle = Path(sys.argv[1])
if (bundle / 'config.json').exists():
    print(f'Bundle exists; preserving {bundle}')
    raise SystemExit(0)
binary = Path('/bin/busybox')
if not binary.is_file():
    raise SystemExit('Install Ubuntu busybox-static first')
root = bundle / 'rootfs'
for name in ('bin', 'proc', 'sys', 'dev', 'tmp', 'etc'):
    (root / name).mkdir(parents=True, exist_ok=True)
shutil.copy2(binary, root / 'bin/busybox')
for applet in ('sh', 'sleep', 'echo', 'cat', 'true', 'uname'):
    path = root / 'bin' / applet
    if not path.exists():
        path.symlink_to('busybox')
config = {'ociVersion': '1.0.2', 'root': {'path': 'rootfs', 'readonly': False},
          'process': {'terminal': False, 'user': {'uid': 0, 'gid': 0},
                      'args': ['/bin/sh', '-c', 'echo sandbox-ready; sleep 300'],
                      'env': ['PATH=/bin'], 'cwd': '/'},
          'hostname': 'debug-sandbox', 'mounts': [{'destination': '/proc', 'type': 'proc', 'source': 'proc'}],
          'linux': {'namespaces': [{'type': t} for t in ('pid', 'mount', 'ipc', 'uts', 'network')]}}
(bundle / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
print(f'Prepared OCI bundle: {bundle}')
