# GeoAgent-R1 毕设当前状态整合报告

> 生成日期：2026-06-20  
> 工作目录：`/home/lzj/fusionprocessing/GraduatePaper`  
> 报告性质：当前事实状态整合，不作为单一研究方向裁决文件  
> 信息来源：`README.md`、`DASHBOARD.md`、`configs/trustgeo.json`、`experiments/`、`reports/`、`notes/`、`outputs/`、`src/agentic_ipv6_geo/`、自动化测试结果

## 0. 报告范围

本文档整合当前毕业设计的实现、数据、算法、工具、实验和训练环境状态。报告尽量采用事实陈述，避免把某一条研究路线表述为唯一结论；涉及“门禁”“待完成”“可继续构造”的内容，均以当前代码、数据和实验产物为依据。

当前毕设目录是 `GraduatePaper/`，实现项目名为 `agentic-ipv6-geo`。项目的工程目标是实现一个面向 IPv6 地理位置推断的工具调度与 Agent 实验系统。系统不让 LLM 直接凭空输出经纬度，而是围绕可复现定位工具构造证据、候选位置、调用成本、失败原因和训练/评测数据。

当前系统已经覆盖以下方面：

- TrustGeo 数据适配。
- ModuGeo 预测复用。
- rDNS/PTR 采集与地名词典解析。
- 主动三角定位，默认 CBG。
- 被动 IPDB 多 backend 框架。
- WHOIS/BGP 上下文证据。
- 置信度加权融合。
- 规则调度、Contextual Bandit、Qwen 工具选择 baseline、离线奖励 policy。
- 批量评测与指标产物。
- Streamlit Dashboard 入口。
- MCP 工具服务入口。
- P0 阶段无泄漏、可回放、多轮 Agent 环境。
- P0 SFT seed 和 GRPO prompts 生成。
- Oracle 工具效用审计。
- W&B P0 同步。

当前系统还没有完成以下方面：

- 正式 SFT 训练。
- 正式 GRPO 训练。
- 多轮在线 rollout 的训练闭环。
- 工具适配后重新达到定位纠错型 GRPO 门禁。
- E02、E03、E04 的完整实验结果。
- 被动 IPv6 IPDB 的可用数据文件接入。
- 使用当前 P0 产物训练出的 Agent checkpoint。

## 1. 当前毕设对象与边界

### 1.1 项目主题

当前毕设围绕“基于 Agent 调度的 IPv6 地理位置推断系统”展开。工程实现目录名为 `GraduatePaper/`，Python 包名为 `agentic_ipv6_geo`。

系统的定位方式不是单一模型推理，而是将多个定位证据源统一封装为工具：

- 核心定位器：ModuGeo。
- 主动测距工具：CBG/NCR/NCR-CBG 主动三角定位。
- 语义工具：rDNS hostname 地名解析。
- 被动定位工具：GeoCN.mmdb、ip-database、Aiwen TSV 等 backend 框架。
- 上下文工具：WHOIS/BGP。
- 融合工具：FusionTool。
- 调度器：规则、Bandit、Qwen baseline、离线奖励 policy。
- Agent 环境：P0 离线回放多轮环境。

### 1.2 当前 Agent 研究边界

当前代码中的 LLM/Agent 相关部分分成三个层次：

1. **工具调度层**：已有规则调度、Bandit 调度和 Qwen 工具选择 baseline。Qwen baseline 只选择工具动作，不直接输出经纬度。
2. **训练数据层**：已有 P0 SFT seed 和 GRPO prompts，但它们是训练准备产物，不等同于已经完成模型训练。
3. **环境层**：已有 `GeoAgentEnv` 离线回放环境，可以执行有限动作、返回工具观察、维护预算并计算奖励。

当前代码还没有接入实际大模型微调框架，没有产出 LoRA/QLoRA checkpoint，也没有执行正式 GRPO 更新。

### 1.3 当前事实源

当前报告涉及的主要事实源：

| 类型 | 路径 |
| --- | --- |
| 项目说明 | `GraduatePaper/README.md` |
| 进度看板 | `GraduatePaper/DASHBOARD.md` |
| 主配置 | `GraduatePaper/configs/trustgeo.json` |
| Python 项目配置 | `GraduatePaper/pyproject.toml` |
| P0 报告 | `GraduatePaper/reports/p0_construction_report.md` |
| P0 实验结果 | `GraduatePaper/experiments/E05_p0_environment/results.md` |
| 完整研究报告 | `GraduatePaper/reports/geoagent_sft_grpo_full_report.md` |
| 工具上限条件方案 | `GraduatePaper/notes/tool_ceiling_alternative_route.md` |
| P0 汇总 JSON | `GraduatePaper/outputs/p0/p0_summary.json` |
| P0 构建清单 | `GraduatePaper/outputs/p0/build_manifest.json` |
| E01 指标 | `GraduatePaper/outputs/trustgeo/metrics/summary.json` |
| TrustGeo 适配摘要 | `GraduatePaper/data/trustgeo_processed/adapter_summary.json` |

## 2. 工程与运行环境状态

### 2.1 Python 与 uv

当前 `GraduatePaper/pyproject.toml` 声明：

- Python 版本：`>=3.11`
- 包名：`agentic-ipv6-geo`
- 构建后端：`uv_build>=0.11.0,<0.12.0`
- 基础依赖：`numpy>=1.24.0`
- 可选依赖：
  - `active`：`pandas`、`scipy`、`ujson`
  - `ui`：`streamlit`
  - `mcp`：`fastmcp`

当前机器已安装并验证：

| 项目 | 状态 |
| --- | --- |
| `uv` | `0.11.19` |
| 当前项目 Python | `3.12.4` |
| 标准虚拟环境 | `GraduatePaper/.venv` |
| 原 root 环境 | `GraduatePaper/.venv-root-broken-20260608`，保留但不作为运行环境 |
| 临时环境 | `GraduatePaper/.venv-claude`，存在但不是 README 指定标准环境 |

最近一次验证命令：

```bash
cd /home/lzj/fusionprocessing/GraduatePaper
UV_CACHE_DIR=.uv-cache uv --version
UV_CACHE_DIR=.uv-cache uv run python --version
UV_CACHE_DIR=.uv-cache uv run python -m unittest discover -s tests -v
```

