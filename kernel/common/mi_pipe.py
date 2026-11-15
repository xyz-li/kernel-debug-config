"""Translate debugger control commands for a managed QEMU system target."""
from pathlib import Path
import shlex


def pipe_command(arguments):
    if len(arguments) == 1:
        arguments = shlex.split(arguments[0])
    interactive = any(argument.startswith('--interpreter=mi') for argument in arguments)
    if arguments and Path(arguments[0]).name == 'kill':
        if (len(arguments) != 3 or arguments[1] not in ('-5', '-2', '-SIGTRAP', '-SIGINT') or
                not arguments[2].isdigit() or int(arguments[2]) < 1):
            raise ValueError('Unsupported debugger interrupt command')
        # The stub PID is virtual. A nonzero exit makes MIEngine fall back to
        # -exec-interrupt and recognize SIGINT as its own internal pause. A
        # successful QMP stop instead looks like an unrelated exception and
        # prevents automatic resume after changing breakpoints.
        return ['/bin/false'], False
    return arguments, interactive
