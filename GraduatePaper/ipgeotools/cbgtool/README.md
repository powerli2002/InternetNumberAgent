# CBG定位工具 (CBGLocTool)

CBG定位工具是一个基于约束边界地理定位(Constraint-Based Geolocation)方法的IP地理定位工具，能够通过网络测量数据推断IP地址的地理位置。

## 注意事项

1. 确保ipinfo API密钥有效，或根据需要更换为其他地理位置API。
2. 免费逆地理编码服务需要代理，同时处理时间较长。


## 功能介绍

该工具包含三个主要模块：

1. **数据预处理器(Preprocesser)**: 将原始测量数据转换为标准格式，包括探针(probes)和锚点(anchors)的JSON文件以及ping测量结果。

2. **数据集创建器(DatasetCreator)**: 处理标准格式数据，生成目标IP列表、距离矩阵。

3. **CBG定位工具(CBGTool)**: 使用多种定位算法计算目标IP的地理位置，包括：
   - 原始CBG方法
   - NCR(最近公共路由器)方法
   - NCR-CBG混合方法

## 安装与依赖

创建环境并安装依赖：
```bash
conda create -n cbg python=3.8
cd /home/cbgtool
pip install -r requirements.txt
```

## 使用方法

### 准备数据

将原始数据文件放置在`data/raw/`目录下，文件名格式为`tmp_ip_anl_geo_ping_YYYYMMDD.csv`。

原始数据格式应为：
```
anchor_ad, probe_ad, rtt, ttl, region, label
```
其中：
- anchor_ad: 被探测IP地址
- probe_ad: 探测点IP地址
- rtt: 往返时间(ms)
- ttl: 生存时间
- region: 探测点区域
- label: 序号

### 命令行参数

基本参数：
- `--date`, `-d`: 指定数据日期，格式为YYYYMMDD
- `--limit`, `-l`: 探针数量限制，默认为1000

主要命令（互斥，必须选择一个）：
- `--preprocess`, `-p`: 仅运行数据预处理
- `--create`, `-c`: 仅运行数据集创建
- `--locate`, `-loc`: 仅运行CBG定位工具
- `--auto`, `-a`: 自动运行完整流程

### 运行示例

1. 数据预处理：
```bash
python setup.py -p -d 20241213
# 或
python setup.py --preprocess --date 20241213
```

2. 数据集创建：
```bash
python setup.py -c
# 或
python setup.py --create
```

3. CBG定位：
```bash
python setup.py -loc
# 或
python setup.py --locate
```

4. 自动运行完整流程：
```bash
python setup.py -a -d 20241213
# 或
python setup.py --auto --date 20241213
```

## 输出结果

所有结果保存在`data/output`目录下：

- `user_result_loc_ori.json`: 原始CBG方法的定位结果
- `user_result_loc_ncr.json`: NCR方法的定位结果
- `user_result_loc_ncr_ori.json`: NCR-CBG混合方法的定位结果

每个结果文件包含以下信息：
- 目标IP
- 定位误差(km)
- 预测位置的经纬度
- 实际位置的经纬度
- 计算得到的delta(如果存在)
- 逆地理编码后预测位置的省份
- 逆地理编码后实际位置的省份

## 工作流程

1. **数据预处理**:
   - 从原始数据生成探针和锚点的JSON文件
   - 生成ping测量结果CSV文件

2. **数据集创建**:
   - 加载探针和锚点数据
   - 生成目标IP列表
   - 计算距离矩阵
   - 贪婪选择探针

3. **CBG定位**:
   - 加载位置缓存
   - 使用多种算法进行定位
   - 保存定位结果

## 算法说明

### CBG方法
基于延迟测量和三角定位原理，通过多个探测点的延迟测量来约束目标IP的可能位置。
具体逻辑；
绘制所有可能的圆，取两两圆之间的交点，验证交点是否在所有的圆中。
取过滤后的交点质心。


### NCR方法

> 未使用，需设置CBGTool中 only_cbg = False
原理详解
https://alidocs.dingtalk.com/i/nodes/QOG9lyrgJPPNL2rXInDm1aPMJzN67Mw4?utm_scene=person_space

1. 简化处理：直接用目标地址T替代最近公共路由器R
2. 迭代选择三角形：
   按延迟总和排序选择三个地标点
   计算距离-延迟转换系数delta
   用delta计算目标T的位置
   验证T是否在三角形内，若在则成功，否则尝试下一组三角形
3. 定位结果产出三种版本(默认只输出ori)：
   ori：原始CBG方法（交圆质心）
   ncr：直接使用NCR方法计算的位置
   ncr_ori：当NCR迭代次数少且成功解出delta时使用NCR指导CBG，否则回退到原始CBG