验证结果：

```text
uv 0.11.19
Python 3.12.4
Ran 12 tests in 0.316s
OK
```

### 2.2 命令行入口

当前 `pyproject.toml` 暴露以下命令：

| 命令 | 入口函数 | 用途 |
| --- | --- | --- |
| `ipv6geo-run` | `agentic_ipv6_geo.cli:run_main` | 批量调度 IPv6 定位工具 |
| `ipv6geo-eval` | `agentic_ipv6_geo.cli:evaluate_main` | 运行评测实验 |
| `ipv6geo-prepare-trustgeo` | `agentic_ipv6_geo.cli:prepare_trustgeo_main` | 适配 TrustGeo 数据 |
| `ipv6geo-validate` | `agentic_ipv6_geo.cli:validate_main` | 校验统一输入数据 |
| `ipv6geo-dashboard` | `agentic_ipv6_geo.cli:dashboard_main` | 启动 Streamlit Dashboard |
| `ipv6geo-mcp` | `agentic_ipv6_geo.mcp_server:main` | 启动 MCP 工具服务 |
| `ipv6geo-collect-rdns` | `agentic_ipv6_geo.cli:collect_rdns_main` | 批量采集 PTR/rDNS |
| `ipv6geo-build-p0` | `agentic_ipv6_geo.cli:build_p0_main` | 构建 P0 Agent 训练环境 |

P0 入口已验证：

```bash
UV_CACHE_DIR=.uv-cache uv run ipv6geo-build-p0 --help
```

### 2.3 自动化测试

当前测试文件：

- `GraduatePaper/tests/test_evaluator.py`
- `GraduatePaper/tests/test_p0_environment.py`
- `GraduatePaper/tests/test_tools.py`

最近一次测试通过项：

| 测试 | 状态 |
| --- | --- |
| `test_evaluator_runs_all_mvp_experiments` | 通过 |
| `test_leakage_scanner_finds_private_fields` | 通过 |
| `test_p0_builder_writes_private_and_visible_data_separately` | 通过 |
| `test_prefix_split_is_isolated` | 通过 |
| `test_replay_environment_is_deterministic_and_rejects_invalid_action` | 通过 |
| `test_active_triangulation_uses_cbgtool_contract` | 通过 |
| `test_cbg_requires_at_least_three_constraints` | 通过 |
| `test_fusion_conflict_penalty_keeps_coordinate_output` | 通过 |
| `test_mcp_runtime_runs_tools_without_transport` | 通过 |
| `test_method_registry_builds_default_methods` | 通过 |
| `test_modugeo_and_rdns_return_structured_results` | 通过 |
| `test_zdns_bulk_collector_normalizes_status_and_writes_cache` | 通过 |

总计：12/12 通过。

## 3. 代码结构状态

### 3.1 主包结构

当前主包目录为 `GraduatePaper/src/agentic_ipv6_geo/`：

```text
agentic_ipv6_geo/
├── cli.py
├── mcp_server.py
├── common/
├── data/
├── environment/
├── evaluation/
├── fusion/
├── providers/
├── scheduler/
├── tools/
└── ui/
```

### 3.2 主要模块职责

| 模块 | 当前职责 |
| --- | --- |
| `common/` | 配置加载、地理距离、通用数据模型、JSONL 日志 |
| `data/` | CSV 数据仓库、TrustGeo 适配、数据校验、P0 构建 |
| `tools/` | ModuGeo、rDNS、主动三角、被动 IPDB、WHOIS/BGP、工具注册 |
| `fusion/` | 多工具候选位置置信度加权融合与冲突惩罚 |
| `scheduler/` | 规则调度、Contextual Bandit、Qwen baseline、离线奖励策略 |
| `providers/` | rDNS、zdns、scamper、RIPE Atlas 等外部采集/探测封装 |
| `evaluation/` | 批量实验、指标汇总、分组指标、RL/SFT 初始产物 |
| `environment/` | P0 Schema、泄漏扫描、离线回放环境、P0 加载 |
| `ui/` | Streamlit Dashboard |
| `mcp_server.py` | FastMCP 工具服务 |

### 3.3 MCP 服务状态

当前 MCP runtime 文件为 `src/agentic_ipv6_geo/mcp_server.py`。

MCP 服务暴露工具：

- `health`
- `list_geo_tools`
- `run_geo_tool`
- `geolocate_ip`
- `debug_geo_tools`
- `collect_scamper_constraints`

其中 `run_geo_tool` 支持：

- `modugeo`
- `rdns`
- `active_triangulation`
- `passive_ipdb`
- `whois`
- `fusion`
- `scheduler_rule`

`collect_scamper_constraints` 默认只读缓存或已有数据，只有显式 `allow_live=true` 才触发 live scamper 相关流程。

### 3.4 Dashboard 状态

当前 Dashboard 入口：

```bash
UV_CACHE_DIR=.uv-cache uv sync --extra ui
UV_CACHE_DIR=.uv-cache uv run ipv6geo-dashboard --config configs/trustgeo.json --server-port 8501 --server-address 127.0.0.1
```

README 描述的 Dashboard 能力：

- TrustGeo 数据适配。
- 数据校验。
- 单 IP 自动定位。
- 规则调度/Bandit 调度选择。
- 各工具输出对比。
- 置信度与误差展示。
- 评测运行。
- 成本-精度前沿。
- 实验报告查看。
- 类似 trace 的节点流展示。

## 4. 数据集状态

### 4.1 TrustGeo 适配数据

当前主用数据目录：

```text
GraduatePaper/data/trustgeo_processed/
```

适配摘要：

| 数据 | 行数 |
| --- | ---: |
| targets | 929 |
| metadata | 106 |
| traces | 58,363 |
| probes | 3 |
| landmarks | 2,290 |
| rdns | 适配阶段为 0；后续采集文件当前有 212 条 PTR 记录 |
| modugeo_predictions | 929 |

适配器来源信息：

