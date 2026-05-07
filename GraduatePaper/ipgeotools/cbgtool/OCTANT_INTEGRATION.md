# Octant环形区域定位方法集成

## 概述

本文档介绍了在现有CBG地理定位项目中集成的新的Octant环形区域定位方法。该方法基于Octant框架的理论，通过计算多个环形约束区域的交集来估计目标位置。

**关键改进**：
- ✅ 直接使用CBG计算的距离数据，避免重复计算
- ✅ 保持与CBG方法的数据格式一致性
- ✅ 优化的文件组织结构
- ✅ 完整的向后兼容性

## 核心组件

### 1. OctantRingLocalizer 类

位置：`src/octant_ring_localizer.py`

这是一个独立的定位器类，直接使用CBG生成的圆形数据：

```python
from src.octant_ring_localizer import OctantRingLocalizer, NoIntersectionError

# 创建定位器
localizer = OctantRingLocalizer(
    buffer_resolution=32,  # 环形精度
    inner_ratio=2/3,       # 内半径比例
    outer_ratio=4/3        # 外半径比例
)

# 使用CBG圆形数据进行定位（推荐）
cbg_circles = [
    (116.39, 39.90, 15.0, 25.5, 25.5/6371),  # (lon, lat, rtt, d_km, r_radians)
    (116.41, 39.91, 12.0, 20.8, 20.8/6371),
    (116.40, 39.89, 18.0, 30.2, 30.2/6371),
]

try:
    result = localizer.locate_target_from_cbg_circles(cbg_circles)
    if result:
        lon, lat = result
        print(f"目标位置: ({lon:.6f}, {lat:.6f})")
except NoIntersectionError:
    print("环形区域没有交集")
```

### 2. 集成的CBGTool类

修改后的`CBGTool`类现在直接传递CBG圆形数据给Octant方法：

```python
from src.CBGTool import CBGTool

# 创建支持Octant方法的工具
tool = CBGTool(
    limit=100,
    use_octant=True  # 启用Octant方法
)

# 运行定位（Octant将直接使用CBG的圆形数据）
results = tool.run()

# 查看结果
print(f"CBG方法结果: {len(results['result_ori'])}")
print(f"Octant方法结果: {len(results['result_octant'])}")
```

## 核心算法

### 数据流程

1. **CBG圆形生成**: CBG方法计算VP到目标的距离和约束圆形
2. **Octant接收数据**: 直接使用CBG的圆形数据，格式为 `(lon, lat, rtt, d_km, r_radians)`
3. **环形约束创建**: 对CBG距离进行比例放缩
4. **几何交集计算**: 使用Shapely库计算环形区域交集
5. **质心定位**: 从交集区域计算目标位置

### 环形约束生成

对于每个CBG圆形和其距离 `d_km`，生成环形约束：

- **外半径**: `R_outer = outer_ratio × d_km` (默认4/3)
- **内半径**: `R_inner = inner_ratio × d_km` (默认2/3)
- **环形区域**: 外圆减去内圆的差集

### 距离数据复用

```python
# CBG生成的圆形数据格式
cbg_circle = (lon, lat, rtt_ms, distance_km, radius_radians)

# Octant直接使用CBG的distance_km
R_outer_km = (4/3) * distance_km  # 不需要重新计算
R_inner_km = (2/3) * distance_km
```

### 几何运算

使用Shapely库进行精确的几何运算：

1. **环形创建**: `outer_circle.difference(inner_circle)`
2. **交集计算**: `intersection(annulus1, annulus2, ...)`
3. **质心计算**: 对于复杂几何体，选择面积最大的连通区域计算质心

## 使用方法

### 命令行使用

```bash
# 仅使用CBG方法（默认）
python src/CBGTool.py

# CBG + Octant方法
python src/CBGTool.py --octant

# CBG + NCR方法
python src/CBGTool.py --use-ncr

# 所有方法（CBG + NCR + Octant）
python src/CBGTool.py --use-ncr --octant

# 限制处理数量进行测试
python src/CBGTool.py --octant --limit 10
```

### 程序化使用

```python
# 方法1: 直接使用OctantRingLocalizer（推荐）
from src.octant_ring_localizer import OctantRingLocalizer

localizer = OctantRingLocalizer()
cbg_circles = [...]  # CBG圆形数据
result = localizer.locate_target_from_cbg_circles(cbg_circles)

# 方法2: 通过CBGTool集成使用
from src.CBGTool import CBGTool

# 仅CBG + Octant
tool = CBGTool(use_octant=True)
results = tool.run()

# 所有方法
tool_all = CBGTool(use_ncr=True, use_octant=True)
results_all = tool_all.run()

# 方法3: 向后兼容接口（不推荐）
landmarks = [...]  # 旧格式
result = localizer.locate_target(landmarks)  # 会显示警告
```

## 输出文件

运行后会生成以下结果文件：

- `data/output/user_result_loc_ori.json` - CBG方法结果
- `data/output/user_result_octant.json` - Octant方法结果（如果启用）
- `data/output/user_octant_circle_map.json` - Octant方法的环形区域数据（如果启用）
- `data/output/user_circle_map_ori.json` - CBG方法的圆形数据

