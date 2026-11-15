#!/usr/bin/env python3
"""Tunnel one localhost DAP session over Apple Container stdin/stdout."""
import base64
import errno
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import sys

remote_command = ['dap']
if len(sys.argv) != 1:
    if len(sys.argv) != 3 or sys.argv[1] != '--attach' or not sys.argv[2].isascii() or not sys.argv[2].isdigit() or int(sys.argv[2]) <= 0:
        raise SystemExit('Usage: dap_bridge.py [--attach LINUX_PID]')
    remote_command = ['attach', str(int(sys.argv[2]))]

machine = os.environ['MACHINE']
directory = Path(os.environ['DEBUG_DIR'])
port = int(os.environ.get('DEBUG_PORT', '38697'))
if not 1024 <= port <= 65535:
    raise SystemExit('DEBUG_PORT must be between 1024 and 65535')
base = ['container', 'machine', 'run', '-n', machine, '--root']
argv = base + ['--interactive', '--env', 'DEBUG_DLV_STDIN=1']
for key in ('SOURCE_DIR', 'WORKDIR', 'TOOLS_DIR', 'GO_VERSION', 'DEBUG_PORT'):
    argv += ['--env', f'{key}={os.environ[key]}']
encoded = base64.b64encode(json.dumps(remote_command).encode()).decode()
argv += ['--env', f'DEBUG_ARGS_BASE64={encoded}', '--', '/bin/bash', str(directory / 'dev.sh'), '_linux']

def interrupted(_signal, _frame):
    raise KeyboardInterrupt

signal.signal(signal.SIGTERM, interrupted)

with socket.socket() as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('127.0.0.1', port))
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            raise SystemExit(f'ERROR: Local debug port {port} is occupied. Stop the previous gVisor '
                             'debug task with Tasks: Terminate Task, or press Ctrl+C in its '
                             'dev.sh dap/attach terminal, then retry F5.') from None
        raise
    server.listen(1)
    print(f'DAP bridge listening at 127.0.0.1:{port}; waiting for Linux Delve.', flush=True)
    remote = subprocess.Popen(argv, stdin=subprocess.PIPE)
    connector = None
    try:
        server.settimeout(1)
        while True:
            try:
                connection, _ = server.accept()
                break
            except socket.timeout:
                if remote.poll() is not None:
                    raise SystemExit('Linux Delve exited before a client connected')
        with connection:
            command = base + ['--interactive', '--', 'socat', 'STDIO',
                f'TCP:127.0.0.1:{port},connect-timeout=2,retry=30,interval=0.2']
            connector = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            with selectors.DefaultSelector() as selector:
                selector.register(connection, selectors.EVENT_READ)
                selector.register(connector.stdout, selectors.EVENT_READ)
                finished = False
                while not finished:
                    for key, _ in selector.select():
                        if key.fileobj is connection:
                            data = connection.recv(65536)
                            if not data:
                                connector.stdin.close()
                                selector.unregister(connection)
                                finished = True
                                break
                            else:
                                connector.stdin.write(data)
                                connector.stdin.flush()
                        else:
                            data = os.read(connector.stdout.fileno(), 65536)
                            if not data:
                                selector.unregister(connector.stdout)
                                try:
                                    connection.shutdown(socket.SHUT_WR)
                                except OSError:
                                    pass
                                finished = True
                                break
                            else:
                                connection.sendall(data)
    except (KeyboardInterrupt, BrokenPipeError, ConnectionResetError):
        pass
    finally:
        # EOF on this pipe stops Linux Delve even if the local task is terminated.
        remote.stdin.close()
        for child in (connector, remote):
            if child is not None:
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
