"""Check lean defaults, optional features, and silent Kconfig dependency loss."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import configuration
import manifest


class ConfigurationTests(unittest.TestCase):
    def environment(self, path):
        return SimpleNamespace(kind='apple-container', directory=path, local={},
                               environment={'KERNEL_BASE_CONFIG':'tinyconfig'})

    def test_default_is_small_but_keeps_both_firewall_backends_and_loadable_modules(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            env = self.environment(Path(temporary))
            text = configuration.fragment(env)
            self.assertIn('CONFIG_NF_TABLES=m', text)
            self.assertIn('CONFIG_IP_NF_IPTABLES=m', text)
            self.assertIn('CONFIG_VIRTIO_NET=y', text)
            self.assertNotIn('CONFIG_PROVE_LOCKING=y', text)
            self.assertNotIn('CONFIG_FUNCTION_TRACER=y', text)
            before = configuration.identity(env)
            with patch.dict(os.environ, KERNEL_FEATURES='tracing', KERNEL_MODULES='DUMMY TUN'):
                text = configuration.fragment(env)
                self.assertIn('CONFIG_FUNCTION_TRACER=y', text)
                self.assertIn('CONFIG_DUMMY=m', text)
                self.assertNotEqual(configuration.identity(env), before)
            with patch.dict(os.environ, KERNEL_MODULES='../TUN'):
                with self.assertRaises(ValueError): configuration.fragment(env)

    def test_missing_firewall_dependencies_and_dropped_module_requests_fail_the_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resolved, request = root/'resolved', root/'request'
            request.write_text('CONFIG_DUMMY=m\n')
            resolved.write_text('# CONFIG_DUMMY is not set\nCONFIG_NF_TABLES=m\n')
            with self.assertRaisesRegex(ValueError, 'CONFIG_DUMMY=m'):
                manifest.validate_requested_config(resolved, request)
            with self.assertRaisesRegex(ValueError, 'IP_NF_IPTABLES'):
                manifest.validate_network_config(resolved)
