# 容器化 Linux 内核开发与调试环境

本文档介绍如何使用容器化环境进行 Linux 内核编译、initramfs 生成和 VSCode Remote 调试。

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    Host Machine (macOS/Linux)               │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │          Docker Container: kernel-dev                │   │
│  │                                                      │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │   │
│  │  │ Kernel Build │  │   QEMU VM    │  │ GDB Server │  │   │
│  │  │              │  │              │  │ :1234      │  │   │
│  │  │ /kernel      │  │ Linux Kernel │  │            │  │   │
│  │  │ /output      │  │ + initramfs  │  │            │  │   │
│  │  └──────────────┘  └──────────────┘  └────────────┘  │   │
│  │                                                      │   │
│  └──────────────────────────────────────────────────────┘   │
│                           ▲                                 │
│                           │                                 │
│                  ┌────────┴──────────┐                      │
│                  │  VSCode Remote    │                      │
│                  │  Debugging        │                      │
│                  └───────────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

## 环境组件

### 1. kernel-dev 容器（Ubuntu 24.04）
- **功能**: 编译内核、运行 QEMU、GDB 调试
- **包含工具**:
  - 内核编译工具链（gcc, make, etc.）
  - QEMU（qemu-system-aarch64）
  - GDB（gdb-multiarch）
- **挂载点**:
  - `/kernel`: 内核源码（只读或读写）
  - `/output`: 编译输出（vmlinux, Image, modules）
  - `/scripts`: 辅助脚本

### 2. initramfs-builder 容器（Alpine Linux）
- **功能**: 生成 initramfs 文件系统
- **包含工具**:
  - iptables, iproute2, kmod, busybox
  - 调试工具（strace, tcpdump, curl）

## 完整工作流程

### 步骤 1: 启动容器环境

```bash
# 构建镜像（首次或 Dockerfile 更新后）
docker compose build

# 启动 kernel-dev 容器
docker compose up -d kernel-dev

# 查看容器状态
docker compose ps
```

### 步骤 2: 使用 VSCode Remote 连接容器

1. 安装 VSCode 扩展：
   - **Dev Containers** (ms-vscode-remote.remote-containers)
   - **C/C++** (ms-vscode.cpptools)

2. 连接到容器：
   - 按 `F1` 或 `Cmd+Shift+P`
   - 选择 `Dev Containers: Attach to Running Container...`
   - 选择 `kernel-dev` 容器

3. 打开工作目录：
   - 在容器内打开 `/kernel` 目录

### 步骤 3: 编译内核

在容器内终端或使用 VSCode 任务：

```bash
# 方法 1: 直接运行脚本
/scripts/build_kernel.sh

# 方法 2: 使用 VSCode 任务
# 按 Cmd+Shift+B -> 选择 "Build Kernel"
```

编译输出：
- `/output/Image` - 内核镜像
- `/output/vmlinux` - 带调试符号的内核（用于 GDB）
- `/output/rootfs/lib/modules/` - 内核模块

### 步骤 4: 生成 initramfs

```bash
# 从主机运行（推荐）
docker compose run --rm initramfs-builder /scripts/build_initramfs.sh

# 或使用 VSCode 任务
# 按 F1 -> Tasks: Run Task -> "Build Initramfs (Host)"
```

输出：
- `/output/initramfs.cpio.gz` - 打包的 initramfs
- `/output/rootfs/` - 完整的根文件系统（含模块）

### 步骤 5: 启动 QEMU 虚拟机

在容器内启动 QEMU（带 GDB 调试支持）：

```bash
# 方法 1: 直接运行脚本
/scripts/start_qemu_debug.sh

# 方法 2: 使用 VSCode 任务（后台运行）
# 按 F1 -> Tasks: Run Task -> "Start QEMU"
```

QEMU 配置：
- 监听端口：`1234`（GDB remote debugging）
- 启动参数：`-S`（暂停启动，等待 GDB 连接）
- 串口输出：`-nographic -serial stdio`

### 步骤 6: 使用 VSCode 调试内核

