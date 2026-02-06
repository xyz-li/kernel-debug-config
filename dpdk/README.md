# dpdk and vpp

## 1. 设置hugepage
```bash
echo 512 > /proc/sys/vm/nr_hugepages
cat /proc/meminfo  |grep Huge
```
## 2. vpp startup.conf
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

## 3. 启动vpp
```bash
bin/vpp -c startup.conf
```
## 4. 设置interface IP state
```
set interface state GigabitEthernet0/2/0 up
set interface ip address  GigabitEthernet0/2/0 192.168.65.5/24
```

## 5. 从host主机上ping vpp 接口IP