- TrustGeo 根目录：`/home/lzj/TrustGeo`
- 输出目录：`data/trustgeo_processed`
- 复用文件包括 `pfxgeo_v11/predictions.csv`、`probe_results_0122.csv`、`pfx2as_v6_processed.csv`、AS WHOIS GPS 与城市坐标表。

### 4.2 当前数据分布

基于当前 `targets.csv`：

| 指标 | 数量 |
| --- | ---: |
| 目标 IPv6 数量 | 929 |
| 唯一 ASN | 15 |
| 唯一 operator | 13 |
| 唯一 `/32` 前缀 | 112 |
| 唯一 `/40` 前缀 | 454 |
| 唯一 `/48` 前缀 | 637 |
| 唯一 `/56` 前缀 | 910 |
| 唯一 `/64` 前缀 | 929 |

Top ASN：

| ASN | 数量 |
| --- | ---: |
| AS9808 | 392 |
| AS4134 | 288 |
| AS4837 | 90 |
| AS4808 | 58 |
| AS56048 | 34 |
| AS56042 | 31 |
| AS24547 | 7 |
| AS17621 | 7 |

Top operator：

| Operator | 数量 |
| --- | ---: |
| 中国移动通信集团公司 | 423 |
| No.31,Jin-rong Street\|Beijing\|100032 | 288 |
| 中国联通 | 94 |
| 中国联合网络通信有限公司北京市分公司 | 58 |
| 中国移动通信集团公司北京市公司 | 34 |
| 河北移动通信有限公司 | 7 |
| 中国联通上海市分公司 | 7 |
| 中国电信云南分公司 | 6 |

### 4.3 CSV 输入表定义

系统默认读取以下 CSV：

| 文件 | 字段 |
| --- | --- |
| `targets.csv` | `ip,lat,lon,region,city,asn,operator,observed_at` |
| `traces.csv` | `target_ip,probe_id,hop_ip,hop_index,rtt_ms,measured_at` |
| `probes.csv` | `probe_id,lat,lon,region,city,operator,network_type` |
| `metadata.csv` | `prefix,bgp_prefix,asn,org,operator,registered_region,registered_city` |
| `rdns.csv` | `ip,hostname,resolved_at`，当前实际文件还包含 `source,status,failure_reason` |
| `landmarks.csv` | `ip,lat,lon,region,city,rtt_ms` |

缺失数据不会被伪造；对应工具返回 `unavailable` 并写明失败原因。

### 4.4 P0 数据划分

P0 构建使用 `/48` 前缀隔离，避免同一 `/48` 同时进入训练与测试划分。

当前划分：

| Split | 数量 |
| --- | ---: |
| Train | 650 |
| Validation | 93 |
| Test | 93 |
| Test-Prefix-OOD | 93 |
| 合计 | 929 |

P0 划分配置：

| 参数 | 值 |
| --- | --- |
| seed | 42 |
| split_prefix_length | 48 |
| max_steps | 4 |
| max_probe_count | 12 |
| oracle_min_improvement_rate | 0.1 |

## 5. 工具状态

### 5.1 工具注册表

当前 `tools/registry.py` 注册 5 个基础工具：

| ID | 名称 | 类别 | 成本 | 证据类型 |
| --- | --- | --- | --- | --- |
| `modugeo` | ModuGeo | 核心定位器 | 低 | 前缀先验 + last-hop 条件证据 |
| `active_triangulation` | 主动三角定位 | 主动测距 | 高 | 探针 RTT 约束圆 |
| `rdns` | rDNS | 语义证据 | 低 | hostname 地理词 |
| `whois` | WHOIS/BGP | 上下文 | 低 | 注册与路由上下文 |
| `passive_ipdb` | 被动 IPDB | 被动定位 | 低 | 本地 IP 数据库 |

此外注册构造阶段会创建：

- `fusion`：融合工具。

### 5.2 ModuGeo

实现文件：

```text
src/agentic_ipv6_geo/tools/modugeo.py
```

当前 ModuGeoTool 支持两种路径：

1. 优先复用外部预测：`repo.modugeo_prediction_for(target.ip)`。
2. 若没有外部预测，则使用多尺度前缀样本、ASN/运营商语义质心和 last-hop 地标信号构造可复现 baseline。

当前 `trustgeo.json` 中：

```json
{
  "use_external_predictions": true,
  "default_external_confidence": 0.72,
  "prefix_lengths": [64, 56, 48, 40, 32],
  "min_prefix_samples": 1,
  "semantic_weight": 0.25,
  "landmark_weight": 0.25
}
```

在 E01 测试集 325 个 IP 上：

| 指标 | 值 |
| --- | ---: |
| Median | 31.813 km |
| Mean | 67.999 km |
| P90 | 140.911 km |
| Coverage | 100% |
| AvgToolCalls | 1 |
| AvgProbeCost | 0 |

在 P0 全量 929 个目标上：

| 指标 | 值 |
| --- | ---: |
| Median | 30.234 km |
| Mean | 61.169 km |
| P90 | 125.048 km |

### 5.3 rDNS

实现文件：

```text
src/agentic_ipv6_geo/tools/rdns.py
src/agentic_ipv6_geo/providers/zdns.py
src/agentic_ipv6_geo/providers/rdns.py
```

rDNS 工具逻辑：

1. 从数据仓库读取目标 IP 的 hostname。
2. 若缺少记录，可按配置触发 active lookup。
3. 将 hostname 分词。
4. 匹配内置城市别名和 `configs/rdns_lexicon.csv`。
5. 命中地理词后输出城市级候选。
6. 未命中则返回 `unavailable`。

当前 rDNS 状态：

- TrustGeo 适配阶段没有发现独立 rDNS 数据。
- 后续使用 `zdns PTR` 对 21,088 个 IP 做过批量采集。
- 采集得到 PTR 记录 212 条。
- PTR 命中率约 1.005%。
- P0 工具回放中，rDNS 对 929 个目标全部为 `unavailable`。
- E01 单工具评测覆盖率为 0%。

批量采集统计：

| 项目 | 数量 |
| --- | ---: |
| total_requested | 21,088 |
| total_queried | 21,088 |
| ok_count | 212 |
| ptr_result_rate | 0.010053 |
| nxdomain | 14,223 |
| servfail | 5,135 |
| timeout | 1,518 |
| elapsed_sec | 402.722 |
| throughput_qps | 52.364 |

