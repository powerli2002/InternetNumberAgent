# 毕业论文进度看板

> 题目：基于 Agent 调度的 IPv6 地理位置推断系统  
> 最后更新：2026-05-31  
> 当前阶段：**实验阶段 · 数据缺口待突破**

---

## 一、总体进度

```
系统实现  [████████████████████] 100%  代码完整，评测可跑通
数据准备  [████████████░░░░░░░░]  60%  TrustGeo 已适配；rDNS/被动IPDB 缺失
实验评测  [████████████░░░░░░░░]  55%  E01基线完成；E02/E03/E04 待做
论文撰写  [░░░░░░░░░░░░░░░░░░░░]   0%  尚未开始 ← 最高风险项
```

---

## 二、实验台账

| ID | 名称 | 状态 | Median误差 | 覆盖率 | 结论 |
|----|------|------|----------:|-------:|------|
| E01 | TrustGeo 基线 | ✅ 完成 | ModuGeo 31.8 km | 100% | 调度未超基线，rDNS/IPDB 0% 覆盖 |
| E02 | rDNS 覆盖率提升 | 📋 规划中 | — | — | 换 resolver，分析词典质量 |
| E03 | CBG 探针扩充 | 📋 规划中 | — | — | 用 landmarks 扩充约束源 |
| E04 | 被动 IPDB 接入 | 📋 规划中 | — | — | 需要 GeoCN.mmdb |

### E01 核心数据（325 测试 IP）

| 策略 | Median | Mean | P90 | 覆盖率 |
|------|-------:|-----:|----:|-------:|
| ModuGeo 基线 | **31.8 km** | 68.0 | 140.9 | 100% |
| CBG 主动三角 | 678 km | 895 | 1847 | 59% |
| rDNS | — | — | — | **0%** |
| 被动 IPDB | — | — | — | **0%** |
| 规则/Bandit/Qwen 调度 | 31.8 km | 68.0 | 140.9 | 100% |
| RL Policy | 31.8 km | 69.0 | 148.6 | 100% |

---

## 三、当前阻塞

| 阻塞 | 严重性 | 建议 |
|------|--------|------|
| rDNS PTR 覆盖率 1%（中国 ISP 不部署 IPv6 PTR） | 高 | E02：换 resolver 重试；若无改善作为负面结果写入论文 |
| 被动 IPDB 本地无 GeoCN.mmdb | 中 | E04：评估开源替代方案（ip2location-lite） |
| CBG 精度 678 km（probe 仅 3 个） | 高 | E03：用 2290 个 landmarks 扩充约束圆来源 |
| RIPE Atlas API 401 | 低 | 更换有效 API Key 或放弃此路线 |
| **论文未动笔** | **极高** | 立即开始，系统实现已充分 |

---

## 四、下一步任务（按优先级）

### 本周必做

- [ ] **T1** 开始论文第 1、2 章（题目背景、相关工作）—— 不依赖任何实验
- [ ] **T2** E03：修改 `ActiveTriangulationTool` 支持 landmarks 作为约束源，重跑评测

### 近期（2 周内）

- [ ] **T3** E02：换 Google/114 DNS 重跑 rDNS 采集，分析现有 212 条 PTR 的词典命中率
- [ ] **T4** 论文第 3 章（系统设计）——代码已实现，直接描述架构
- [ ] **T5** 论文第 4 章（实验设置与数据）——E01 数据已有

### 待定

- [ ] **T6** E04：评估 GeoCN.mmdb 或 ip2location-lite IPv6 可用性
- [ ] **T7** 论文第 5 章（实验结果与分析）——依赖 E02/E03 完成
- [ ] **T8** 图表制作：误差 CDF、成本-精度前沿、调度策略对比

---

## 五、论文写作进度

| 章节 | 内容 | 状态 | 依赖 |
|------|------|------|------|
| 1. 引言 | 背景、动机、贡献 | ⬜ 未开始 | 无 |
| 2. 相关工作 | TrustGeo、CBG、rDNS 定位综述 | ⬜ 未开始 | 无 |
| 3. 系统设计 | 架构、工具、调度、融合 | ⬜ 未开始 | 无（代码已有） |
| 4. 实验设置 | 数据集、评测指标、实现细节 | ⬜ 未开始 | E01 ✅ |
| 5. 实验结果 | 单工具/融合/调度对比，分析 | ⬜ 未开始 | E01 ✅，E02/E03 待完成 |
| 6. 结论与展望 | 总结、局限性、未来工作 | ⬜ 未开始 | 5章完成后 |
| 参考文献 | — | ⬜ 未开始 | — |

