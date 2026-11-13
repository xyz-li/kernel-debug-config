#!/usr/bin/env python3
"""Keep the Guest UART on its own PTY, separate from GDB's MI channel."""
import argparse
import os
from pathlib import Path
import pty
import select
import selectors
import signal
import socket
import sys
import termios
import tty


def serve(path, tty_file, log_file):
    master, slave = pty.openpty()
    tty.setraw(slave)
    os.set_blocking(master, False)
    client = None
    history = bytearray()
    outbound = bytearray()
    inbound = bytearray()
    bound = False

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        with socket.socket(socket.AF_UNIX) as server, selectors.DefaultSelector() as selector, open(log_file, 'wb', buffering=0) as log:
            server.bind(path)
            bound = True
            os.chmod(path, 0o600)
            server.listen(1)
            server.setblocking(False)
            selector.register(server, selectors.EVENT_READ)
            selector.register(master, selectors.EVENT_READ)
            Path(tty_file).write_text(os.ttyname(slave) + '\n')
            os.chmod(tty_file, 0o600)
            while True:
                for key, events in selector.select():
                    if key.fileobj is server:
                        connection, _ = server.accept()
                        if client is not None:
                            connection.close()
                            continue
                        client = connection
                        client.setblocking(False)
                        outbound = bytearray(history)
                        selector.register(client, selectors.EVENT_READ | (selectors.EVENT_WRITE if outbound else 0))
                    elif key.fileobj == master:
                        if events & selectors.EVENT_READ:
                            data = os.read(master, 65536)
                            log.write(data)
                            history.extend(data)
                            del history[:-65536]
                            if client is not None:
                                outbound.extend(data)
                        if events & selectors.EVENT_WRITE:
                            del inbound[:os.write(master, inbound)]
                        selector.modify(master, selectors.EVENT_READ | (selectors.EVENT_WRITE if inbound else 0))
                    elif key.fileobj is client:
                        disconnected = False
                        try:
                            if events & selectors.EVENT_READ:
                                data = client.recv(65536)
                                if not data:
                                    disconnected = True
                                else:
                                    inbound.extend(data)
                                    selector.modify(master, selectors.EVENT_READ | selectors.EVENT_WRITE)
                            if events & selectors.EVENT_WRITE and outbound:
                                del outbound[:client.send(outbound)]
                        except (BrokenPipeError, ConnectionResetError):
                            disconnected = True
                        if disconnected:
                            selector.unregister(client)
                            client.close()
                            client = None
                            outbound.clear()
                    if client is not None:
                        # A slow terminal must never stall the Guest UART.
                        if len(outbound) > 1024 * 1024:
                            selector.unregister(client)
                            client.close()
                            client = None
                            outbound.clear()
                        else:
                            selector.modify(client, selectors.EVENT_READ | (selectors.EVENT_WRITE if outbound else 0))
    except KeyboardInterrupt:
        pass
    finally:
        if client is not None:
            client.close()
        os.close(master)
        os.close(slave)
        if bound:
            Path(path).unlink(missing_ok=True)
            Path(tty_file).unlink(missing_ok=True)


def connect(path):
    old = termios.tcgetattr(0) if os.isatty(0) else None
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.connect(path)
            print('Guest console: Ctrl+] disconnects; the VM keeps running.', file=sys.stderr, flush=True)
            if old is not None:
                tty.setraw(0)
            while True:
                ready, _, _ = select.select([connection, 0], [], [])
                if connection in ready:
                    data = connection.recv(65536)
                    if not data:
                        return
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
                if 0 in ready:
                    data = os.read(0, 4096)
                    if not data:
                        return
                    before_escape, separator, _ = data.partition(b'\x1d')
                    if before_escape:
                        connection.sendall(before_escape)
                    if separator:
                        return
    finally:
        if old is not None:
            termios.tcsetattr(0, termios.TCSADRAIN, old)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('serve', 'connect'))
    parser.add_argument('socket')
    parser.add_argument('--tty-file')
    parser.add_argument('--log')
    args = parser.parse_args()
    if args.command == 'serve':
        if not args.tty_file or not args.log:
            parser.error('serve needs --tty-file and --log')
        serve(args.socket, args.tty_file, args.log)
    else:
        try:
            connect(args.socket)
        except OSError as error:
            raise SystemExit(f'Console unavailable: {error}; start the VM first.')


if __name__ == '__main__':
    main()