### 5.4 主动三角定位

实现文件：

```text
src/agentic_ipv6_geo/tools/active_triangulation.py
src/agentic_ipv6_geo/tools/cbg.py
GraduatePaper/ipgeotools/cbgtool/
```

当前默认算法：

```json
{
  "algorithm": "cbg",
  "min_constraints": 3,
  "delta": 0.398,
  "sort_circles": 0
}
```

工具支持：

- `cbg`
- `ncr`
- `ncr-cbg`

当前默认通过已有 traceroute/probe 约束构造 CBG 圆交集。若约束少于 3 个，工具返回 `unavailable`。当前配置中 live 主动探测允许打开，但 P0 离线构建会强制关闭 live measurement，只使用已有 trace。

E01 测试集结果：

| 指标 | 值 |
| --- | ---: |
| Median | 678.379 km |
| Mean | 894.583 km |
| P90 | 1846.980 km |
| Coverage | 59.385% |
| AvgToolCalls | 1 |
| AvgProbeCost | 2.609 |

P0 全量工具回放：

| 状态 | 数量 |
| --- | ---: |
| ok | 565 |
| unavailable | 364 |

### 5.5 被动 IPDB

实现文件：

```text
src/agentic_ipv6_geo/tools/passive_ipdb.py
```

当前配置启用 multi backend：

- GeoCN.mmdb：`ipgeotools/IPDB/GeoCN/GeoCN.mmdb`
- ip-database PHP：`ipgeotools/IPDB/ip-database`
- AiwenIPv4：`../database/db/aiwen.txt`

当前状态：

- `GeoCN.mmdb` 本地缺失。
- `ip-database` 的 IPv6 数据文件路径配置存在，但本地文件缺失时会返回明确失败。
- Aiwen TSV 口径为 IPv4 整数区间，不作为 IPv6 证据。
- E01 被动 IPDB 覆盖率为 0%。
- P0 被动 IPDB 对 929 个目标全部为 `unavailable`。

### 5.6 WHOIS/BGP

实现文件：

```text
src/agentic_ipv6_geo/tools/whois_bgp.py
```

当前工具从 `metadata.csv` 获取：

- prefix
- bgp_prefix
- asn
- org
- operator
- registered_region
- registered_city

工具定位属性：

- 它是上下文证据。
- 不作为强定位器。
- 若有注册地，可输出区域级/注册地上下文。

P0 工具回放：

| 状态 | 数量 |
| --- | ---: |
| ok | 929 |
| unavailable | 0 |

### 5.7 FusionTool

实现文件：

```text
src/agentic_ipv6_geo/fusion/tool.py
```

当前融合逻辑：

1. 过滤 `ok` 且有坐标的工具结果。
2. 根据工具置信度和配置中的 reliability 计算权重。
3. 对候选坐标做加权平均。
4. 计算候选之间的距离冲突。
5. 按最大冲突距离扣减置信度。
6. 输出融合坐标、置信度、成本和证据。

当前工具 reliability：

| 工具 | reliability |
| --- | ---: |
| ModuGeo | 1.0 |
| rDNS | 0.65 |
| ActiveTriangulation | 0.8 |
| WhoisBGP | 0.25 |
| PassiveIPDB | 0.45 |

冲突惩罚配置：

```json
{
  "conflict_penalty_km": 500.0,
  "confidence_threshold": 0.55
}
```

E01 中，`fusion_modugeo_active` 和 `fusion_all` 的 Median 为 83.621 km，差于 ModuGeo 单工具；这说明当前主动定位候选在融合时会拉偏结果。

## 6. 调度与算法状态

### 6.1 RuleAgentScheduler

实现文件：

```text
src/agentic_ipv6_geo/scheduler/rule.py
```

当前规则：

1. 固定先调用 ModuGeo。
2. 固定调用 WHOIS/BGP 提供上下文。
3. 若目标存在 rDNS hostname，调用 rDNS，否则跳过。
4. 若被动 IPDB 启用，调用被动 IPDB。
5. 若 ModuGeo 置信度低于阈值，调用主动三角定位。
6. 将已调用工具输入 FusionTool。
7. 若融合结果可用且置信度达标，返回融合结果。
8. 否则返回融合结果或最高置信可用工具。

配置阈值：

| 参数 | 值 |
| --- | ---: |
| `modugeo_low_confidence` | 0.62 |
| `final_confidence_threshold` | 0.55 |

E01 结果：

| 指标 | 值 |
| --- | ---: |
| Median | 31.813 km |
| Mean | 67.999 km |
| P90 | 140.911 km |
| Coverage | 100% |
| AvgToolCalls | 2 |

### 6.2 ContextualBanditScheduler

实现文件：

```text
src/agentic_ipv6_geo/scheduler/bandit.py
```

当前 Bandit 训练阶段在训练集模拟动作：

- `stop`
- `rdns`
- `active`
- `all`

上下文包括：

- ModuGeo 置信度桶。
- rDNS 是否可用。
- 主动约束是否达到 3 个。
- operator。

奖励形式：

```text
reward = -error - tool_cost_weight * tool_calls - probe_cost_weight * probe_count
```

配置：

| 参数 | 值 |
| --- | ---: |
| tool_cost_weight | 10.0 |
| probe_cost_weight | 2.0 |
| min_samples_per_context | 2 |

E01 结果与 Rule 调度相同，未超过 ModuGeo baseline。

### 6.3 QwenToolUseScheduler

实现文件：

```text
src/agentic_ipv6_geo/scheduler/qwen.py
```

当前 Qwen baseline 是受限工具选择器：

- 只允许从 `stop`、`rdns`、`active`、`passive`、`all` 中选择动作。
- 不允许直接输出经纬度。
- 若未启用、缺少 API key、缺少 base URL 或返回非法动作，则默认 `stop`。

当前配置中：

```json
{
  "llm_baseline": {
    "enabled": false,
    "provider": "qwen",
    "model": "qwen3.5",
    "max_steps": 4
  }
}
```

