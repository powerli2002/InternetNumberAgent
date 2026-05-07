# 凸包方法距离-延迟分析项目

## 项目概述

本项目实现了基于Octant论文中描述的凸包方法，用于分析网络延迟与地理距离的关系，并计算距离-延迟转换系数（δ值）。

## 文件结构

```
CBGLocTool/scripts/culcate_convex_hull/
├── convex_hull_analysis.py      # 主分析脚本
├── requirements.txt             # Python依赖包
├── analysis_results.json        # 分析结果（JSON格式）
├── analysis_report.md          # 分析报告
├── distance_latency_analysis.png # 可视化图表
├── 技术说明文档.md             # 详细技术实现说明
├── 结果分析文档.md             # 结果解释与分析
├── README.md                   # 本文件
└── Octant_paper.md            # Octant方法理论说明
```

## 主要结果

基于794个有效数据点的分析结果：

- **网络传播速度**: 56,655 m/s
- **光速比例 (δ)**: 0.0002 (约为光速的0.02%)
- **线性拟合斜率**: 56.655 km/ms
- **距离范围**: 0 - 8,191 km
- **延迟范围**: 0.009 - 120 ms

## 快速开始

### 1. 环境准备

```bash
# 安装依赖包
pip install -r requirements.txt
```

### 2. 运行分析

```bash
# 执行完整分析
python3 convex_hull_analysis.py
```

### 3. 查看结果

- **图表**: `distance_latency_analysis.png`
- **报告**: `analysis_report.md`
- **详细结果**: `analysis_results.json`

## 核心技术

### 1. 数据处理
- 城市地理编码（26个美国主要城市）
- 大圆距离计算
- 离群点检测（IQR方法）

### 2. 凸包分析
- 使用scipy.spatial.ConvexHull构建凸包
- 上下边界分离算法
- 二次多项式边界函数拟合

### 3. 转换系数计算
- 线性拟合计算延迟-距离关系
- 速度计算：speed = slope * 1000
- δ值计算：δ = speed / 光速

## 可视化说明

生成的图表包含：
- 蓝色散点：有效数据点
- 红色×号：离群点（如有）
- 黑色线条：凸包边界
- 绿色线条：上边界函数
- 红色线条：下边界函数
- 紫色虚线：线性拟合（显示δ值）

**坐标轴设置**：
- 横轴：延迟 (ms)
- 纵轴：距离 (km)

## 结果解释

δ = 0.0002 表示计算得到的网络传播速度约为光速的0.02%。这个相对较低的值反映了：

1. **网络复杂性**: 包含路由延迟、处理延迟、拥塞等因素
2. **路径迂回**: 网络路径不是地理最短路径
3. **协议开销**: TCP/IP协议栈的处理时间

## 应用场景

- 网络性能评估和基准建立
- 粗粒度地理定位
- 网络容量规划
- 异常连接检测
- 学术研究支持

## 技术特点

- **准确性**: 使用大圆距离和多项式拟合
- **鲁棒性**: 多种离群点检测方法
- **可扩展性**: 模块化设计，易于扩展
- **可视化**: 清晰的图表和详细报告

## 限制说明

1. **地理覆盖**: 仅限美国城市间测量
2. **时间快照**: 反映特定时间点的网络状态  
3. **线性假设**: 假设延迟与距离线性相关
4. **测量方法**: 基于ping，可能不代表应用层性能

## 参考文献

- Octant: A Comprehensive Framework for the Geolocalization of Internet Hosts
- scipy.spatial.ConvexHull Documentation
- geopy Distance Calculation Methods

## 作者

AI Assistant - 基于用户需求实现

## 许可证

本项目仅用于学术研究和教育目的。

---

更多详细信息请参阅：
- **技术实现**: `技术说明文档.md`
- **结果分析**: `结果分析文档.md`
- **理论基础**: `Octant_paper.md` 