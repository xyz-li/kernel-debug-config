"""Check exact version selection, authenticated transport checksums and safe extraction."""
import hashlib
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sources


class SourceTests(unittest.TestCase):
    def tree(self, path, minor='1', sublevel='102'):
        (path / 'init').mkdir(parents=True)
        (path / 'Makefile').write_text('VERSION = 6\nPATCHLEVEL = '+minor+'\nSUBLEVEL = '+sublevel+'\n')
        (path / 'init/main.c').touch()

    def test_requested_version_reuses_bound_tree_but_explicit_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            root = Path(temporary)
            source = root / 'edited-source'
            self.tree(source)
            with patch.dict(os.environ, KERNEL_VERSION='6.1.102'):
                selected, release, _ = sources.select(root, {'source': str(source)})
                self.assertEqual(selected, source.resolve())
                self.assertEqual(release, '6.1.102')
            with patch.dict(os.environ, KERNEL_VERSION='6.6', KERNEL_SOURCE=str(source)):
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    sources.select(root, {})
            with patch.dict(os.environ, KERNEL_VERSION='6.6'):
                selected, release, _ = sources.select(root, {'source': str(source)})
                self.assertEqual(selected, root / 'output/sources/6.6/tree/linux-6.6')

    def test_invalid_release_cannot_inject_paths_or_urls(self):
        for name in ('latest', '../6.1.102', '6.1;id', 'https://example.com', '6.1-rc1'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                sources.version(name)

    def test_prepare_verifies_checksum_and_never_replaces_an_existing_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_tree = root / 'input/linux-6.1.102'
            self.tree(input_tree)
            archive = root / 'release.tar.xz'
            with tarfile.open(archive, 'w:xz') as stream:
                stream.add(input_tree, arcname='linux-6.1.102')
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            selected = root / 'output/sources/6.1.102/tree/linux-6.1.102'

            def download(url, target):
                target.write_bytes((digest+'  linux-6.1.102.tar.xz\n').encode() if url.endswith('.asc') else archive.read_bytes())

            with patch('sources.sys.platform', 'linux'), patch('sources.fetch', side_effect=download) as fetch:
                sources.prepare(selected, '6.1.102', root)
                (selected / 'local-edit').write_text('keep user changes')
                sources.prepare(selected, '6.1.102', root)
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual((selected / 'local-edit').read_text(), 'keep user changes')
            self.assertTrue((selected.parents[1] / 'source.json').exists())
            with self.assertRaisesRegex(ValueError, 'refusing to replace'):
                sources.prepare(input_tree, '6.1.102', root)

    def test_archive_links_cannot_escape_the_extraction_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'bad.tar.xz'
            with tarfile.open(archive, 'w:xz') as stream:
                entry = tarfile.TarInfo('linux-6.1.102/escape')
                entry.type = tarfile.SYMTYPE
                entry.linkname = '../../../escaped'
                stream.addfile(entry)
            with self.assertRaises(tarfile.FilterError):
                sources.unpack(archive, root / 'target', '6.1.102')
