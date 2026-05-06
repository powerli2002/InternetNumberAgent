# 1. 背景

本文件用于指导 AI 实现毕设系统，不用于写论文正文。

目标是在现有 ModuGeo 基础上实现一个 IPv6 地理位置推断系统。系统不让 LLM 直接预测经纬度，而是让 agent 调度可复现的定位工具，并输出位置、置信度、证据链和调用成本。

工具选择必须满足三个标准：

```text
1. 证据独立：不能重复封装 ModuGeo 已经使用的前缀先验和 last-hop/RTT 特征。
2. 数据可得：必须能从现有数据或可采集数据中构造输入。
3. 可评测：必须能输出位置、置信度、失败原因和调用成本。
```

因此，MVP 工具不再单独实现“前缀树定位工具”和“Traceroute/last-hop 特征工具”。这两部分属于 ModuGeo 内部能力。额外工具优先选择 rDNS 语义定位和 CBG 主动测距定位，因为它们提供与 ModuGeo 不同类型的证据。

# 2. 技术实现方案

系统按数据、工具、调度、融合、评测五部分实现。

```text
数据层 -> 定位工具层 -> Agent 调度层 -> 融合层 -> 评测与系统接口
```

数据层需要整理为统一表结构：

```text
targets：目标 IPv6、经纬度真值、省市、运营商、采集时间
traces：目标 IPv6、probe_id、每跳 IP、每跳 RTT、测量时间
probes：probe_id、探针位置、运营商、网络类型
metadata：IPv6 前缀、BGP 前缀、ASN、组织、运营商
rdns：IP、hostname、解析时间
landmarks：已知位置 IP、经纬度、可用 RTT/trace
```

如果某类数据不存在，工具必须返回 `unavailable`，不能伪造结果。

统一工具输出格式：

```json
{
  "tool": "ModuGeo",
  "status": "ok",
  "location": {
    "lat": 39.9,
    "lon": 116.4,
    "region": "北京市"
  },
  "granularity": "coordinate",
  "confidence": 0.82,
  "cost": {
    "time_ms": 120,
    "probe_count": 0
  },
  "evidence": {},
  "failure_reason": null
}
```

## MVP

MVP 只实现必要闭环，先不做复杂 RL。

必须实现的工具：

```text
1. ModuGeoTool
2. RDnsGeoTool
3. ActiveTriangulationTool
4. WhoisBgpContextTool
5. FusionTool
6. RuleAgentScheduler
7. Evaluator
```

`ModuGeoTool` 是核心定位器。它内部使用多尺度前缀、语义属性、last-hop 和 RTT 条件调制。该工具输出坐标级预测、置信度和关键证据摘要。

`RDnsGeoTool` 负责从 rDNS hostname 中提取地理语义。实现时需要维护城市名、拼音缩写、机场码、运营商机房缩写等词典。该工具优先输出区域级候选，不应在证据不足时强行输出坐标。

`ActiveTriangulationTool` 实现基于时延约束的主动定位。默认复用 `GraduatePaper/cbgtool` 的 CBG 约束圆交集方法；NCRGeo 与 NCR-CBG 混合方法作为配置级备选。输入为多个已知位置探针或地标到目标的 RTT。有效约束少于 3 个时直接返回 `unavailable`，不能硬凑坐标。

`WhoisBgpContextTool` 只提供上下文，不作为强定位器。它输出 ASN、组织、BGP 前缀、运营商和可能的注册地。除非注册信息明确到城市且经过验证，否则不能直接作为最终位置。

`FusionTool` 负责融合多个工具结果。MVP 采用置信度加权和冲突惩罚即可：

```text
最终位置 = 按置信度和工具可靠性加权
最终置信度 = 工具置信度 - 工具间地理冲突惩罚
```

`RuleAgentScheduler` 按成本从低到高调度工具：

```text
1. 加载 metadata 和已有 trace。
2. 调用 ModuGeoTool。
3. 若 rDNS 可用，调用 RDnsGeoTool。
4. 若 ModuGeo 置信度低且有足够探针/地标 RTT，调用 ActiveTriangulationTool。
5. 调用 FusionTool。
6. 如果融合置信度达到阈值，停止。
7. 如果仍低置信，输出低置信结果和失败原因，不盲目补工具。
```

