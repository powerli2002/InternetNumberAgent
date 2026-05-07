# ScamperTrace - 智能网络路径探测工具

<div align="center">


**一个基于scamper的智能网络测量工具，支持IPv4/IPv6多策略探测和断点续传**



</div>

---

## 🚀 功能特性

### 🌐 多协议智能探测
- **IPv4 ICMP探测**: 使用icmp-paris确保路径一致性
- **IPv6多策略回退**: ICMP → TCP(80) → TCP(443)三层回退机制
- **三重探测输出**: 每个目标IP同时生成ICMP/TCP80/TCP443三条`tracetype`记录
- **智能频率控制**: 可配置的每小时探测频率限制

### 🧠 智能前缀处理
- **IPv4策略**: ≥/24选择网络地址，</24拆分为多个/24子网
- **IPv6策略**: ≥/48选择网络地址，</48拆分为多个/48子网
- **大规模优化**: 自动限制大前缀生成的IP数量，避免过载

### 🔀 Source/Device协同探测
- **双列输入**: `-sd`模式读取`source_ipv6`与`device_ipv6`，自动去重
- **角色映射**: 同一IPv6若出现在两个角色，只探测一次但输出双份记录
- **独立结果**: 自动生成`*_source_result.csv`与`*_device_result.csv`

### 📡 Ping RTT采集
- **自动补测**: 每个目标IP完成三种trace后会额外执行一次`ping`
- **严格超时**: `ping`命令以0.5秒超时执行，避免阻塞整体流程
- **统一写入**: 同一个目标的Ping RTT会同步写入对应的三条`tracetype`记录

### 💾 断点续传
- **智能恢复**: 自动检测已探测IP，避免重复探测
- **多格式支持**: 解析.jsonl、.csv、.warts等多种结果文件
- **灵活控制**: `--nocontinues`参数可禁用续传功能

### 📊 完整日志系统
- **中文输出**: 所有日志信息支持中文显示
- **时间戳文件**: 自动生成带时间戳的日志文件
- **分级记录**: 支持DEBUG、INFO、WARNING、ERROR多级日志

### ⚙️ 灵活配置
- **JSON配置**: 所有探测参数可通过配置文件调整
- **命令可配**: scamper探测命令完全可自定义
- **参数详解**: 配置文件包含详细的中文参数说明

---

## 📦 快速开始

### 方法一：一键自动部署 (推荐)

```bash
# 运行自动部署脚本

./deploy.sh
```

### 方法二：手动安装

1. **克隆项目**
```bash
git clone https://github.com/powerli2002/scampertrace.git
cd scampertrace
```

2. **创建conda环境**
```bash
conda create -n scampertrace python=3.9
conda activate scampertrace
```

3. **安装依赖**
```bash
pip install -r requirements.txt
```

4. **安装scamper**
```bash
# Ubuntu/Debian
sudo apt-get install scamper

# macOS
brew install scamper
```

---

## 🛠 安装部署

### 系统要求

| 组件 | 要求 |
|------|------|
| **操作系统** | Linux (Ubuntu 18.04+, CentOS 7+) / macOS 10.14+ |
| **Python** | 3.9+ |
| **内存** | 最小 2GB，推荐 4GB+ |
| **磁盘** | 最小 1GB 可用空间 |
| **网络** | 需要IPv6公网地址 |

### 详细安装步骤

<details>
<summary>点击展开详细安装说明</summary>

#### 1. 安装Miniconda

```bash
# Linux x86_64
curl -O https://mirrors.aliyun.com/anaconda/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh

# macOS Intel
curl -O https://mirrors.aliyun.com/anaconda/miniconda/Miniconda3-latest-MacOSX-x86_64.sh
bash Miniconda3-latest-MacOSX-x86_64.sh

# macOS Apple Silicon
curl -O https://mirrors.aliyun.com/anaconda/miniconda/Miniconda3-latest-MacOSX-arm64.sh
bash Miniconda3-latest-MacOSX-arm64.sh
```

