FROM ubuntu:24.04

# 设置非交互式安装
ENV DEBIAN_FRONTEND=noninteractive

# 使用带签名校验的 Ubuntu 官方 HTTPS 源。
COPY ubuntu.sources /etc/apt/sources.list.d/

RUN sed -i 's|https://ports.ubuntu.com|http://ports.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o APT::Update::Error-Mode=any update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends ca-certificates \
    && sed -i 's|http://ports.ubuntu.com|https://ports.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources

# 安装编译 Linux 内核所需的工具
RUN apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 update && apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
    build-essential \
    libncurses-dev \
    bison \
    flex \
    libssl-dev \
    libelf-dev \
    bc \
    kmod \
    cpio \
    rsync \
    git \
    wget \
    xz-utils \
    curl \
    ca-certificates \
    gdb-multiarch \
    qemu-system-arm \
    gcc-aarch64-linux-gnu \
    python3 \
    file \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /kernel

# 默认命令
CMD ["/bin/bash"]
