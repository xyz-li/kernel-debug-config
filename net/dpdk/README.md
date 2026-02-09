# dpdk and vpp

## 1. BUILD dpdk
```bash
apt install python3-pyelftools

# arp palatform
meson setup build -Dplatform=generic

cd build
ninja
meson install
ldconfig

modprobe uio_pci_generic
# 需要使用 ./usertools/dpdk-devbind.py 
./usertools/dpdk-devbind.py -b uio_pci_generic 0000:00:02.0
```

## 2. BUILD VPP
```bash
apt-get install ninja-build clang llvm python3 python3-pip python3-setuptools pkg-config  python3-ply meson debhelper libpcap-dev libcap-dev libbpf-dev

./configure

make install-ext-deps
make build VPP_USE_DPDK=1 VPP_ENABLE_LTO=n
```
## 3. 设置hugepage
```bash
echo 512 > /proc/sys/vm/nr_hugepages
cat /proc/meminfo  |grep Huge
```
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
  # dpdk plugin dir
  path /root/vpp/build-root/install-vpp_debug-native/vpp/lib/aarch64-linux-gnu/vpp_plugins/
  plugin dpdk_plugin.so { enable }
  plugin unittest_plugin.so { enable }
}


statseg {
  size 32m
}
```

## 5. 启动vpp
```bash
bin/vpp -c startup.conf
```
## 6. 设置interface IP state
```
set interface state GigabitEthernet0/2/0 up
set interface ip address  GigabitEthernet0/2/0 192.168.65.5/24
```

## 5. 从host主机上ping vpp 接口IP
