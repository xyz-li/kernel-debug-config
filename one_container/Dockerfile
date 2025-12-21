# Linux Kernel Development Environment
FROM ubuntu:24.04

# 设置非交互模式，避免安装过程中的提示
ENV DEBIAN_FRONTEND=noninteractive
# 更换为国内镜像源（阿里云）以加速下载
COPY ubuntu.sources /etc/apt/sources.list.d/

# 更新包列表并安装内核编译所需的工具
RUN apt-get update && apt-get install -y \
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
