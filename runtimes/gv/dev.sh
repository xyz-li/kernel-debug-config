#!/usr/bin/env bash
set -Eeuo pipefail
DEBUG_KIND=gvisor
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/common/config.sh"

build() {
    need_source
    [[ -f "$SOURCE_DIR/.bazelversion" ]] || die 'Expected the upstream gVisor Bazel checkout.'
    cd "$SOURCE_DIR"
    local bazel=(bazelisk --output_user_root="$WORKDIR/bazel" --host_jvm_args=-Xmx1536m)
    # Keep Go optimizations for nosplit stack limits, but preserve call frames and DWARF.
    local build_flags=(-c fastbuild --strip=never --@io_bazel_rules_go//go/config:gc_goopts=-l)
    "${bazel[@]}" build "${build_flags[@]}" --jobs="$JOBS" --symlink_prefix="$WORKDIR/links/" //:release
    local output
    output=$("${bazel[@]}" info "${build_flags[@]}" bazel-bin)
    # Current gVisor requires the adjacent gvisor-bin sidecars, including Sentry.
    [[ -d "$output/release" ]] || die 'The checkout must provide the upstream //:release layout.'
    # Bazel outputs are read-only; replace installed files instead of writing through them.
    cp -aL --remove-destination "$output/release/." "$BIN_DIR/"
    git rev-parse HEAD > "$BIN_DIR/source.commit"
    file "$BIN_DIR/runsc"
}

if [[ ${1:-} == _linux ]]; then
    shift
    decode_args "$@"
    set -- "${DECODED_ARGS[@]}"
    linux_init
    command=${1:-help}; shift || true
    case "$command" in
        setup)
            exec 9> "$TOOLS_DIR/setup.lock"
            flock 9
            setup_packages; setup_go ;;
        doctor) doctor ;;
        build) build ;;
        dap|attach)
            if [[ "$command" == attach ]]; then
                [[ $# == 1 && $1 =~ ^[1-9][0-9]*$ ]] || die 'Usage: dev.sh attach LINUX_PID'
                [[ -d /proc/$1 ]] || die "Linux PID $1 has exited; run dev.sh ps again."
            fi
            exec python3 "$DEBUG_COMMON/dlv_server.py" "$WORKDIR" "$DEBUG_PORT" "$command" "$@" ;;
        run)
            [[ -x "$BIN_DIR/runsc" ]] || die 'Run dev.sh build first.'
            exec "$BIN_DIR/runsc" --root="$WORKDIR/state" --platform=systrap "$@" ;;
        ps)
            # Match sandbox/gofer command lines, excluding platform helpers and this filter.
            ps -eo pid,ppid,stat,comm,args | awk 'NR==1 || $5=="runsc-sandbox" || $5=="runsc-gofer" || ($4=="runsc" && / (boot|gofer)( |$)/)'
            ;;
        *) die 'Unknown Linux command.' ;;
    esac
    exit
fi

case ${1:-help} in
    bind) python3 "$DEBUG_COMMON/bind.py" gv "${2:?Usage: dev.sh bind /path/to/gvisor}" ;;
    setup|doctor|build|run|ps) remote "$@" ;;
    dap)
        export MACHINE DEBUG_PORT
        if [[ $(uname -s) == Darwin ]]; then exec python3 "$DEBUG_COMMON/dap_bridge.py"; fi
        remote dap ;;
    attach)
        [[ $# == 2 && $2 =~ ^[1-9][0-9]*$ ]] || die 'Usage: dev.sh attach LINUX_PID'
        export MACHINE DEBUG_PORT
        if [[ $(uname -s) == Darwin ]]; then exec python3 "$DEBUG_COMMON/dap_bridge.py" --attach "$2"; fi
        remote "$@" ;;
    *) cat <<'EOF'
Usage: ./dev.sh COMMAND
  bind PATH      Bind an existing google/gvisor checkout; generate local workspace
  setup          Install Ubuntu dependencies, official Go, Delve and Bazelisk
  doctor         Check source and tools
  build          Bazel debug build of //:release, including gvisor-bin sidecars
  dap            Start Linux Delve DAP and macOS loopback forwarding (also started by F5)
  attach PID     Attach Linux Delve to PID and forward its debug server (also started by F5)
  run ARGS...    Run the built runsc with an isolated state directory
  ps             Show Linux Sentry/Gofer PIDs for attaching
EOF
    ;;
esac
