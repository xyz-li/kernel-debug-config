FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
# Apple Container machine starts /sbin/init; the bare Ubuntu image lacks it.
RUN apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        systemd-sysv dbus bash ca-certificates curl python3 file coreutils \
        util-linux e2fsprogs squashfs-tools iproute2 iptables gdb openssh-client \
        build-essential linux-libc-dev cmake perl pkg-config musl-tools git libclang-dev \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends libseccomp-dev gperf \
    && rm -rf /var/lib/apt/lists/*
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