#### 2. 配置conda镜像源

```bash
conda config --add channels https://mirrors.aliyun.com/anaconda/pkgs/main/
conda config --add channels https://mirrors.aliyun.com/anaconda/pkgs/free/
conda config --set show_channel_urls yes
```

#### 3. 创建虚拟环境

```bash
conda create -n scampertrace python=3.9
conda activate scampertrace
```

#### 4. 安装scamper

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y scamper
```

**CentOS/RHEL:**
```bash
sudo yum install -y epel-release
sudo yum install -y scamper
```

**macOS:**
```bash
brew install scamper
```

**从源码编译 (如果包管理器无法安装):**
```bash
wget https://www.caida.org/tools/measurement/scamper/code/scamper-cvs-20230323.tar.gz
tar -xzf scamper-cvs-20230323.tar.gz
cd scamper-cvs-20230323
./configure --prefix=/usr/local
make -j$(nproc)
sudo make install
sudo ldconfig  # Linux only
```

#### 5. 配置scamper权限 (推荐) 

scamper 需要sudo执行，配置权限执行：
```
./ensudo.sh
```

如果运行超时，需要考虑
1. 是否 给予了 sudo 权限，执行 ./ensudo.sh
2. 超时时间是否设置不足，在config.json 中设置 "timeout_per_ip" 增加时间。




</details>

---

## 📖 使用文档

### 基本用法

```bash
# 基本运行
python main.py

# 指定输入文件
python main.py -f custom_prefixes.csv

# 禁用断点续传
python main.py --nocontinues

# 详细输出模式
python main.py --verbose

# 探测后清理中间文件
python main.py --cleanup-warts


