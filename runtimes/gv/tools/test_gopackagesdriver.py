"""Verify that Linux package files remain usable by local gopls."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('driver', Path(__file__).with_name('gopackagesdriver.py'))
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class MirrorTests(unittest.TestCase):
    def test_driver_reports_the_checkout_language_version(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory).resolve() / 'source'
            source.mkdir()
            (source / 'go.mod').write_text('module example.test/sentry\n\ngo 1.27.3\n')
            mirror = driver.FileMirror(source, Path(directory) / 'cache')
            result = mirror.response({'Packages': []})
            self.assertEqual(result['GoVersion'], 27)

    def test_generated_files_are_readable_and_updates_replace_readonly_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / 'source'
            source.mkdir()
            original = source / 'main.go'
            original.write_text('package main\n')
            generated = root / 'linux-cache/generated.go'
            generated.parent.mkdir()
            generated.write_text('package generated\n')
            mirror = driver.FileMirror(source, root / 'mirror')
            response = {'Packages': [{'GoFiles': [str(original), str(generated)],
                                     'CompiledGoFiles': [str(generated)]}]}
            data = mirror.response(response)
            files = data['Packages'][0]['GoFiles']
            self.assertEqual(files[0], str(original))
            local = Path(files[1])
            self.assertEqual(local.read_bytes(), generated.read_bytes())
            self.assertEqual(mirror.remote(str(local)), str(generated))
            self.assertEqual(data['Packages'][0]['CompiledGoFiles'], [str(local)])
            local.chmod(0o444)
            generated.write_text('package updated\n')
            second = driver.FileMirror(source, root / 'mirror')
            second.response({'Packages': [{'GoFiles': [str(generated)]}]})
            self.assertEqual(local.read_bytes(), generated.read_bytes())
            signature = json.loads(second.manifest.read_text())[str(generated)]
            self.assertEqual(signature[1], generated.stat().st_size)


if __name__ == '__main__':
    unittest.main()