MVP 评测必须覆盖：

```text
单工具：ModuGeo、rDNS、主动三角定位
融合：ModuGeo vs ModuGeo+rDNS vs ModuGeo+主动三角定位 vs 全部融合
调度：固定调用全部工具 vs RuleAgentScheduler
指标：Median、Mean、P90、Coverage、平均工具调用数、平均 probe 成本
校准：高置信样本误差是否低于低置信样本
```

MVP 完成标准：

```text
1. 系统能批量输入 IPv6 并输出位置、置信度、证据链。
2. ModuGeo 是最强单工具或核心工具。
3. rDNS 或主动三角定位至少在某个子集上提供可验证增益。
4. 调度策略相比固定全调用降低成本，且精度不明显下降。
5. 所有工具都有失败状态和日志。
```

## 后续内容

MVP 稳定后再实现学习型调度。优先做 contextual bandit，不直接上复杂 RL。

状态特征：

```text
目标 IPv6 前缀粒度
ASN / 运营商
是否有可用 trace
ModuGeo 置信度
rDNS 是否命中地理词
主动三角定位有效约束数量
不同工具预测冲突度
当前累计成本
```

动作空间：

```text
调用 RDnsGeoTool
调用 ActiveTriangulationTool
执行 FusionTool
停止输出
```

ModuGeoTool 默认作为核心工具先调用，不放入可选动作，除非后续要研究极低成本场景。

奖励函数：

```text
R = - Error_km - λ1 * ToolCost - λ2 * ProbeCost - λ3 * Conflict + λ4 * Coverage
```

后续实验：

```text
RuleAgentScheduler vs BanditScheduler
不同成本权重下的精度-成本曲线
按运营商、省份、rDNS 命中情况分组评测
主动三角定位有效探针数量对误差的影响
工具冲突样本的处理效果
```

如果主动测量数据足够，再考虑多轮测量规划。否则不要实现 offline RL，避免把系统复杂度堆到无法验证。

# 3. 注意事项

实现时要坚持数据和方法标准，不按口头设想随意加工具。

不要重复封装 ModuGeo 内部能力：

```text
前缀先验属于 ModuGeo。
last-hop/RTT 条件调制属于 ModuGeo。
单独提取 last-hop 特征可以作为数据预处理，但不是独立定位工具。
```

rDNS 工具只在 hostname 存在且能解析地理语义时有效。没有命中地理词时必须返回 `unavailable` 或低置信结果。

主动三角定位工具必须依赖足够探针或地标位置。没有 3 个以上有效 RTT 约束时不要输出坐标级结果。

WHOIS/BGP/ASN 主要作为上下文和模型特征，不应被包装成强定位方法。注册地与实际使用地可能偏差很大。

每个模块都要写日志：

```text
输入是否完整
调用了哪些工具
每个工具是否成功
失败原因是什么
各工具预测距离冲突多大
最终为什么采用该结果
```

目录建议：

```text
data/
  raw/
  processed/
src/
  data/
  tools/
  scheduler/
  fusion/
  evaluation/
  api/
configs/
experiments/
```

优先级：

```text
必须完成：数据整理、ModuGeoTool、RDnsGeoTool、ActiveTriangulationTool、RuleAgentScheduler、FusionTool、Evaluator。
推荐完成：contextual bandit 调度、成本-精度曲线、置信度校准。
可选完成：多轮主动测量规划、offline RL、前端地图展示。
```

最终系统应证明一个问题：在 ModuGeo 已经较强的前提下，独立证据工具和 agent 调度是否能在特定子集上提升可靠性，或在相同精度下降低调用成本。

# 4. 当前实现入口

当前 MVP 已按数据、工具、调度、融合、评测五层落到 `GraduatePaper/src/agentic_ipv6_geo/`，默认使用标准库实现，便于在无外网环境中通过 `uv` 复现。