### 结果格式

每个结果项的格式：
```json
[
    "目标IP",
    误差_km,
    [预测经度, 预测纬度],
    [真实经度, 真实纬度],
    额外参数,
    "预测省份",
    "真实省份"
]
```

### 环形区域数据格式

Octant方法的环形区域数据格式：
```json
{
    "目标IP": [
        [经度, 纬度, RTT时间, 距离_公里, 半径_弧度],
        ...
    ]
}
```

## 性能优化

### 参数调优

1. **buffer_resolution**: 控制圆形多边形的边数
   - 测试环境: 16
   - 生产环境: 32-64

2. **inner_ratio/outer_ratio**: 环形半径比例
   - 默认: 2/3 和 4/3
   - 可根据网络特性调整

3. **数据过滤**: 
   - 复用CBG的过滤逻辑
   - 至少需要3个有效圆形进行定位

### 坐标系统

当前实现使用地理坐标（WGS84）：
- 简化的度到米转换近似
- 适用于局部区域定位
- 对于高精度需求，建议投影到适当的UTM坐标系

## 异常处理

### NoIntersectionError

当环形区域没有公共交集时抛出：

```python
try:
    result = localizer.locate_target_from_cbg_circles(cbg_circles)
except NoIntersectionError:
    print("环形区域没有交集，无法定位")
```

### 其他异常

- **空CBG数据**: 返回None
- **圆形数量不足**: 返回None  
- **几何计算错误**: 记录日志并返回None

## 与CBG方法的比较

| 特性 | CBG方法 | Octant环形方法 |
|------|---------|----------------|
| 约束类型 | 圆形 | 环形（圆环状） |
| 数学基础 | 高斯分布质心 | 几何约束交集 |
| 距离计算 | 内置RTT转换 | 复用CBG距离 |
| 容错性 | 较好 | 严格几何约束 |
| 适用场景 | 传统网络定位 | 理论约束定位 |
| 计算复杂度 | 较低 | 中等 |
| 数据一致性 | N/A | 完全一致 |

## 依赖项

新增的依赖项：
```
shapely>=1.8.0
```

安装方法：
```bash
pip install shapely
```

## 文件结构

```
CBGLocTool/
├── src/
│   ├── octant_ring_localizer.py  # 新增：Octant定位器
│   └── CBGTool.py                 # 修改：集成支持
├── scripts/
│   ├── tests/
│   │   └── test_octant.py         # 移动：测试脚本
│   └── examples/
│       └── example_usage.py       # 移动：使用示例
├── data/
│   └── format/                    # 标准数据格式
│       ├── user_probes_and_anchors.json
│       ├── user_anchors.json
│       ├── user_probes.json
│       └── ping_to_anchors.csv
├── OCTANT_INTEGRATION.md          # 更新：集成文档
└── requirements.txt               # 修改：添加shapely依赖
```

## 贡献指南

### 扩展方向

1. **投影支持**: 添加UTM坐标系统支持
2. **权重系统**: 为约束添加置信度权重
3. **多层约束**: 支持主/次地标的分层约束
4. **可视化**: 添加环形区域和交集的可视化功能

### 开发注意事项

1. 保持向后兼容性
2. 充分的单元测试覆盖
3. 详细的性能基准测试
4. 完整的错误处理和日志记录
5. 与CBG方法的数据格式一致性

## Web界面集成

### 环形区域可视化

Web界面(`analysis/web/`)已更新以支持Octant环形区域的可视化：

1. **方法选择**: 界面中的"数据集"选择器已更新为"方法"选择器
2. **环形区域绘制**: 
   - CBG方法显示普通圆形（紫色实线）
   - Octant方法显示环形区域（橙色虚线，内外圆环）
3. **交互功能**: 
   - 点击环形区域查看详细信息
   - 支持环形区域的缩放控制
   - 区分不同方法的图例显示

### 启动Web界面

```bash
cd analysis/web
npm start
# 访问 http://localhost:8080
```

### 环形区域数据API

- `/api/data/user_circle_map/octant` - 获取Octant环形区域数据
- `/api/data/user_result_loc/octant` - 获取Octant定位结果

## 数据一致性检查

### 验证CBG数据格式

```python
def validate_cbg_circle(circle):
    """验证CBG圆形数据格式"""
    if len(circle) != 5:
        return False
    lon, lat, rtt, d_km, r_radians = circle
    return all([
        -180 <= lon <= 180,      # 有效经度
        -90 <= lat <= 90,        # 有效纬度
        rtt >= 0,                # 有效RTT
        d_km > 0,                # 有效距离
        r_radians > 0            # 有效半径
    ])
```

### 数据来源统一

所有定位方法现在使用相同的数据源：
- VP坐标: `data/format/user_probes_and_anchors.json`
- RTT数据: `data/format/ping_to_anchors.csv`
- 距离计算: 统一的CBG逻辑

## 参考文献

- Octant框架理论文档: `octant_method.md`
- Shapely几何库文档: https://shapely.readthedocs.io/
- 网络延迟地理定位相关论文 