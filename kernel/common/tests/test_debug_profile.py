"""Check selective compiler flags and rejection of stale debug builds."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import debug_profile
import dev
from manifest import write_json


class DebugProfileTests(unittest.TestCase):
    def test_only_selected_cached_objects_get_flags_and_patch_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / 'net/ipv4'; directory.mkdir(parents=True)
            (directory / 'ping.c').touch()
            (directory / 'tcp.c').touch()
            makefile = directory / 'Makefile'
            original = 'obj-y += ping.o tcp.o\nCFLAGS_ping.o += -existing-flag\n'
            makefile.write_text(original)
            debug_profile.apply(root, ['net/ipv4/ping.c'])
            first = makefile.read_text()
            debug_profile.apply(root, ['net/ipv4/ping.c'])
            self.assertEqual(makefile.read_text(), first)
            self.assertIn(original.strip(), first)
            self.assertIn('CFLAGS_ping.o += -Og', first)
            self.assertNotIn('CFLAGS_tcp.o', first)

    def test_source_paths_cannot_escape_or_inject_make_expressions(self):
        for value in ('../ping.c', '/tmp/ping.c', 'net/../ping.c', 'net/$(shell id).c', 'net/ping.c\nall:'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                debug_profile.sources([value])

    def test_profile_is_recorded_only_when_flags_really_took_effect(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            directory = output / 'net/ipv4'; directory.mkdir(parents=True)
            command = directory / '.ping.o.cmd'
            flags = ' '.join(debug_profile.FLAGS)
            command.write_text('cmd_net/ipv4/ping.o := gcc -Os ' + flags + ' -c ping.c\n')
            debug_profile.record(output, output, ['net/ipv4/ping.c'])
            self.assertEqual(json.loads((output / 'debug-profile.json').read_text())['sources'], ['net/ipv4/ping.c'])
            command.write_text('cmd_net/ipv4/ping.o := gcc ' + flags + ' -Os -c ping.c\n')
            with self.assertRaisesRegex(ValueError, 'did not take effect'):
                debug_profile.record(output, output, ['net/ipv4/ping.c'])

    def test_restart_cannot_activate_profile_without_rebuilding(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = object.__new__(dev.Environment)
            environment.output = Path(temporary)
            environment.source = Path('/linux')
            environment.local = {'debug_sources': ['net/ipv4/ping.c']}
            write_json(environment.output / 'source.local.json', {'source': '/linux'})
            with (patch.dict(os.environ, {}, clear=True), patch.object(environment, 'refuse_running'),
                  patch.object(environment, 'up') as up):
                with self.assertRaisesRegex(ValueError, 'local-variable profile'):
                    environment.debug(rebuild=False)
                up.assert_not_called()
                self.assertTrue(environment.matching_build(dict(source='/linux',
                    debug_sources=['net/ipv4/ping.c'], debug_flags=debug_profile.FLAGS)))