```text
src/agentic_ipv6_geo/data/repository.py      统一 CSV 加载、索引和训练/评测切分
src/agentic_ipv6_geo/tools/modugeo.py        ModuGeo 工具封装与多尺度前缀/语义/last-hop 基线
src/agentic_ipv6_geo/tools/rdns.py           rDNS 地理语义解析工具
src/agentic_ipv6_geo/tools/active_triangulation.py 主动三角定位工具，默认适配 cbgtool 的 CBG
src/agentic_ipv6_geo/tools/passive_ipdb.py   被动 IP 数据库候选定位工具
src/agentic_ipv6_geo/tools/cbg.py            传统 CBG RTT 约束定位工具，保留为回归测试与历史对照
src/agentic_ipv6_geo/tools/whois_bgp.py      WHOIS/BGP 上下文工具
src/agentic_ipv6_geo/providers/              scamper、rDNS、RIPE Atlas 主动探测 provider
src/agentic_ipv6_geo/fusion/tool.py          置信度加权融合与冲突惩罚
src/agentic_ipv6_geo/scheduler/rule.py       规则式 Agent 调度器
src/agentic_ipv6_geo/scheduler/qwen.py       Qwen3.5 工具选择 baseline
src/agentic_ipv6_geo/scheduler/rl_policy.py  离线奖励优化 policy
src/agentic_ipv6_geo/evaluation/evaluator.py 单工具、融合、调度批量评测
```

默认运行命令：

```bash
UV_CACHE_DIR=.uv-cache uv sync
UV_CACHE_DIR=.uv-cache uv run python -m unittest discover -s tests -v
UV_CACHE_DIR=.uv-cache uv run ipv6geo-eval --config configs/default.json --output-dir outputs
UV_CACHE_DIR=.uv-cache uv run ipv6geo-run --config configs/default.json --targets data/processed/targets.csv --output outputs/predictions/batch_predictions.jsonl
```

默认样例数据位于 `data/processed/`，用于验证系统闭环。替换为真实数据时保持同名 CSV 和字段契约即可；缺失输入不会被工具伪造，工具会返回 `unavailable` 并记录失败原因。评测输出落到 `outputs/metrics/` 和 `outputs/predictions/`，RL 轨迹默认落到 `outputs/rl/trajectories/`，调度日志为 JSONL 格式，默认路径为 `outputs/logs/run.jsonl`。

真实主动探测默认关闭。RIPE Atlas、scamper、Qwen3.5 与被动 IPDB 的运行参数统一放在 `configs/*.json` 中，密钥只通过环境变量读取，不能写入配置文件或实验日志。RIPE Atlas API 使用规范见 `skills/ripe-atlas/SKILL.md`。

TrustGeo 数据适配入口：

```bash
UV_CACHE_DIR=.uv-cache uv run ipv6geo-prepare-trustgeo --trustgeo-root /home/lzj/TrustGeo --output-dir data/trustgeo_processed
UV_CACHE_DIR=.uv-cache uv run ipv6geo-validate --config configs/trustgeo.json --output outputs/trustgeo/metrics/data_validation.json
UV_CACHE_DIR=.uv-cache uv run ipv6geo-eval --config configs/trustgeo.json --output-dir outputs/trustgeo
UV_CACHE_DIR=.uv-cache uv sync --extra ui
UV_CACHE_DIR=.uv-cache uv run ipv6geo-dashboard --config configs/trustgeo.json --server-port 8501 --server-address 127.0.0.1
```

当前 TrustGeo 适配默认复用 `output/pfxgeo_v11/predictions.csv` 作为 `ModuGeoTool` 的外部核心预测，复用 `data/traceroute/probe_results_0122.csv` 构造主动三角定位与 last-hop 证据，复用 `pfx2as_v6_processed.csv` 和 AS WHOIS GPS 构造元数据、探针位置和 weak landmark。

Streamlit 可视化界面位于 `src/agentic_ipv6_geo/ui/dashboard.py`，用于展示数据覆盖、单 IP 自动定位、规则/Bandit 调度决策、各工具输出、置信度、误差、评测指标、成本-精度前沿和实验报告。