因此 E01 中 Qwen baseline 实际表现为受限 fallback，结果与 ModuGeo 基线相同。

### 6.4 OfflineRewardPolicyScheduler

当前系统有离线奖励 policy 相关产物：

- `outputs/rl/reward_summary.json`
- `outputs/rl/offline_reward_comparison.json`
- `outputs/rl/policy.json`
- `outputs/rl/trajectories/`
- `outputs/rl/sft/tool_selection_sft.jsonl`

该部分是早期离线策略比较与 SFT 原型产物，不等同于正式 GRPO 训练。P0 后续已经将正式训练准备转移到无泄漏的 `outputs/p0/dataset/sft_seed.jsonl` 与 `outputs/p0/dataset/grpo_prompts.jsonl`。

### 6.5 GeoAgentEnv

实现文件：

```text
src/agentic_ipv6_geo/environment/env.py
```

当前环境特点：

- 基于离线工具回放，不在训练环境中重复执行真实外部工具。
- 每个 task 有模型可见任务、工具回放和私有真值。
- `reset(task_id)` 返回无真值观察。
- `step(action)` 执行动作并返回新观察、奖励和 done。
- 支持预算：
  - `max_steps`
  - `max_probe_count`
- 支持非法动作惩罚。
- 支持 `finalize` 与 `abstain`。
- `trajectory()` 导出时会执行无私有真值断言。

允许动作：

- `inspect_tool_applicability`
- `query_tool`
- `query_rdns`
- `run_active_solver`
- `query_passive_evidence`
- `inspect_result_quality`
- `compare_candidates`
- `finalize`
- `abstain`

当前奖励字段：

| 字段 | 含义 |
| --- | --- |
| `total` | 总奖励 |
| `geo` | 地理误差奖励 |
| `improve` | 相对 ModuGeo 改善 |
| `applicability` | 适用性奖励字段，当前 Schema 中保留 |
| `cost_penalty` | 步数和 probe 成本惩罚 |
| `invalid_penalty` | 非法动作惩罚 |
| `unsupported_penalty` | 选择不可见/无坐标候选的惩罚 |

## 7. E01 基线实验状态

实验路径：

```text
GraduatePaper/experiments/E01_baseline_trustgeo/results.md
GraduatePaper/outputs/trustgeo/
```

配置：

```text
configs/trustgeo.json
```

数据：

- 929 个目标 IP。
- 测试集 325 个 IP。

核心指标：

| 策略 | Median km | Mean km | P90 km | Coverage | AvgToolCalls | AvgProbeCost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ModuGeo | 31.813 | 67.999 | 140.911 | 1.000 | 1.000 | 0.000 |
| rDNS | — | — | — | 0.000 | 0.000 | 0.000 |
| ActiveTriangulation | 678.379 | 894.583 | 1846.980 | 0.594 | 1.000 | 2.609 |
| PassiveIPDB | — | — | — | 0.000 | 0.000 | 0.000 |
| ModuGeo + rDNS | 31.813 | 67.999 | 140.911 | 1.000 | 3.000 | 0.000 |
| ModuGeo + Active | 83.621 | 136.992 | 321.042 | 1.000 | 3.000 | 2.609 |
| ModuGeo + Passive | 31.813 | 67.999 | 140.911 | 1.000 | 3.000 | 0.000 |
| Fusion All | 83.621 | 136.992 | 321.042 | 1.000 | 5.000 | 2.609 |
| Rule Scheduler | 31.813 | 67.999 | 140.911 | 1.000 | 2.000 | 0.000 |
| Bandit Scheduler | 31.813 | 67.999 | 140.911 | 1.000 | 2.000 | 0.000 |
| Qwen Baseline | 31.813 | 67.999 | 140.911 | 1.000 | 2.000 | 0.000 |
| RL Policy | 31.813 | 68.987 | 148.618 | 1.000 | 2.006 | 0.018 |

E01 已生成产物：

- `outputs/trustgeo/metrics/summary.json`
- `outputs/trustgeo/metrics/summary.csv`
- `outputs/trustgeo/metrics/group_metrics.json`
- `outputs/trustgeo/figures/cost_accuracy_frontier.csv`
- `outputs/trustgeo/figures/*_error_cdf.csv`
- `outputs/trustgeo/predictions/*.jsonl`
- `outputs/trustgeo/实验报告.md`

## 8. P0 Agent 训练环境状态

### 8.1 P0 目标

P0 建设目标：

1. 建立模型可见任务与私有真值分离。
2. 统一工具输出为可训练观察。
3. 支持多轮动作与确定性回放。
4. 按 `/48` 前缀隔离划分数据。
5. 生成 SFT seed 与 GRPO prompts。
6. 审计数据泄漏。
7. 使用 Oracle 评估工具动作空间是否具备定位纠错收益。

### 8.2 P0 构建入口

命令：

```bash
cd /home/lzj/fusionprocessing/GraduatePaper
UV_CACHE_DIR=.uv-cache uv run ipv6geo-build-p0 \
  --config configs/trustgeo.json \
  --output-dir outputs/p0
```

构建器：

```text
src/agentic_ipv6_geo/data/p0_builder.py
```

Schema：

```text
src/agentic_ipv6_geo/environment/schemas.py
```

### 8.3 P0 产物

| 产物 | 数量 | 路径 |
| --- | ---: | --- |
| 模型可见任务 | 929 | `outputs/p0/dataset/tasks.jsonl` |
| 私有真值 | 929 | `outputs/p0/dataset/private_truth.jsonl` |
| 工具回放 | 4,645 | `outputs/p0/dataset/tool_replay.jsonl` |
| SFT seed | 650 | `outputs/p0/dataset/sft_seed.jsonl` |
| GRPO prompts | 650 | `outputs/p0/dataset/grpo_prompts.jsonl` |
| 划分文件 | 1 | `outputs/p0/dataset/splits.json` |
| Oracle 审计 | 929 rows | `outputs/p0/audit/oracle_audit.json` |
| 泄漏审计 | 1 | `outputs/p0/audit/leakage_audit.json` |
| 回放审计 | 1 | `outputs/p0/audit/replay_audit.json` |
| 构建清单 | 1 | `outputs/p0/build_manifest.json` |
| P0 汇总 | 1 | `outputs/p0/p0_summary.json` |

