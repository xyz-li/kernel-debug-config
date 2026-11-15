"""QEMU target PIDs must never be used to signal Linux container processes."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mi_pipe


class MiPipeTests(unittest.TestCase):
    def test_virtual_pid_one_defers_interrupt_to_gdb_mi(self):
        command, interactive = mi_pipe.pipe_command(['kill -5 1'])
        self.assertEqual(command, ['/bin/false'])
        self.assertFalse(interactive)

    def test_mi_debugger_keeps_its_arguments_and_input(self):
        arguments = ['/usr/bin/gdb-multiarch', '--interpreter=mi']
        self.assertEqual(mi_pipe.pipe_command(arguments), (arguments, True))

    def test_invalid_control_commands_are_rejected(self):
        for arguments in (['kill -9 1'], ['kill -5 -1'], ['kill -5 1; touch /tmp/unexpected']):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                mi_pipe.pipe_command(arguments)


if __name__ == '__main__':
    unittest.main()
