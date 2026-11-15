#!/usr/bin/env python3
"""Keep one Linux Delve server alive for the lifetime of its bridge input."""
import fcntl
import os
from pathlib import Path
import select
import signal
import subprocess
import sys


def main():
    workdir, port, mode, *arguments = sys.argv[1:]
    command = ['dlv', 'dap', f'--listen=127.0.0.1:{port}']
    if mode == 'attach':
        command = ['dlv', '--headless', f'--listen=127.0.0.1:{port}', '--api-version=2', 'attach', *arguments]
    elif mode != 'dap':
        raise SystemExit('Expected dap or attach')

    with (Path(workdir) / 'dap.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('ERROR: Another Delve session is active; stop its VSCode task first.')

        def interrupted(_signal, _frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, interrupted)
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL)
        try:
            while child.poll() is None:
                if os.environ.get('DEBUG_DLV_STDIN') == '1':
                    ready, _, _ = select.select([sys.stdin], [], [], 0.2)
                    if ready and not os.read(sys.stdin.fileno(), 4096):
                        break
                else:
                    try:
                        child.wait(timeout=0.2)
                    except subprocess.TimeoutExpired:
                        pass
            return child.returncode or 0
        except KeyboardInterrupt:
            return 0
        finally:
            if child.poll() is None:
                # Delve detaches an attached target on SIGTERM, leaving it running.
                child.terminate()
                try:
                    child.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
