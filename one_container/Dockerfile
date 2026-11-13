# Linux Kernel Development Environment
FROM ubuntu:24.04

# 设置非交互模式，避免安装过程中的提示
ENV DEBIAN_FRONTEND=noninteractive
# 使用带签名校验的 Ubuntu 官方 HTTPS 源。
COPY ubuntu.sources /etc/apt/sources.list.d/

# Bare Ubuntu has no CA bundle: bootstrap it over signed APT, then use HTTPS.
RUN sed -i 's|https://ports.ubuntu.com|http://ports.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o APT::Update::Error-Mode=any update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends ca-certificates \
    && sed -i 's|http://ports.ubuntu.com|https://ports.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources

# 更新包列表并安装内核编译所需的工具
RUN apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 update && apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
    # 基础编译工具
    build-essential \
    gcc \
    g++ \
    make \
    cmake \
    # 内核编译必需工具
    bc \
    bison \
    flex \
    libelf-dev \
    libssl-dev \
    libncurses-dev \
    # 交叉编译工具链
    gcc-aarch64-linux-gnu \
    gcc-arm-linux-gnueabihf \
    # QEMU 虚拟化和调试
    qemu-system-arm \
    qemu-system-x86 \
    qemu-system-aarch64 \
    qemu-utils \
    # 调试工具
    gdb \
    gdb-multiarch \
    python3 \
    xz-utils \
    # 版本控制和编辑器
    git \
    vim \
    nano \
    # 文件系统工具
    cpio \
    initramfs-tools \
    kmod \
    # 其他实用工具
    wget \
    curl \
    rsync \
    tree \
    file \
    patchutils \
    diffstat \
    && rm -rf /var/lib/apt/lists/*

# 创建必要的目录
RUN mkdir -p /kernel /output /scripts

# 设置工作目录
WORKDIR /kernel

# 设置默认 shell
SHELL ["/bin/bash", "-c"]

# 默认命令
CMD ["/bin/bash"]
