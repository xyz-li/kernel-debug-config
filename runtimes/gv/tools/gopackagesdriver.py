#!/usr/bin/env python3
"""Generate Bazel package metadata on Linux; expose its files to local gopls."""
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


class FileMirror:
    def __init__(self, source, cache):
        self.source = source.resolve()
        self.cache = cache.resolve()
        self.manifest = self.cache / 'manifest.json'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.previous = json.loads(self.manifest.read_text()) if self.manifest.exists() else {}
        self.changed = False
        self.paths = {}
        self.go_version = None
        go_mod = self.source / 'go.mod'
        if go_mod.is_file():
            contents = go_mod.read_text()
            version = re.search(r'^go\s+(\d+\.\d+(?:\.\d+)?)', contents, re.MULTILINE)
            if version:
                self.go_version = int(version[1].split('.')[1])

    def local(self, value):
        if not value or not value.startswith('/'):
            return value
        path = Path(value)
        if path.is_relative_to(self.source):
            return value
        destination = self.cache / value.lstrip('/')
        if value not in self.paths and path.is_file():
            stat = path.stat()
            signature = [stat.st_mtime_ns, stat.st_size]
            if self.previous.get(value) != signature or not destination.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Bazel outputs are read-only. Replace copies rather than writing through them.
                with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
                    temporary = Path(output.name)
                    with path.open('rb') as source:
                        shutil.copyfileobj(source, output)
                temporary.replace(destination)
                self.previous[value] = signature
                self.changed = True
        self.paths[value] = str(destination)
        return str(destination)

    def remote(self, value):
        prefix = str(self.cache) + '/'
        return '/' + value[len(prefix):] if value.startswith(prefix) else value

    def response(self, data):
        if self.go_version is not None:
            data['GoVersion'] = self.go_version
        for package in data.get('Packages', []):
            for key in ('GoFiles', 'CompiledGoFiles', 'OtherFiles', 'EmbedFiles', 'IgnoredFiles'):
                if key in package:
                    package[key] = [self.local(path) for path in package[key]]
            if package.get('ExportFile'):
                package['ExportFile'] = self.local(package['ExportFile'])
            for error in package.get('Errors', []):
                position = error.get('Pos', '')
                path, separator, suffix = position.partition(':')
                if path.startswith('/'):
                    error['Pos'] = self.local(path) + separator + suffix
        if self.changed:
            temporary = self.manifest.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.previous))
            temporary.replace(self.manifest)
        return data


def linux_driver(arguments):
    source = Path(os.environ['SOURCE_DIR'])
    work = Path(os.environ['WORKDIR'])
    tools = Path(os.environ['TOOLS_DIR'])
    work.mkdir(parents=True, exist_ok=True)
    # gopls can query several views concurrently; serialize generation and mirror updates.
    with (work / 'gopackagesdriver.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        mirror = FileMirror(source, Path(os.environ['DEBUG_DIR']) / 'output/gopls-files')
        request = json.load(sys.stdin)
        request['Overlay'] = {mirror.remote(k): v for k, v in (request.get('Overlay') or {}).items()}
        arguments = ['file=' + mirror.remote(a[5:]) if a.startswith('file=') else mirror.remote(a)
                     for a in arguments]
        os.chdir(os.environ.get('LSP_CWD', str(source)))
        bazel = str(tools / 'bin/bazelisk')
        startup = [f'--output_user_root={work}/bazel', '--host_jvm_args=-Xmx1536m']
        arch = {'aarch64': 'arm64', 'x86_64': 'amd64'}[platform.machine()]
        build_flags = ['-c', 'fastbuild', '--strip=never',
                       '--@io_bazel_rules_go//go/config:gc_goopts=-l',
                       # The driver turns ./... into explicit labels, including
                       # tests for other architectures (for example amd64 SlimVM).
                       '--skip_incompatible_explicit_targets',
                       f'--jobs={os.environ.get("JOBS", "2")}',
                       f'--symlink_prefix={work}/lsp-links/']
        env = dict(os.environ, GOOS='linux', GOARCH=arch,
                   GOPACKAGESDRIVER_BAZEL=bazel,
                   GOPACKAGESDRIVER_BAZEL_FLAGS=' '.join(startup),
                   GOPACKAGESDRIVER_BAZEL_BUILD_FLAGS=' '.join(build_flags))
        command = [bazel, *startup, 'run', *build_flags, '--',
                   '@io_bazel_rules_go//go/tools/gopackagesdriver', *arguments]
        with tempfile.TemporaryFile() as errors:
            result = subprocess.run(command, input=json.dumps(request).encode(),
                                    stdout=subprocess.PIPE, stderr=errors, env=env)
            errors.seek(0)
            log = errors.read()
            sys.stderr.buffer.write(log)
        # rules_go may return exit 0 with partial metadata after a Bazel failure.
        if result.returncode or re.search(rb'^ERROR:', log, re.MULTILINE):
            raise RuntimeError('Linux Bazel package generation failed; see the preceding Bazel error.')
        response = mirror.response(json.loads(result.stdout))
        json.dump(response, sys.stdout)


def main():
    if platform.system() == 'Darwin':
        keys = ('SOURCE_DIR', 'WORKDIR', 'TOOLS_DIR', 'DEBUG_DIR', 'GO_VERSION', 'JOBS', 'LSP_CWD')
        command = ['container', 'machine', 'run', '-n', os.environ['MACHINE'], '--root', '--interactive']
        for key in keys:
            command.extend(['--env', f'{key}={os.environ[key]}'])
        # machine run takes a shell command, so preserve spaces and shell metacharacters.
        command.extend(['--', shlex.join(['python3', str(Path(__file__).resolve()), *sys.argv[1:]])])
        return subprocess.call(command)
    linux_driver(sys.argv[1:])
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f'gVisor packages driver: {error}', file=sys.stderr)
        sys.exit(1)
