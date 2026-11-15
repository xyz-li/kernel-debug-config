FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
COPY ubuntu.sources /etc/apt/sources.list.d/
RUN sed -i 's|https://ports.ubuntu.com|http://ports.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && sed -i 's|http://ports.ubuntu.com|https://ports.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends build-essential ninja-build \
        python3 python3-venv python3-packaging pkg-config libglib2.0-dev \
        libslirp-dev libfdt-dev zlib1g-dev gdb-multiarch git rsync curl xz-utils \
        e2fsprogs procps util-linux \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends python3-setuptools python3-wheel \
    && rm -rf /var/lib/apt/lists/*
CMD ["sleep", "infinity"]