### 8.4 P0 工具回放状态

| 工具 | ok | unavailable |
| --- | ---: | ---: |
| ModuGeo | 929 | 0 |
| rDNS | 0 | 929 |
| ActiveTriangulation | 565 | 364 |
| PassiveIPDB | 0 | 929 |
| WHOIS/BGP | 929 | 0 |

总工具回放记录：

```text
929 targets * 5 tools = 4,645 rows
```

### 8.5 P0 泄漏审计

泄漏审计结果：

| 数据集 | finding_count |
| --- | ---: |
| tasks | 0 |
| tool_replay | 0 |
| sft_messages | 0 |
| grpo_prompts | 0 |

总 finding：

```text
0
```

审计结论：

```text
passed = true
```

泄漏扫描覆盖的私有字段包括真实位置、奖励和显式 truth 字段。旧评测器中曾出现的 `truth_region`、`truth_city` 已不再写入 P0 模型可见数据。

### 8.6 P0 确定性回放

回放审计：

| 项目 | 值 |
| --- | --- |
| passed | true |
| deterministic | true |
| task_id | `geo-00482bf9ca692fb1` |

这说明同一任务在相同离线回放数据和动作下，环境观察与奖励可复现。

### 8.7 P0 Oracle 审计

P0 Oracle 的含义：

> 在隐藏真值可见的审计侧，从当前可用工具候选中选择与真值距离最小的候选，计算理论上限。Oracle 不进入模型输入，不作为部署策略。

总体结果：

| 指标 | ModuGeo | Oracle |
| --- | ---: | ---: |
| Count | 929 | 929 |
| Median | 30.234 km | 30.022 km |
| Mean | 61.169 km | 60.628 km |
| P90 | 125.048 km | 125.048 km |

工具最优次数：

| 工具 | 次数 |
| --- | ---: |
| ModuGeo | 881 |
| ActiveTriangulation | 48 |

非 ModuGeo 改善：

| 项目 | 值 |
| --- | ---: |
| improved_count | 48 |
| improvement_rate | 5.17% |
| mean_improvement_km | 0.541 |

按 split：

| Split | Count | ModuGeo Median | ModuGeo Mean | ModuGeo P90 | Oracle Median | Oracle Mean | Oracle P90 | 非 ModuGeo 改善 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| train | 650 | 29.238 | 63.092 | 134.309 | 28.840 | 62.452 | 133.895 | 35 |
| validation | 93 | 28.569 | 51.076 | 106.817 | 28.181 | 50.679 | 106.817 | 6 |
| test | 93 | 37.233 | 45.997 | 94.422 | 37.233 | 45.883 | 94.422 | 2 |
| test_prefix_ood | 93 | 32.050 | 72.995 | 140.911 | 32.050 | 72.568 | 140.911 | 5 |

### 8.8 P0 门禁字段

`outputs/p0/p0_summary.json` 中：

```json
{
  "p0_build_complete": true,
  "precision_grpo_gate_passed": false
}
```

这里的 `precision_grpo_gate_passed=false` 是当前构建器根据 `oracle_min_improvement_rate=0.1` 得出的结果。当前非 ModuGeo 改善率为 5.17%，低于配置阈值 10%。

该字段表示“以坐标精度提升为主要目标的 GRPO 进入门禁未通过”。它不表示 P0 环境构建失败；P0 环境本身已完成构建并通过泄漏与回放检查。

## 9. SFT 与 GRPO 数据状态

### 9.1 SFT seed

路径：

```text
outputs/p0/dataset/sft_seed.jsonl
```

数量：

```text
650
```

当前 SFT seed 生成逻辑：

1. 仅使用 train split。
2. 初始 prompt 中包含：
   - task_id
   - target ip
   - `/48` prefix
   - asn
   - operator
   - available_tools
   - visible ModuGeo candidate
   - remaining_budget
3. 私有真值只用于审计侧选择教师动作，不写入 messages。
4. 若 Oracle 最优工具为 ModuGeo，教师轨迹为直接 `finalize`。
5. 若 Oracle 最优工具为其他工具，教师轨迹为 `query_tool` 后 `finalize`。
6. 若没有候选，教师轨迹为 `abstain`。

当前 SFT seed 状态：

- 已完成无泄漏构造。
- 可用于验证训练数据格式。
- 动作分布严重偏向 ModuGeo。
- 训练集中非 ModuGeo 教师轨迹为 35 条。
- 失败识别、质量判断、冲突、拒答和多轮轨迹覆盖不足。

### 9.2 GRPO prompts

路径：

```text
outputs/p0/dataset/grpo_prompts.jsonl
```

数量：

```text
650
```

当前 GRPO prompt 字段：

- `task_id`
- `split`
- `prompt`
- `environment_ref`
- `max_steps`
- `reward_profile`

当前状态：

- prompt 本身不包含私有真值。
- 每条 prompt 指向 `geoagent-p0-replay:v1`。
- 当前没有正式 GRPO rollout 训练脚本。
- 当前没有模型 checkpoint。
- 当前没有 GRPO 训练日志。

### 9.3 当前奖励环境

`GeoAgentEnv` 中已经实现位置误差奖励、相对 ModuGeo 改善、成本惩罚、非法动作惩罚和 unsupported candidate 惩罚。

当前奖励仍属于 P0 环境级原型：

- 可用于验证 episode 执行。
- 可用于测试合法动作与最终候选。
- 尚未与具体 RL trainer 打通。
- 尚未实现风险感知奖励、选择性输出奖励或校准奖励。

## 10. rDNS、主动定位、被动定位专题状态

### 10.1 E02 rDNS

实验目录：

```text
experiments/E02_rdns_enhancement/
```

状态：

```text
规划中
```

当前已知事实：

- TrustGeo 初始适配没有独立 rDNS 数据。
- 后续全量采集 21,088 个 IP，PTR 命中 212 个。
- PTR 命中率约 1.0%。
- E01 和 P0 评测中 rDNS 没有产生有效定位候选。

当前计划项：

