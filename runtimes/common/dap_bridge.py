#!/usr/bin/env python3
"""Tunnel one localhost DAP session over Apple Container stdin/stdout."""
import base64
import json
import os
from pathlib import Path
import selectors
import socket
import subprocess
import sys

machine = os.environ['MACHINE']
directory = Path(os.environ['DEBUG_DIR'])
port = int(os.environ.get('DEBUG_PORT', '38697'))
if not 1024 <= port <= 65535:
    raise SystemExit('DEBUG_PORT must be between 1024 and 65535')
base = ['container', 'machine', 'run', '-n', machine, '--root']
argv = base.copy()
for key in ('SOURCE_DIR', 'WORKDIR', 'TOOLS_DIR', 'GO_VERSION', 'DEBUG_PORT'):
    argv += ['--env', f'{key}={os.environ[key]}']
encoded = base64.b64encode(json.dumps(['dap']).encode()).decode()
argv += ['--env', f'DEBUG_ARGS_BASE64={encoded}', '--', '/bin/bash', str(directory / 'dev.sh'), '_linux']
with socket.socket() as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', port))
    server.listen(1)
    print(f'DAP bridge listening at 127.0.0.1:{port}; waiting for Linux Delve.', flush=True)
    remote = subprocess.Popen(argv)
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
                while selector.get_map():
                    for key, _ in selector.select():
                        if key.fileobj is connection:
                            data = connection.recv(65536)
                            if not data:
                                connector.stdin.close()
                                selector.unregister(connection)
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
                            else:
                                connection.sendall(data)
    except (KeyboardInterrupt, BrokenPipeError, ConnectionResetError):
        pass
    finally:
        for child in (connector, remote):
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
