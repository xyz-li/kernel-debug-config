# katran学习
## 1 编译
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
./build_katran.sh
```