- 更换 resolver。
- 分析 212 条 PTR 的地理词命中率。
- 统计命中省市分布。
- 若命中率无法达到有意义覆盖，作为负面结果记录。

### 10.2 E03 主动定位/CBG

实验目录：

```text
experiments/E03_cbg_probe_expansion/
```

状态：

```text
规划中
```

当前已知事实：

- TrustGeo probes 只有 3 个。
- E01 active coverage 约 59.4%。
- E01 active Median 678.379 km。
- P0 active 工具 565 个 ok，364 个 unavailable。
- P0 Oracle 中 active 只在 48/929 个目标上优于 ModuGeo。

当前计划项：

- 用 2,290 个 landmarks 扩充约束来源。
- 分析约束数量与误差关系。
- 验证 CBG、NCR、NCR-CBG 或其他求解方式。

### 10.3 E04 被动 IPDB

实验目录：

```text
experiments/E04_passive_ipdb/
```

状态：

```text
规划中
```

当前已知事实：

- PassiveIpDbGeoTool 已实现 multi backend。
- 本地缺少 `GeoCN.mmdb`。
- ip-database IPv6 数据文件当前不可用。
- Aiwen TSV 当前仅作为 IPv4 数据口径处理。
- E01 和 P0 中被动 IPDB 覆盖率为 0%。

当前计划项：

- 接入 GeoCN.mmdb 并确认许可证。
- 评估 ip2location-lite IPv6。
- 若无法取得可用数据，则记录为数据资源限制。

## 11. 风险与误差分布状态

当前 P0 中 ModuGeo 全量误差分布：

| 阈值 | 大于该阈值数量 | 比例 |
| --- | ---: | ---: |
| > 25 km | 525 | 56.51% |
| > 50 km | 296 | 31.86% |
| > 100 km | 126 | 13.56% |
| > 125 km | 93 | 10.01% |
| > 200 km | 45 | 4.84% |
| > 500 km | 7 | 0.75% |

选择性覆盖的理想上界，即假设可以按真实误差从小到大选择输出：

| 覆盖率 | 样本数 | Mean error | Max error |
| --- | ---: | ---: | ---: |
| 50% | 464 | 15.273 km | 30.224 km |
| 70% | 650 | 22.454 km | 54.305 km |
| 80% | 743 | 27.470 km | 72.790 km |
| 90% | 836 | 34.923 km | 124.551 km |
| 100% | 929 | 61.169 km | 2030.776 km |

这些数字说明当前数据中存在明显长尾误差；但这只是误差分布事实，不等同于已经实现风险预测模型。

## 12. W&B 状态

当前 P0 已同步到 W&B：

| 项目 | 值 |
| --- | --- |
| Team | `powerli_team` |
| Project | `GraduateProject` |
| Run | `https://wandb.ai/powerli_team/GraduateProject/runs/a5ygd2uv` |
| Report | `https://wandb.ai/powerli_team/GraduateProject/reports/GeoAgent-R1-P0-建设结果与结论--VmlldzoxNzE2MDE2Nw==` |
| Artifact | `powerli_team/GraduateProject/geoagent-p0-construction:latest` |

同步内容包括：

- P0 建设报告。
- 聚合指标。
- 构建清单。
- 审计结果。
- 工具能力达到上限时的条件转向方案。

未同步内容：

- `private_truth.jsonl`
- 原始定位数据
- API key
- 可恢复个人凭据

## 13. 当前文档状态

### 13.1 已存在文档

| 文档 | 作用 |
| --- | --- |
| `README.md` | 系统快速运行、工具、数据表、P0 入口 |
| `DASHBOARD.md` | 毕设进度看板 |
| `Agentic_IPv6_Geolocation_Plan.md` | 技术设计方案参考 |
| `reports/geoagent_sft_grpo_full_report.md` | SFT/GRPO 完整研究与实施说明 |
| `reports/p0_construction_report.md` | P0 建设报告 |
| `notes/agent_sft_grpo_research_route.md` | Agent/SFT/GRPO 路线笔记 |
| `notes/tool_ceiling_alternative_route.md` | 工具能力达到上限时的条件转向方案 |
| `experiments/E01_baseline_trustgeo/results.md` | E01 基线结果 |
| `experiments/E02_rdns_enhancement/plan.md` | rDNS 实验计划 |
| `experiments/E03_cbg_probe_expansion/plan.md` | CBG 扩充实验计划 |
| `experiments/E04_passive_ipdb/plan.md` | 被动 IPDB 实验计划 |
| `experiments/E05_p0_environment/results.md` | P0 实验结果 |

### 13.2 本报告位置

当前整合报告路径：

```text
GraduatePaper/reports/current_integrated_status_report.md
```

本文档是综合快照，不替代以下文档的原始用途：

- `DASHBOARD.md` 仍用于短看板。
- `p0_construction_report.md` 仍用于 P0 阶段归档。
- `geoagent_sft_grpo_full_report.md` 仍用于路线和概念说明。
- `tool_ceiling_alternative_route.md` 仍用于条件方案说明。

## 14. 当前 Git 工作区状态说明

当前仓库存在多处未提交改动和未跟踪文件。与毕设相关的改动包括：

- `GraduatePaper/AGENTS.md`
- `GraduatePaper/DASHBOARD.md`
- `GraduatePaper/README.md`
- `GraduatePaper/configs/trustgeo.json`
- `GraduatePaper/pyproject.toml`
- `GraduatePaper/src/agentic_ipv6_geo/cli.py`
- `GraduatePaper/src/agentic_ipv6_geo/evaluation/evaluator.py`
- `GraduatePaper/src/agentic_ipv6_geo/data/p0_builder.py`
- `GraduatePaper/src/agentic_ipv6_geo/environment/`
- `GraduatePaper/tests/test_p0_environment.py`
- `GraduatePaper/experiments/E05_p0_environment/`
- `GraduatePaper/reports/`
- `GraduatePaper/notes/agent_sft_grpo_research_route.md`
- `GraduatePaper/notes/tool_ceiling_alternative_route.md`

当前工作区还存在根服务目录和其他路径的改动，例如：