```

### 命令行参数

| 参数 | 简写 | 默认值 | 说明 |
|------|------|--------|------|
| `--source-file` | `-f` | prefix.csv | 输入前缀文件名 |
| `--config` | `-c` | config.json | 配置文件路径 |
| `--nocontinues` | 无 | False | 禁用断点续传功能 |
| `--cleanup-warts` | 无 | False | 探测完成后删除.warts文件 |
| `--verbose` | `-v` | False | 启用详细输出模式 |
| `--source-device` | `-sd` | False | 启用Source/Device IPv6采集模式 |
| `--help` | `-h` | 无 | 显示帮助信息 |

### 输入文件格式

支持以下CSV格式的输入文件：

**格式1: 分列格式 (推荐)**
```csv
ipv4,ipv6
192.168.1.0/24,2001:db8::/48
10.0.0.0/24;172.16.0.0/16,2408:8000::/32;2606:4700::/32
```

**格式2: 统一格式**
```csv
prefix
192.168.1.0/24
2001:db8::/48
10.0.0.0/16
```

**格式3: Source/Device模式 (`-sd`)**

当输入文件包含`source_ipv6`与`device_ipv6`列时，配合`-sd`参数可一次性探测两个角色。系统会自动对两列IPv6地址去重，避免重复探测，并记录每个地址所属角色，便于生成独立结果文件。

```csv
source_ipv6,device_ipv6
2409:8100:ca6:682:588b:c4ff:feb1:6c3d,240e:504:e20:67a0:1876:481c:c106:6247
2409:8100:ca6:682:588b:c4ff:feb1:6c3d,2409:8900:fe6:34:2830:23ff:fec9:59ac
```

**多前缀支持**: 使用分号`;`分隔多个前缀

---

## ⚙️ 配置说明

### 配置文件结构

系统首次运行时会自动生成`config.json`配置文件：

```json
{
  "scamper_commands": {
    "ipv6_icmp": {
      "command": "trace -P icmp-paris -g 30",
      "description": "IPv6 ICMP，30跳无响应后停止"
    },
    "ipv6_tcp_80": {
      "command": "trace -P tcp -d 80 -g 30", 
      "description": "IPv6 TCP追踪，目标端口80，30跳无响应后停止" 
    },
    "ipv6_tcp_443": {
      "command": "trace -P tcp -d 443 -g 30",
      "description": "IPv6 TCP追踪，目标端口443，30跳无响应后停止"
    },
    "ipv4_icmp": {
      "command": "trace -P icmp-paris -m 30 -g 30",
      "description": "IPv4 ICMP，最大30跳，30跳无响应后停止"
    }
  },
  "probe_settings": {
    "rate_limit": 100,
    "description_rate": "探测频率限制 (每小时IP地址数)",
    "max_ttl": 30,
    "description_ttl": "最大跳数限制",
    "gap_limit": 30, 
    "description_gap": "连续无响应跳数限制",
    "timeout": 30,
    "description_timeout": "单次探测超时时间(秒)"
  },
  "prefix_handling": {
    "ipv4_split_threshold": 24,
    "description_ipv4": "IPv4前缀分割阈值，/24及以上选择最小地址，小于/24的拆分到/24",
    "ipv6_split_threshold": 48,
    "description_ipv6": "IPv6前缀分割阈值，/48及以上选择最小地址，小于/48的拆分到/48",
    "log_strategy_once": true,
    "description_log": "是否只在首次读取前缀时记录IP生成策略"
  },
  "resume_settings": {
    "enable_resume": true,
    "description_resume": "是否启用断点续传功能",
    "check_existing_results": true,
    "description_check": "是否检查已有结果文件",
    "result_file_patterns": ["*.jsonl", "*.csv", "*.warts"],
    "description_patterns": "结果文件匹配模式列表"
  },
  "directories": {
    "input_dir": "data/input",
    "output_dir": "data/output",
    "logs_dir": "logs",
    "description": "各类文件存储目录配置"
  }
}
```

### 核心参数说明

| 参数类别 | 参数名 | 作用 | 建议值 |
|----------|--------|------|--------|
| **探测控制** | rate_limit | 每小时探测IP数量限制 | 100 (礼貌探测) |
| **探测控制** | timeout | 单次探测超时时间(秒) | 30 |
| **前缀处理** | ipv4_split_threshold | IPv4前缀分割阈值 | 24 |
| **前缀处理** | ipv6_split_threshold | IPv6前缀分割阈值 | 48 |
| **断点续传** | enable_resume | 是否启用断点续传 | true |

---

## 🧩 前缀处理策略

### IPv4前缀处理规则

| 前缀类型 | 处理策略 | 示例 | 输出 |
|----------|---------|------|------|
| **≥ /24** | 选择网络地址 | `192.168.1.0/24` | `192.168.1.0` (1个IP) |
| **≥ /24** | 选择网络地址 | `192.168.1.0/25` | `192.168.1.0` (1个IP) |
| **< /24** | 拆分为/24子网 | `192.168.0.0/22` | `192.168.{0,1,2,3}.0` (4个IP) |
| **< /24** | 拆分为/24子网 | `10.0.0.0/16` | `10.0.{0-255}.0` (256个IP) |

### IPv6前缀处理规则

| 前缀类型 | 处理策略 | 示例 | 输出 |
|----------|---------|------|------|
| **≥ /48** | 选择网络地址 | `2001:db8::/48` | `2001:db8::` (1个IP) |
| **≥ /48** | 选择网络地址 | `2001:db8::/64` | `2001:db8::` (1个IP) |
| **< /48** | 拆分为/48子网 | `2001:db8::/40` | `2001:db8:{0-ff}::` (256个IP) |
| **< /48** | 拆分为/48子网 | `2001:db8::/32` | `2001:db8:{0-ffff}::` (65536个IP*) |

> *注：大前缀会自动限制生成数量，IPv4限制10000个，IPv6限制50000个，避免系统过载

---

## 🔄 探测策略

### IPv4探测流程
```
IPv4地址 → ICMP Paris追踪 → 成功/失败
```

### IPv6探测流程 (三层回退)
```
IPv6地址 → ICMP Paris追踪
    ↓ (失败)
