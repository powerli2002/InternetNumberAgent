# E03 CBG 约束扩充实验

**状态**：规划中  
**优先级**：高（CBG 是主动定位的核心，精度 678km 无法用于论文）  
**前置**：E01 已完成

## 问题

当前 TrustGeo 数据集 probes 只有 3 个，CBG 约束圆数量严重不足，导致 Median 678 km。

## 根因分析

- `probe_results_0122.csv` 中探针来源非常有限
- CBG 需要 ≥3 个有效约束，59% 的目标才勉强满足，但精度极差

## 待探索方向

- [ ] **方向A（数据侧）**：从 TrustGeo 的 traceroute 跳点中提取更多 landmark，扩充探针池
  - 已知 landmarks: 2290 个，理论上可作为 CBG 约束来源
  - 修改 `ActiveTriangulationTool` 使用 landmarks 作为约束圆中心
- [ ] **方向B（算法侧）**：换用 LSQR 拟合替代简单圆交集，提升少量约束时的精度
- [ ] **方向C（分析）**：分析 CBG 误差与约束数量的关系，画误差-约束数曲线

## 关键文件

- CBG 实现：`src/agentic_ipv6_geo/tools/cbg.py`
- 主动三角工具：`src/agentic_ipv6_geo/tools/active_triangulation.py`
- cbgtool 依赖：`ipgeotools/cbgtool/scripts/utils/helpers.py`
