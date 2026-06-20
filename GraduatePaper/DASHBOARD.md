# 毕业论文进度看板

> 题目：基于 Agent 调度的 IPv6 地理位置推断系统  
> 最后更新：2026-06-08
> 当前阶段：**P0 Agent 训练环境已建成 · 工具互补收益不足**
> 论文撰写：暂缓，当前专注实验

---

## 一、总体进度

```
系统实现  [████████████████████] 100%  基础评测与 P0 多轮回放环境可运行
数据准备  [████████████████░░░░]  80%  P0 数据已构建；正式 SFT 数据仍需平衡扩充
实验评测  [██████████████░░░░░░]  70%  E01 与 E05 完成；工具适配实验待做
```

---

## 二、实验台账

| ID | 名称 | 状态 | Median误差 | 覆盖率 | 结论 |
|----|------|------|----------:|-------:|------|
| E01 | TrustGeo 基线 | ✅ 完成 | ModuGeo 31.8 km | 100% | 调度未超基线，rDNS/IPDB 0% 覆盖 |
| E02 | rDNS 覆盖率提升 | 📋 规划中 | — | — | 换 resolver，分析词典质量 |
| E03 | CBG 探针扩充 | 📋 规划中 | — | — | 用 landmarks 扩充约束源 |
| E04 | 被动 IPDB 接入 | 📋 规划中 | — | — | 需要 GeoCN.mmdb |
| E05 | P0 Agent 训练环境建设 | ✅ 完成 | Oracle 30.0 km | 100% | 环境通过；定位纠错型 GRPO 门禁未通过 |

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
| rDNS PTR 覆盖率 1%（中国 ISP 不部署 IPv6 PTR） | 高 | E02：换 resolver 重试；若无改善作为负面结果记录 |
| 被动 IPDB 本地无 GeoCN.mmdb | 中 | E04：评估开源替代方案（ip2location-lite） |
| CBG 精度 678 km（probe 仅 3 个） | 高 | E03：用 2290 个 landmarks 扩充约束圆来源 |
| RIPE Atlas API 401 | 低 | 更换有效 API Key 或放弃此路线 |
| 非 ModuGeo 工具仅改善 48/929（5.17%） | 高 | 先做工具适配与适用性/风险控制 SFT，不直接做定位纠错型 GRPO |
| SFT 种子中非 ModuGeo 调用仅 35 个训练任务 | 高 | 增加失败识别、质量判断、冲突和拒答轨迹，平衡动作分布 |

---

## 四、下一步任务（按优先级）

### 本周

- [ ] **T1** 基于 P0 回放构造平衡的工具适用性与风险控制 SFT 数据
- [ ] **T2** E03：验证 landmarks 是否能产生可靠主动约束并重跑 Oracle 审计
- [ ] **T3** E02：分析现有 PTR 的词典命中与有效定位比例

### 近期

- [ ] **T4** E04：评估 GeoCN.mmdb 或 ip2location-lite IPv6 可用性
- [ ] **T5** 实现正式多轮 SFT 数据构建与训练入口

---

## 五、目录说明（AI 入口）

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
│   ├── E04_passive_ipdb/      📋 plan.md（规划中）
│   └── E05_p0_environment/    ✅ results.md（P0 建设完成）
│
├── notes/                     ← 研究笔记
│   └── research_gaps.md       实验发现与负面结果整理
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

### 数据位置

| 数据 | 路径 | 行数 |
|------|------|-----:|
| TrustGeo 目标真值 | `data/trustgeo_processed/targets.csv` | 929 |
| Traceroute | `data/trustgeo_processed/traces.csv` | 58363 跳 |
| 探针 | `data/trustgeo_processed/probes.csv` | 3 |
| Landmarks | `data/trustgeo_processed/landmarks.csv` | 2290 |
| rDNS（当前空） | `data/trustgeo_processed/rdns.csv` | 0 |

### P0 建设结果

| 项目 | 结果 |
|------|-----:|
| P0 目标 | 929 |
| `/48` 隔离划分 | Train 650 / Validation 93 / Test 93 / Prefix-OOD 93 |
| 工具回放记录 | 4,645 |
| SFT 种子轨迹 | 650 |
| GRPO prompts | 650 |
| 模型可见数据泄漏 | 0 |
| 确定性重放 | 通过 |
| 非 ModuGeo Oracle 改善 | 48/929（5.17%） |
| Oracle Median | 30.02 km |
| 定位纠错型 GRPO 门禁 | 未通过 |

---

## 六、更新规则

- **每次实验完成后**：在对应 `experiments/E0N_*/` 写 `results.md`，并更新第二节实验台账。
- **每次解决阻塞项**：从第三节删除或标注已解决。
- **不要追加"更新日志"**：直接改正文，保持看板始终反映当前真实状态。