TCP端口80探测
    ↓ (失败) 
TCP端口443探测
    ↓ (失败)
记录失败并继续
```

### 探测参数解释

| 参数 | 含义 | IPv4值 | IPv6值 |
|------|------|--------|--------|
| `-P` | 探测协议 | icmp-paris | icmp-paris/tcp |
| `-m` | 最大TTL跳数 | 30 | - |
| `-g` | 连续无响应跳数限制 | 30 | 30 |
| `-d` | TCP目标端口 | - | 80/443 |

---

## 💾 断点续传机制

### 工作原理

1. **扫描已有结果**: 自动检测`data/output/`目录下的结果文件
2. **解析已探测IP**: 从`.jsonl`、`.csv`、`.warts`文件中提取目标IP
3. **计算差集**: 新输入IP集合 - 已探测IP集合 = 待探测IP集合
4. **增量探测**: 仅对未探测的IP执行探测任务

### 支持的结果文件格式

| 格式 | 解析方式 | 示例文件 |
|------|---------|----------|
| **JSONL** | 解析`dst`字段 | `ipv4_results_20240131-143022.jsonl` |
| **CSV** | 读取`dst`列 | `results.csv` |
| **WARTS** | 文件名推断 | `ipv4_probes_20240131.warts` |

### 控制参数

```bash
# 启用断点续传 (默认)
python main.py

# 禁用断点续传
python main.py --nocontinues
```

---

## 📊 输出格式

### 日志输出示例

```
2024-01-31 14:30:15 - ScamperTrace - INFO - 正在初始化ScamperTrace控制器...
2024-01-31 14:30:16 - ScamperTrace - INFO - 前缀处理策略 - IPv4前缀: 192.168.0.0/22 (/22) -> 拆分为4个/24子网 -> 生成4个IP地址
2024-01-31 14:30:17 - ScamperTrace - INFO - 生成的IP地址示例: 192.168.0.0, 192.168.1.0, 192.168.2.0, 192.168.3.0
2024-01-31 14:30:18 - ScamperTrace - INFO - [1/4] 探测IPv4地址: 192.168.0.0
2024-01-31 14:30:19 - ScamperTrace - INFO - IPv4探测成功: 192.168.0.0
2024-01-31 14:30:20 - ScamperTrace - INFO - [2/4] 探测IPv4地址: 192.168.1.0
2024-01-31 14:30:21 - ScamperTrace - INFO - IPv4探测成功: 192.168.1.0
```

### 结果文件格式

所有 `.warts` 文件在解析后会生成同名的 `.csv` 文件，最终再汇总为 `{输入文件名}_result.csv`。每个目标IP会输出3条记录，分别对应`icmp`、`tcp_80`、`tcp_443`三种探测方式。

```csv
timestamp,src,dst,stop,tracetype,tracelog,ping_rtt
1706688615,172.16.1.100,192.168.1.1,COMPLETED,icmp,"['10.0.0.1  1.234ms', '172.16.1.1  5.678ms', '192.168.1.1  12.345ms']",12.4ms
1706688615,172.16.1.100,192.168.1.1,HOPLIMIT,tcp_80,"['10.0.0.1  1.400ms', '*', '*']",12.4ms
1706688615,172.16.1.100,192.168.1.1,TIMEOUT,tcp_443,"['*', '*', '*']",12.4ms
```

**字段说明:**
- `timestamp`: Unix时间戳
- `src`: 探测源IP地址  
- `dst`: 探测目标IP地址
- `stop`: 探测结果状态 (COMPLETED/HOPLIMIT/TIMEOUT/FAILED)
- `tracetype`: 探测方式(`icmp`/`tcp_80`/`tcp_443`)
- `tracelog`: 逐跳路径信息，格式为"IP地址 RTT"
- `ping_rtt`: 同一目标的`ping`往返时延，单位ms；若0.5秒内无响应则显示`timeout`

在`-sd`模式下会额外生成`{输入文件名}_source_result.csv`与`{输入文件名}_device_result.csv`，分别包含去重后的Source与Device全量探测记录。两个角色若共享同一个IPv6地址，探测仅执行一次，但结果会同时写入两份文件。

> ✅ 探测完成后，所有`temp_input_*.csv`与`.warts`中间文件会在解析成功后自动清理，目录中只保留最终的CSV结果，便于断点续传与结果归档。

---

## 🗂 项目结构

```
scampertrace/
├── 📁 主程序
│   ├── main.py                    # 主程序入口
│   └── config.json               # 配置文件 (自动生成)
├── 📁 核心源码
│   └── src/
│       ├── scamper_controller.py # 探测控制器
│       └── warts2csv.py          # 结果解析器
├── 📁 工具模块
│   └── utils/
│       ├── __init__.py           # 模块导入
│       ├── logger.py             # 日志系统
│       ├── config.py             # 配置管理
│       └── ip_utils.py           # IP处理工具
├── 📁 数据目录
│   └── data/
│       ├── input/                # 输入前缀文件
│       └── output/               # 探测结果文件
├── 📁 日志目录
│   └── logs/                     # 中文日志文件
├── 📁 测试文件
│   └── tests/
│       ├── test_ip_utils.py      # IP工具测试
│       ├── test_config.py        # 配置系统测试
│       └── run_tests.py          # 测试运行器
├── 📁 部署文件
│   ├── deploy.sh                 # 自动部署脚本
│   ├── requirements.txt          # Python依赖
│   └── run_scampertrace.sh       # 启动脚本 (自动生成)
└── 📁 文档
    ├── README.md                 # 本文档
    ├── IMPLEMENTATION.md         # 实现详解
    └── CLAUDE.md                 # 项目指导
