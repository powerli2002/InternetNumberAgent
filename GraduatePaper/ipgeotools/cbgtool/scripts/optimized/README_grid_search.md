# CBG和Octant方法网格搜索工具

## 概述

该工具对CBG和Octant地理定位方法的关键超参数进行网格搜索优化，通过系统地测试不同参数组合来找到最优配置。

## 功能特性

- **CBG方法**: 对延迟-距离转换系数δ进行一维网格搜索
- **Octant方法**: 对环形边界系数α和β进行二维网格搜索
- **性能指标**: 记录P50、P95误差和CDF目标函数值
- **可视化**: 生成二维/三维图表展示参数与性能的关系
- **实验跟踪**: 自动记录到Weights & Biases平台

## 快速开始

### 1. 运行完整网格搜索（推荐）

```bash
cd scripts/optimized
python run_grid_search.py
```

### 2. 仅运行CBG网格搜索

```bash
python run_grid_search.py --method cbg
```

### 3. 仅运行Octant网格搜索

```bash
python run_grid_search.py --method octant
```

### 4. 自定义参数运行

```bash
# 自定义CBG参数
python run_grid_search.py --method cbg --delta-min 0.1 --delta-max 0.6 --delta-points 50

# 自定义Octant参数
python run_grid_search.py --method octant --alpha-min 1.0 --alpha-max 2.0 --alpha-points 10 --beta-min 0.01 --beta-max 1.0 --beta-points 20
```

## 参数说明

### 基本参数
- `--data-dir`: 数据文件目录路径
- `--method`: 要运行的方法，可选cbg/octant/both

### CBG参数
- `--delta-min`: δ最小值
- `--delta-max`: δ最大值
- `--delta-points`: δ搜索点数

### Octant参数
- `--alpha-min`: α最小值
- `--alpha-max`: α最大值
- `--beta-min`: β最小值
- `--beta-max`: β最大值
- `--alpha-points`: α搜索点数
- `--beta-points`: β搜索点数
- `--delta-fixed`: Octant中固定的δ值

## 输出文件

### 结果文件
- `delta_grid_search_results.json`: CBG网格搜索结果
- `octant_alpha_beta_grid_search_results.json`: Octant网格搜索结果

### 可视化图表
- `cbg_delta_grid_search_visualization.png`: CBG参数二维可视化
- `octant_alpha_beta_grid_search_visualization.png`: Octant参数三维可视化

## 性能指标

### P50误差
50百分位数误差，表示有50%的定位结果误差小于此值

### P95误差
95百分位数误差，表示有95%的定位结果误差小于此值

### CDF目标函数
基于累积分布函数的目标函数值，计算公式为 `1.0 - normalized_area_under_CDF`
- 值越小表示整体定位性能越好
- 范围在[0, 1]之间

## 可视化说明

### CBG可视化（二维图表）
1. Delta vs P50误差曲线
2. Delta vs P95误差曲线  
3. Delta vs CDF目标函数曲线
4. 各指标归一化对比图

### Octant可视化（三维图表）
1. Alpha-Beta vs P50误差三维曲面
2. Alpha-Beta vs P95误差三维曲面
3. Alpha-Beta vs CDF目标函数三维曲面
4. P50/P95/CDF误差热力图

## 实验跟踪

所有实验数据自动上传到Weights & Biases平台，包括：
- 参数配置信息
- 每次评估的详细指标
- 最优参数组合
- 可视化图表

项目名称：`cbg-octant-grid-search`


### 依赖安装
```bash
pip install -r requirements.txt
``` 