"""Protect the adapter's DAP input from auxiliary remote control commands."""
import json
import os
from pathlib import Path
import subprocess
import unittest

HELPER = Path(__file__).resolve().parents[1] / 'mi-pipe.sh'
COMMAND = '''source "$1"
shift
prepare_mi_pipe "$@"
python3 -c 'import json,sys; print(json.dumps([sys.argv[1:], sys.stdin.read()]))' "${MI_PIPE_FLAGS[@]}"
'''


class MiPipeTests(unittest.TestCase):
    def test_mi_sessions_keep_input_forwarding(self):
        for interpreter in ('--interpreter=mi', '--interpreter=mi2'):
            result = subprocess.run(['bash', '-c', COMMAND, 'mi-test', str(HELPER),
                                     '/usr/bin/gdb', interpreter],
                                    input='1001-thread-info\n', text=True, capture_output=True, check=True)
            self.assertEqual(json.loads(result.stdout), [['--interactive'], '1001-thread-info\n'])

    def test_control_commands_leave_the_adapters_input_unread(self):
        for arguments in (['kill -5 1234'], ['kill', '-5', '1234']):
            reader, writer = os.pipe()
            try:
                os.write(writer, b'Content-Length: 2\r\n\r\n{}')
                os.close(writer)
                writer = None
                result = subprocess.run(['bash', '-c', COMMAND, 'mi-test', str(HELPER), *arguments],
                                        stdin=reader, text=True, capture_output=True, check=True)
                self.assertEqual(json.loads(result.stdout), [[], ''])
                self.assertEqual(os.read(reader, 100), b'Content-Length: 2\r\n\r\n{}')
            finally:
                os.close(reader)
                if writer is not None:
                    os.close(writer)


if __name__ == '__main__':
    unittest.main()