```

---

## 🔧 故障排除

### 常见问题解决

<details>
<summary><strong>1. scamper命令未找到</strong></summary>

```bash
# 检查scamper安装
which scamper
scamper -v

# 如果未安装，参考上方安装说明
# Ubuntu/Debian: sudo apt-get install scamper
# macOS: brew install scamper
```
</details>

<details>
<summary><strong>2. 权限被拒绝错误</strong></summary>

```bash
# 错误信息: Permission denied, could not open /dev/bpf0

# 解决方案: 使用sudo运行
./ensudo.sh
python main.py


```
</details>

<details>
<summary><strong>3. 探测无结果或超时</strong></summary>

- **检查网络连通性**: `ping 目标IP`
- **检查防火墙设置**: 确保ICMP/TCP包不被阻止
- **调整超时时间**: 修改`config.json`中的`timeout`值
- **更换探测协议**: IPv6可尝试TCP端口探测
</details>

<details>
<summary><strong>4. 日志乱码问题</strong></summary>

```bash
# 设置UTF-8环境变量
export PYTHONIOENCODING=utf-8
export LANG=zh_CN.UTF-8
export LC_ALL=zh_CN.UTF-8

# 或在脚本中设置
python main.py
```
</details>

<details>
<summary><strong>5. 内存不足错误</strong></summary>

- **减少探测并发**: 降低`rate_limit`参数
- **分批处理**: 将大输入文件拆分为小文件
- **清理中间文件**: 使用`--cleanup-warts`参数
- **增加虚拟内存**: 系统级别增加swap空间
</details>

### 调试模式

```bash
# 启用详细日志
python main.py --verbose

# 检查配置文件
python -c "from utils import get_config; import json; print(json.dumps(get_config().config, indent=2))"

# 验证IP处理逻辑
python -c "from utils import generate_ips_from_prefix; print(generate_ips_from_prefix('192.168.0.0/22'))"

# 运行测试套件
python tests/run_tests.py
```
