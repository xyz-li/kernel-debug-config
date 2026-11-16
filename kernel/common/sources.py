"""Select exact kernel.org releases without overwriting bound working trees."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

DEFAULT_VERSION = '6.1.102'


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[6-9]\.\d+(?:\.\d+)?', value):
        raise ValueError('KERNEL_VERSION must be an exact stable release, for example 6.1.102 or 6.6')
    return value


def tree_version(source):
    try:
        text = (Path(source) / 'Makefile').read_text()
        numbers = [re.search(r'^' + key + r'\s*=\s*(\d+)\s*$', text, re.M)[1]
                   for key in ('VERSION', 'PATCHLEVEL', 'SUBLEVEL')]
        return '.'.join(numbers if numbers[-1] != '0' else numbers[:2])
    except (OSError, TypeError):
        return None


def select(kernel_root, local):
    shared_path = kernel_root / 'output/source.local.json'
    shared = json.loads(shared_path.read_text()) if shared_path.exists() else {}
    settings = {**shared, **local}
    requested = os.environ.get('KERNEL_VERSION', settings.get('kernel_version'))
    bound = os.environ.get('KERNEL_SOURCE', settings.get('source'))
    if requested:
        requested = version(requested)
        dormant_image = (bound and settings.get('source_image') and
                         Path(bound).name == 'linux-' + requested and
                         not (Path(bound).expanduser() / 'Makefile').exists())
        if bound and (tree_version(Path(bound).expanduser()) == requested or dormant_image):
            return Path(bound).expanduser().resolve(), requested, settings
        if bound and 'KERNEL_SOURCE' in os.environ:
            raise ValueError('KERNEL_SOURCE does not match KERNEL_VERSION=' + requested)
    elif bound:
        return Path(bound).expanduser().resolve(), None, settings
    requested = requested or DEFAULT_VERSION
    source = kernel_root / 'output/sources' / requested / 'tree' / ('linux-' + requested)
    return source, requested, settings


def fetch(url, target):
    with urllib.request.urlopen(url, timeout=60) as response, target.open('wb') as output:
        shutil.copyfileobj(response, output)


def unpack(archive, directory, release):
    expected = 'linux-' + release
    with tarfile.open(archive, 'r:xz') as stream:
        # Reject archives with unrelated roots; data_filter also rejects escaping links.
        members = stream.getmembers()
        if any(Path(member.name).parts[0] != expected for member in members):
            raise ValueError('Unexpected kernel archive root')
        stream.extractall(directory, members=members, filter='data')


def prepare(source, release, kernel_root):
    release = version(release)
    managed = kernel_root / 'output/sources' / release
    expected = managed / 'tree' / ('linux-' + release)
    if source != expected:
        raise ValueError('Missing bound kernel source; refusing to replace it: ' + str(source))
    managed.mkdir(parents=True, exist_ok=True)
    with (managed / 'source.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        tree = managed / 'tree'
        image = managed / 'source.sparsebundle'
        if sys.platform == 'darwin' and not os.path.ismount(tree):
            if not image.exists():
                subprocess.run(['hdiutil', 'create', '-size', '8g', '-type', 'SPARSEBUNDLE',
                                '-fs', 'Case-sensitive APFS', '-volname', 'kernel-' + release, str(image)], check=True)
            tree.mkdir(exist_ok=True)
            subprocess.run(['hdiutil', 'attach', str(image), '-mountpoint', str(tree), '-nobrowse'], check=True)
        else:
            tree.mkdir(exist_ok=True)
        if tree_version(source) == release:
            return
        if source.exists():
            raise ValueError('Managed source has unexpected content; inspect it before retrying: ' + str(source))
        base = 'https://cdn.kernel.org/pub/linux/kernel/v' + release.split('.')[0] + '.x/'
        filename = 'linux-' + release + '.tar.xz'
        with tempfile.TemporaryDirectory(prefix='download-', dir=managed) as temporary:
            scratch = Path(temporary)
            checksums, archive = scratch / 'sha256sums.asc', scratch / filename
            print('Downloading exact Linux release ' + release + ' from kernel.org', flush=True)
            fetch(base + 'sha256sums.asc', checksums)
            match = re.search(r'^([0-9a-f]{64})\s+\*?' + re.escape(filename) + r'\s*$', checksums.read_text(), re.M)
            if not match:
                raise ValueError('Release absent from kernel.org SHA256 list: ' + release)
            fetch(base + filename, archive)
            with archive.open('rb') as downloaded:
                digest = hashlib.file_digest(downloaded, 'sha256').hexdigest()
            if digest != match[1]:
                raise ValueError('Kernel archive SHA256 mismatch')
            staging = Path(tempfile.mkdtemp(prefix='.extract-', dir=tree))
            try:
                unpack(archive, staging, release)
                if tree_version(staging / ('linux-' + release)) != release:
                    raise ValueError('Extracted Makefile version does not match requested release')
                (staging / ('linux-' + release)).rename(source)
            finally:
                shutil.rmtree(staging)
            (managed / 'source.json').write_text(json.dumps(dict(version=release, url=base + filename,
                sha256=digest, source=str(source)), indent=2) + '\n')


def check(source, requested):
    actual = tree_version(source)
    if requested and actual != requested:
        raise ValueError('Requested kernel ' + requested + ', but source Makefile is ' + str(actual))
