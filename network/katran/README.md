# katran学习
## 1 编译

这是 Linux 上的源码构建笔记，不包含完整的网卡、测试后端和流量拓扑配置。

### 1.1 编译安装liburing
```bash
sudo apt remove liburing-dev -y  #删除集版本
git clone https://github.com/axboe/liburing.git
cd liburing
./configure
make -j$(nproc)
sudo make install
```


### 1.2 build katran
```bash
cd /path/to/katran
./build_katran.sh
```