1. **确保 QEMU 已启动并等待 GDB 连接**

2. **设置断点**（可选）：
   - 打开 `init/main.c`
   - 在 `start_kernel` 函数处设置断点

3. **启动调试**：
   - 按 `F5` 或点击调试面板的 "Kernel Debug (GDB)"
   - VSCode 会自动：
     - 加载符号文件（`/output/vmlinux`）
     - 连接到 QEMU（`localhost:1234`）
     - 停在入口点或断点处

4. **调试操作**：
   - `F5`: 继续执行（Continue）
   - `F10`: 单步跳过（Step Over）
   - `F11`: 单步进入（Step Into）
   - `Shift+F11`: 跳出函数（Step Out）
   - 查看变量、调用栈、寄存器等

### 步骤 7: 停止 QEMU

```bash
# 方法 1: 在 QEMU 终端按 Ctrl+C

# 方法 2: 使用 VSCode 任务
# 按 F1 -> Tasks: Run Task -> "Stop QEMU"

# 方法 3: 手动 kill
pkill qemu-system-aarch64
```

## VSCode 调试配置说明

### launch.json 关键配置

```json
{
    "name": "Kernel Debug (GDB)",
    "type": "cppdbg",
    "miDebuggerPath": "/usr/bin/gdb-multiarch",
    "miDebuggerServerAddress": "localhost:1234",
    "program": "${workspaceFolder}/output/vmlinux",
    "preLaunchTask": "Start QEMU"
}
```

- `miDebuggerPath`: GDB 路径（容器内）
- `miDebuggerServerAddress`: QEMU GDB 服务器地址
- `program`: 带符号的内核文件
- `preLaunchTask`: 启动调试前自动运行 QEMU

### tasks.json 可用任务

| 任务名称 | 描述 |
|---------|------|
| `Build Kernel` | 编译内核和模块 |
| `Build Initramfs (Host)` | 生成 initramfs（需主机 Docker） |
| `Start QEMU` | 后台启动 QEMU（带 GDB） |
| `Stop QEMU` | 停止 QEMU 进程 |
| `Full Build` | 完整构建（内核 + initramfs） |

## 调试技巧

### 1. 常用 GDB 命令

```gdb
# 设置断点
break start_kernel
break do_fork

# 查看调用栈
backtrace

# 查看变量
print current
print *current

# 查看内存
x/10i $pc           # 查看当前 10 条指令
x/10x 0xffff800000000000  # 查看内存内容

# 查看寄存器
info registers
info registers all

# 单步执行
step    # 进入函数
next    # 跳过函数
finish  # 执行到函数返回
```

### 2. 内核特定调试

```gdb
# 查看当前进程
lx-ps

# 查看内核日志
lx-dmesg

# 查看符号地址
info address start_kernel

# 监视点（硬件断点）
watch global_variable
```

### 3. QEMU 控制台命令

如果 QEMU 使用 monitor 模式（`-monitor stdio`）：

```
info registers    # 查看 CPU 寄存器
info mem          # 查看内存映射
info mtree        # 查看内存树
savevm <name>     # 保存虚拟机状态
loadvm <name>     # 恢复虚拟机状态
```

## 常见问题

### 1. 无法连接到 QEMU GDB 服务器

**问题**: VSCode 提示 "Unable to connect to localhost:1234"

**解决方案**:
```bash
# 检查 QEMU 是否在运行
ps aux | grep qemu

# 检查端口是否监听
netstat -tlnp | grep 1234  # Linux
lsof -i :1234              # macOS

# 重启 QEMU
/scripts/start_qemu_debug.sh
```

### 2. 符号无法加载

**问题**: GDB 提示 "No debugging symbols found"

**解决方案**:
```bash
# 确认 vmlinux 存在且包含调试符号
file /output/vmlinux
readelf -S /output/vmlinux | grep debug

# 重新编译内核（启用调试符号）
export DEBUG_BUILD=yes
/scripts/build_kernel.sh
```

### 3. 断点无法命中

**问题**: 设置的断点不生效

