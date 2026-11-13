# dpdk and vpp

以下是 Linux 上的构建与专用 PCI 网卡实验笔记，需要已经 clone DPDK / VPP 源码。`0000:00:02.0`、接口名和二进制路径均为示例，执行前按实际设备与构建结果替换；网卡绑定会把设备交给用户态程序，应选择专用测试设备。

## 1. BUILD dpdk
```bash
apt install python3-pyelftools

cd /path/to/dpdk
# ARM / 通用平台；始终留在源码根目录，usertools 路径才有效
meson setup build -Dplatform=generic

ninja -C build
sudo meson install -C build
sudo ldconfig

sudo modprobe vfio-pci
python3 ./usertools/dpdk-devbind.py --status
sudo python3 ./usertools/dpdk-devbind.py -b vfio-pci 0000:00:02.0
```

绑定驱动与下文 VPP 的 `uio-driver vfio-pci` 保持一致。VFIO 需要满足设备及 IOMMU group 条件；并非所有 PMD 都需要解绑内核驱动，具体要求见 [DPDK Linux Drivers](https://doc.dpdk.org/guides/linux_gsg/linux_drivers.html)。

## 2. BUILD VPP
```bash
apt-get install ninja-build clang llvm python3 python3-pip python3-setuptools pkg-config  python3-ply meson debhelper libpcap-dev libcap-dev libbpf-dev

cd /path/to/vpp
make install-ext-deps
make build VPP_USE_DPDK=1 VPP_ENABLE_LTO=n
```
## 3. 设置hugepage
```bash
echo 512 > /proc/sys/vm/nr_hugepages
cat /proc/meminfo  |grep Huge
```

页数需结合 `Hugepagesize` 和 VPP 的 `socket-mem` 计算；例如每页 2 MiB 时 512 页为 1 GiB，ARM64 上不要直接假定页大小。

## 4. vpp startup.conf
```
unix {
  interactive
}

api-trace {
  on
}

dpdk {
  dev 0000:00:02.0 {
  	num-rx-queues 1
  	num-tx-queues 1
  }

  socket-mem 1024
  uio-driver vfio-pci
}

memory {
  main-heap-size 1G
}

cpu {
  # main-core 1
  # corelist-workers 2-3,18-19
}

plugins {
  # 使用当前 VPP 二进制的默认插件目录，避免引用其他用户/构建的绝对路径
  plugin dpdk_plugin.so { enable }
  plugin unittest_plugin.so { enable }
}


statseg {
  size 32m
}
```

## 5. 启动vpp
```bash
sudo /path/to/vpp/build-root/install-vpp_debug-native/vpp/bin/vpp -c /path/to/startup.conf
```
## 6. 设置interface IP state
```
set interface state GigabitEthernet0/2/0 up
set interface ip address  GigabitEthernet0/2/0 192.0.2.5/24
```

## 7. 从 host 主机上 ping VPP 接口 IP

需要与 VPP 网卡相连的对端接口或测试网络，以及正确的双向路由；给 VPP 接口配置 IP 并不会自动在 host 上创建对应链路。
