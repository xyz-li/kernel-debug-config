FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
COPY ubuntu.sources /etc/apt/sources.list.d/
RUN sed -i 's|https://ports.ubuntu.com|http://ports.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends ca-certificates \
    && sed -i 's|http://ports.ubuntu.com|https://ports.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
        build-essential bc bison flex libelf-dev libssl-dev libncurses-dev \
        rsync git python3 xz-utils cpio kmod util-linux procps file gdb-multiarch qemu-system-arm \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /kernel
CMD ["sleep", "infinity"]