- `docker/docker-compose.yml`
- `services/agent/tools/__init__.py`
- `services/agent/tools/base.py`
- `services/agent/tools/dns_lookup_tool.py`
- `services/agent/tools/geoip_lookup_tool.py`
- 根目录 `data/`
- `collected_data.dump`

本文档没有整理这些根服务目录改动的实现状态；它们不属于 `GraduatePaper/` 当前毕设实验系统的主要状态描述范围。

## 15. 当前可复现命令清单

### 15.1 安装/同步环境

```bash
cd /home/lzj/fusionprocessing/GraduatePaper
UV_CACHE_DIR=.uv-cache uv sync
```

### 15.2 运行测试

```bash
cd /home/lzj/fusionprocessing/GraduatePaper
UV_CACHE_DIR=.uv-cache uv run python -m unittest discover -s tests -v
```

### 15.3 适配 TrustGeo

```bash
cd /home/lzj/fusionprocessing/GraduatePaper
UV_CACHE_DIR=.uv-cache uv run ipv6geo-prepare-trustgeo \
  --trustgeo-root /home/lzj/TrustGeo \
  --output-dir data/trustgeo_processed
```

### 15.4 校验数据

```bash
cd /home/lzj/fusionprocessing/GraduatePaper
UV_CACHE_DIR=.uv-cache uv run ipv6geo-validate \
  --config configs/trustgeo.json \
  --output outputs/trustgeo/metrics/data_validation.json
```

### 15.5 运行 E01 评测

```bash
cd /home/lzj/fusionprocessing/GraduatePaper
UV_CACHE_DIR=.uv-cache uv run ipv6geo-eval \
  --config configs/trustgeo.json \
  --output-dir outputs/trustgeo
```

### 15.6 批量定位

```bash
cd /home/lzj/fusionprocessing/GraduatePaper
UV_CACHE_DIR=.uv-cache uv run ipv6geo-run \
  --config configs/trustgeo.json \
  --targets data/trustgeo_processed/targets.csv \
  --output outputs/trustgeo/predictions/batch_predictions.jsonl
```

### 15.7 构建 P0

```bash
cd /home/lzj/fusionprocessing/GraduatePaper
UV_CACHE_DIR=.uv-cache uv run ipv6geo-build-p0 \
  --config configs/trustgeo.json \
  --output-dir outputs/p0
```

### 15.8 采集 rDNS

```bash
cd /home/lzj/fusionprocessing/GraduatePaper
UV_CACHE_DIR=.uv-cache uv run ipv6geo-collect-rdns \
  --input /home/lzj/TrustGeo/data/ipgeo_collected_data_20260114.csv \
  --ip-version 6 \
  --zdns-bin outputs/rdns_test/zdns \
  --resolver 1.1.1.1 \
  --output-jsonl outputs/rdns/zdns_ptr_results.jsonl \
  --output-rdns-csv data/trustgeo_processed/rdns.csv \
  --summary outputs/rdns/zdns_ptr_summary.json
```

### 15.9 启动 Dashboard

```bash
cd /home/lzj/fusionprocessing/GraduatePaper
UV_CACHE_DIR=.uv-cache uv sync --extra ui
UV_CACHE_DIR=.uv-cache uv run ipv6geo-dashboard \
  --config configs/trustgeo.json \
  --server-port 8501 \
  --server-address 127.0.0.1
```

### 15.10 启动 MCP

```bash
cd /home/lzj/fusionprocessing/GraduatePaper
UV_CACHE_DIR=.uv-cache uv sync --extra mcp
UV_CACHE_DIR=.uv-cache uv run ipv6geo-mcp --config configs/trustgeo.json
```

## 16. 当前开放事项清单

本节只列事实层面的开放事项，不将其排序为唯一研究路线。

### 16.1 数据与工具

- rDNS 当前 PTR 命中率约 1%，P0 工具回放未产生可用定位候选。
- 主动定位当前受限于 3 个 probes；CBG 测试集 Median 为 678.379 km。
- Landmarks 有 2,290 个，但尚未完成作为主动约束来源的完整实验。
- 被动 IPDB backend 框架存在，但缺少可用 IPv6 数据文件。
- WHOIS/BGP 可提供上下文，但当前不作为强定位器。

### 16.2 评测与实验

- E01 已完成。
- E05 已完成。
- E02、E03、E04 仍为规划状态。
- P0 Oracle 门禁显示当前非 ModuGeo 工具互补收益不足以通过 10% 改善率阈值。
- 当前缺少正式 SFT、DPO、GRPO、Prompt-only 多轮 Agent 的对比实验结果。

### 16.3 训练数据

- P0 SFT seed 已生成 650 条。
- P0 GRPO prompts 已生成 650 条。
- SFT seed 当前动作分布偏向直接采用 ModuGeo。
- 失败诊断、质量判断、冲突处理、拒答、降级输出等轨迹覆盖不足。

### 16.4 模型训练

- 尚未进行 LoRA/QLoRA SFT。
- 尚未进行 GRPO。
- 尚无模型 checkpoint。
- 尚无训练日志、训练曲线和训练后策略评测结果。

### 16.5 工程与复现

- `uv` 环境和测试已验证。
- P0 entry point 已验证。
- W&B P0 报告和 Artifact 已同步。
- 当前工作区存在较多未提交改动，正式归档前需要区分毕设相关改动与根服务目录改动。

## 17. 关键词

中文关键词：

- IPv6 地理位置推断
- LLM Agent
- 工具调用
- 主动定位
- 被动定位
- rDNS
- CBG
- ModuGeo
- SFT
- GRPO
- 可验证强化学习
- Oracle 审计
- 真值泄漏
- 前缀隔离
- 风险感知
- 选择性输出
- 可信拒答

英文关键词：

- IPv6 Geolocation
- LLM Agent
- Tool Use
- Active Geolocation
- Passive Geolocation
- Reverse DNS
- Constraint-Based Geolocation
- ModuGeo
- Supervised Fine-Tuning
- Group Relative Policy Optimization
- Verifiable Reinforcement Learning
- Oracle Audit
- Label Leakage
- Prefix-Isolated Split
- Risk-Aware Agent
- Selective Prediction
- Abstention

