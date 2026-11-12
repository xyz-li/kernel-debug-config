#!/usr/bin/env bash
set -Eeuo pipefail
DEBUG_KIND=gvisor
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/common/config.sh"

build() {
    need_source
    [[ -f "$SOURCE_DIR/.bazelversion" ]] || die 'Expected the upstream gVisor Bazel checkout.'
    cd "$SOURCE_DIR"
    local bazel=(bazelisk --output_user_root="$WORKDIR/bazel" --host_jvm_args=-Xmx1536m)
    "${bazel[@]}" build -c dbg --strip=never --jobs="$JOBS" --symlink_prefix="$WORKDIR/links/" //:release
    local output
    output=$("${bazel[@]}" info -c dbg bazel-bin)
    # Current gVisor requires the adjacent gvisor-bin sidecars, including Sentry.
    [[ -d "$output/release" ]] || die 'The checkout must provide the upstream //:release layout.'
    cp -aL "$output/release/." "$BIN_DIR/"
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
        dap)
            exec 9> "$WORKDIR/dap.lock"
            flock -n 9 || die 'Another Delve DAP server is active.'
            exec dlv dap --listen="127.0.0.1:$DEBUG_PORT" ;;
        run)
            [[ -x "$BIN_DIR/runsc" ]] || die 'Run dev.sh build first.'
            exec "$BIN_DIR/runsc" --root="$WORKDIR/state" "$@" ;;
        ps) ps -eo pid,comm,args | awk 'NR==1 || /gvisor_sentry|runsc.*boot|runsc.*gofer/' ;;
        *) die 'Unknown Linux command.' ;;
    esac
    exit
fi

case ${1:-help} in
    bind) python3 "$DEBUG_COMMON/bind.py" gvisor "${2:?Usage: dev.sh bind /path/to/gvisor}" ;;
    setup|doctor|build|run|ps) remote "$@" ;;
    dap)
        export MACHINE DEBUG_PORT
        if [[ $(uname -s) == Darwin ]]; then exec python3 "$DEBUG_COMMON/dap_bridge.py"; fi
        remote dap ;;
    *) cat <<'EOF'
Usage: ./dev.sh COMMAND
  bind PATH      Bind an existing google/gvisor checkout; generate local workspace
  setup          Install Ubuntu dependencies, official Go, Delve and Bazelisk
  doctor         Check source and tools
  build          Bazel debug build of //:release, including gvisor-bin sidecars
  dap            Start Linux Delve DAP and macOS loopback forwarding (then F5)
  run ARGS...    Run the built runsc with an isolated state directory
  ps             Show Linux Sentry/Gofer PIDs for attaching
EOF
    ;;
esac
