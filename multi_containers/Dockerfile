FROM ubuntu:24.04

# 设置非交互式安装
ENV DEBIAN_FRONTEND=noninteractive

# 更换为国内镜像源（阿里云）以加速下载
COPY ubuntu.sources  /etc/apt/sources.list.d/ubuntu.sources

# 安装编译 Linux 内核所需的工具
RUN apt-get update  --allow-unauthenticated && apt-get install  --allow-unauthenticated -y \
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
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /kernel

# 默认命令
CMD ["/bin/bash"]