**论文模板**：`thesis/`（待初始化，使用 `LaTeXThesisbyGEAR-master` 或 `gear-thesis-template-v2.1`）

---

## 六、目录说明（AI 入口）

```
GraduatePaper/
├── DASHBOARD.md              ← 本文件，进度总控，每次更新直接改这里
├── AGENTS.md                 ← AI 工作约束与入口规范
├── README.md                 ← 系统快速运行文档
├── Agentic_IPv6_Geolocation_Plan.md  ← 技术设计方案（参考用）
│
├── src/agentic_ipv6_geo/     ← 主代码（40个.py）
│   ├── tools/                  5个定位工具 + base + registry
│   ├── scheduler/              rule / bandit / qwen / rl_policy
│   ├── fusion/                 置信度加权融合
│   ├── evaluation/             评测器与指标
│   ├── data/                   数据加载、TrustGeo适配、校验
│   ├── providers/              scamper / zdns / atlas / rdns
│   ├── ui/                     Streamlit 界面
│   └── cli.py                  所有命令行入口
│
├── experiments/               ← 实验记录（按 E0N 编号）
│   ├── E01_baseline_trustgeo/ ✅ results.md（已完成）
│   ├── E02_rdns_enhancement/  📋 plan.md（规划中）
│   ├── E03_cbg_probe_expansion/ 📋 plan.md（规划中）
│   └── E04_passive_ipdb/      📋 plan.md（规划中）
│
├── thesis/                    ← 论文 LaTeX（空，待写）
├── notes/                     ← 研究笔记
│   └── research_gaps.md       论文论点与负面结果整理
│
├── configs/                   ← 实验配置
│   ├── default.json           合成数据默认配置
│   └── trustgeo.json          TrustGeo 配置（当前主用）
│
├── data/
│   ├── processed/             小样本示例数据（随代码提交）
│   └── trustgeo_processed/    TrustGeo 适配后数据（929目标）
│
├── outputs/trustgeo/          ← E01 全部产物
│   ├── metrics/               summary.json, group_metrics.json
│   ├── predictions/           各策略预测 .jsonl
│   └── 实验报告.md            指标汇总表
│
├── ipgeotools/                ← 外部工具快照
│   ├── cbgtool/               CBG 约束圆实现（被 ActiveTriangulationTool 调用）
│   ├── scampertrace/          Scamper 主动探测接口
│   └── IPDB/                  GeoCN / ip-database（缺 .mmdb 文件）
│
└── scripts/                   ← 一次性运行脚本
```

### 当前最重要的代码路径

| 任务 | 文件 |
|------|------|
| 运行全量评测 | `UV_CACHE_DIR=.uv-cache uv run ipv6geo-eval --config configs/trustgeo.json --output-dir outputs/trustgeo` |
| CBG 修改入口 | `src/agentic_ipv6_geo/tools/active_triangulation.py` |
| rDNS 采集 | `src/agentic_ipv6_geo/providers/zdns.py` |
| 数据适配 | `src/agentic_ipv6_geo/data/trustgeo_adapter.py` |
| 论文模板 | `thesis/`（空，待选定模板） |

### 数据位置

| 数据 | 路径 | 行数 |
|------|------|-----:|
| TrustGeo 目标真值 | `data/trustgeo_processed/targets.csv` | 929 |
| Traceroute | `data/trustgeo_processed/traces.csv` | 58363 跳 |
| 探针 | `data/trustgeo_processed/probes.csv` | 3 |
| Landmarks | `data/trustgeo_processed/landmarks.csv` | 2290 |
| rDNS（当前空） | `data/trustgeo_processed/rdns.csv` | 0 |

---

## 七、更新规则

- **每次实验完成后**：在对应 `experiments/E0N_*/` 写 `results.md`，并更新本文件第二节的实验台账。
- **每次论文章节完成后**：更新第五节论文写作进度的状态。
- **每次解决阻塞项**：从第三节删除或标注已解决。
- **不要追加"更新日志"**：直接改正文，保持看板始终反映当前真实状态。