**可能原因**:
- 代码被优化（-O2）导致函数内联
- 符号文件与运行的内核不匹配
- 内核尚未加载到该模块

**解决方案**:
```bash
# 检查内核版本是否匹配
uname -r  # QEMU 内
cat /kernel/.config | grep CONFIG_LOCALVERSION

# 使用条件断点
break start_kernel if some_condition
```

### 4. QEMU 启动失败

**问题**: QEMU 报错无法启动

**检查**:
```bash
# 检查文件是否存在
ls -lh /output/Image
ls -lh /output/initramfs.cpio.gz

# 手动启动 QEMU 查看详细错误
qemu-system-aarch64 \
  -machine virt -cpu cortex-a57 \
  -kernel /output/Image \
  -initrd /output/initramfs.cpio.gz \
  -nographic -s -S
```

## 快速开始检查清单

- [ ] 已安装 Docker 和 Docker Compose
- [ ] 已安装 VSCode + Dev Containers 扩展
- [ ] 已克隆内核源码到 `/Volumes/linux/linux-6.12.63`
- [ ] 已构建 Docker 镜像：`docker compose build`
- [ ] 已启动容器：`docker compose up -d kernel-dev`
- [ ] VSCode 已连接到 `kernel-dev` 容器
- [ ] 已编译内核：`/scripts/build_kernel.sh`
- [ ] 已生成 initramfs：`docker compose run --rm initramfs-builder /scripts/build_initramfs.sh`
- [ ] 已启动 QEMU：`/scripts/start_qemu_debug.sh`
- [ ] 按 F5 开始调试

## 环境变量参考

### docker-compose.yml 环境变量

| 变量名 | 默认值 | 描述 |
|-------|--------|------|
| `ARCH` | `arm64` | 目标架构 |
| `JOBS` | `8` | 并行编译任务数 |
| `OUTPUT_DIR` | `/output` | 输出目录 |
| `ROOTFS_DIR` | `/output/rootfs` | 根文件系统目录 |
| `KERNEL_IMAGE` | `/output/Image` | 内核镜像路径 |
| `INITRAMFS` | `/output/initramfs.cpio.gz` | initramfs 路径 |
| `GDB_PORT` | `1234` | GDB 调试端口 |

### build_kernel.sh 环境变量

| 变量名 | 默认值 | 描述 |
|-------|--------|------|
| `FORCE_RECONFIG` | `no` | 强制重新配置内核 |
| `DEBUG_BUILD` | `yes` | 启用调试优化 |
| `COPY_DTB` | `no` | 复制设备树文件 |

## 项目文件结构

```
/Users/qmk/project/linux/
├── Dockerfile                    # 内核开发容器镜像
├── Dockerfile.initramfs          # initramfs 构建容器镜像
├── docker-compose.yml            # 容器编排配置
├── build_kernel.sh               # 内核编译脚本
├── build_initramfs.sh            # initramfs 生成脚本
├── start_qemu_debug.sh           # QEMU 启动脚本
├── minimal_debug.config          # 内核最小调试配置
├── .vscode/
│   ├── launch.json               # VSCode 调试配置
│   └── tasks.json                # VSCode 任务配置
└── output/
    ├── Image                     # 内核镜像
    ├── vmlinux                   # 带符号的内核
    ├── initramfs.cpio.gz         # initramfs 文件
    └── rootfs/                   # 根文件系统
        └── lib/modules/          # 内核模块
```

## 下一步

- 尝试调试内核启动过程（`start_kernel`）
- 添加自定义驱动并调试
- 使用 ftrace/kprobe 进行高级调试
- 集成 CI/CD 自动化构建

## 参考资料

- [Linux Kernel Debugging](https://www.kernel.org/doc/html/latest/dev-tools/gdb-kernel-debugging.html)
- [QEMU Documentation](https://www.qemu.org/docs/master/)
- [VSCode C++ Debugging](https://code.visualstudio.com/docs/cpp/cpp-debug)
- [GDB Manual](https://sourceware.org/gdb/documentation/)
