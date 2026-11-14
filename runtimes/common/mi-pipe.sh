#!/usr/bin/env bash
# Only GDB/MI owns stdin. MIEngine's auxiliary commands inherit the adapter's
# DAP input, so forwarding their stdin can steal requests or alter its flags.
# Main call: gdb-host.sh --interpreter=mi. Auxiliary call: "kill -5 <PID>".
prepare_mi_pipe() {
    MI_PIPE_FLAGS=()
    local argument
    for argument in "$@"; do
        if [[ "$argument" == --interpreter=mi* ]]; then
            MI_PIPE_FLAGS=(--interactive)
            return
        fi
    done
    exec </dev/null
}
