# GraduatePaper - 毕业论文实验入口规范

## 角色定位
- 本目录用于建设“基于 Agent 调度的 IPv6 地理位置推断系统”毕业论文实验，不用于维护主仓库现有的互联网号码资源问答主链路。
- 目标是在 `ModuGeo` 基础上，补充独立证据工具、调度策略、融合逻辑与评测闭环，形成可复现实验系统。
- 这里的实现重点是“研究实验可复现性”，不是产品化问答服务；结论必须能由数据、代码、日志和评测结果支撑。

## 先读哪些文件
1. `GraduatePaper/Agentic_IPv6_Geolocation_Plan.md`
   这是当前毕设实验的目标、MVP 范围、工具边界和评测要求。
2. `GraduatePaper/ipgeotools/Modugeo/samplepaper.tex`
   这是 ModuGeo 论文材料，用于理解核心模型假设、特征设计和系统输入输出。
3. `GraduatePaper/ref/`
   这里存放 rDNS、CBG 等参考论文，仅作为实现依据，不作为运行时代码来源。
4. 仓库根 `AGENTS.md` 与 `docs/README.md`
   用于理解仓库级协作规则、文档治理方式以及与主系统的边界。

## 本目录的核心目标
- 复现并封装 `ModuGeo` 能力，使其能作为统一工具被调度。
- 实现与 `ModuGeo` 证据独立的辅助定位工具，优先包括：
  - `RDnsGeoTool`
  - `ActiveTriangulationTool`（默认复用 `GraduatePaper/ipgeotools/cbgtool` 的 CBG，NCR/NCR-CBG 作为备选）
  - `WhoisBgpContextTool`
- 实现规则式调度器、融合模块和批量评测模块。
- 对单工具、融合方案、调度策略进行可重复实验，并输出结构化结果。

## 与主仓库的边界
- `GraduatePaper/` 是研究实验区，允许建立独立的数据处理、工具、评测和实验脚本。
- 不要把毕业论文实验中的临时数据结构、原型脚本或未稳定模块直接混入主系统在线链路。
- 若某项能力后续要进入主仓库正式系统，必须在完成实验验证后再单独设计集成方案。
- 主仓库“16 张核心表事实源”的约束主要适用于问答系统主链路；本目录内的实验数据可独立组织，但不要反向污染主系统 schema。

## 外部参考与代码来源
- `GraduatePaper/ipgeotools/Modugeo/samplepaper.tex` 是 ModuGeo 的论文级参考。
- `/home/lzj/TrustGeo/src/prefixgeo/v11` 可作为现有实现参考，但默认视为“外部参考目录”，不是本目录产物。
- `GraduatePaper/ref/` 中的论文可用于复现 `rDNS` 和 `CBG` 思路。
- 任何从外部实现借鉴的逻辑，都必须在本目录内重新整理为可运行、可解释、可评测的代码；不要做无法追踪的复制拼接。

## 强约束
- 所有毕设相关内容，包括数据、参考论文、实验脚本、结果、图表、日志、笔记，都优先放在 `GraduatePaper/` 下。
- 新实现必须围绕“工具化、可调度、可评测”组织，不能只写零散 notebook 而没有稳定入口。
- 不要把 `ModuGeo` 已有内部能力重复包装成独立工具：
  - 前缀先验属于 `ModuGeo`
  - last-hop/RTT 条件调制属于 `ModuGeo`
- `Whois/BGP/ASN` 默认只作为上下文证据，不应直接伪装成强定位器。
- 工具不可在缺失输入时伪造输出；无法定位时必须明确返回失败状态或 `unavailable`。
- 所有实验结论都必须能回溯到输入数据、参数配置、运行日志和评测结果。
- 代码注释必须使用简体中文；复杂算法在实现前先用注释写清楚思路。

## 推荐目录结构
```text
GraduatePaper/
  AGENTS.md
  Agentic_IPv6_Geolocation_Plan.md
  ipgeotools/
    Modugeo/
    cbgtool/
    scampertrace/
  ref/
  data/
    raw/
    interim/
    processed/
  src/
    data/
    tools/
    scheduler/
    fusion/
    evaluation/
    common/
  configs/
  scripts/
  experiments/
  outputs/
    metrics/
    predictions/
    figures/
    logs/
  worklog.md
```

`ipgeotools/` 用于收纳外部工具、论文原型和主动探测工具快照；稳定实验入口仍应放在 `src/agentic_ipv6_geo/`、`scripts/` 与 `configs/` 中。`worklog.md` 用于研究笔记、阶段性分析和废弃方案说明，不作为默认运行入口。

## 模块设计要求

### 数据层
- 统一整理目标、探针、trace、metadata、rDNS、landmark 等输入。
- 原始数据与处理后数据分开存放，禁止覆盖原始快照。
- 处理脚本必须可重复执行，同样输入应得到同样输出。

### 工具层
- 每个定位工具都要有清晰输入契约、输出契约、失败状态和日志。
- 输出字段应尽量统一，至少包含：
  - `tool`
  - `status`
  - `location`
  - `granularity`
  - `confidence`
  - `cost`
  - `evidence`
  - `failure_reason`
- `RDnsGeoTool` 以区域级候选为主，证据不足时不要强出坐标。
- 主动三角定位工具在有效约束不足时直接返回不可用，不允许硬凑结果。

### 调度与融合层
- MVP 优先实现规则式调度，不先上复杂强化学习。
- 调度顺序、停机条件、调用成本都必须可配置、可记录、可复现。
- 融合模块必须显式处理工具冲突，而不是简单平均。

### 评测层
- 评测必须覆盖单工具、融合和调度三类实验。
- 指标至少包括：
  - `Median`
  - `Mean`
  - `P90`
  - `Coverage`
  - 平均工具调用数
  - 平均探针成本
- 评测脚本要支持批量运行，并把结果稳定落到 `outputs/` 或 `experiments/` 下。

## 命名与实现习惯
- 入口脚本尽量放到 `GraduatePaper/scripts/`。
- 研究代码尽量模块化放到 `GraduatePaper/src/`，不要把核心逻辑散落在多个一次性脚本里。
- 配置放到 `GraduatePaper/configs/`，不要把关键实验参数硬编码在脚本内部。
- 实验输出按“可复跑、可比对”组织，文件名应包含数据版本、方法名、时间或实验标签。

## 文档与记录要求
- 如果实现内容改变了本目录实验目标、数据口径、评测指标或默认流程，应同步改：
  - `GraduatePaper/Agentic_IPv6_Geolocation_Plan.md`
  - 本文件 `GraduatePaper/AGENTS.md`
- 若新增某个独立方法复现，至少补充：
  - 方法来源
  - 输入依赖
  - 输出定义
  - 失败条件
  - 与 `ModuGeo` 的证据独立性说明
- 历史废弃方案不要继续混在主说明里；如需保留，单独归档到本目录下的历史笔记位置，并明确标注“非当前默认方案”。

## 开发优先级
1. 先打通数据整理、`ModuGeoTool`、统一输出协议。
2. 再补 `RDnsGeoTool`、`ActiveTriangulationTool`、`WhoisBgpContextTool`。
3. 然后实现 `RuleAgentScheduler`、`FusionTool`、`Evaluator`。
4. MVP 稳定后，再考虑 contextual bandit 等学习型调度。

## 当前实现入口
- Python 包：`src/agentic_ipv6_geo/`
- 默认配置：`configs/default.json`
- 样例处理后数据：`data/processed/`
- 批量预测入口：`UV_CACHE_DIR=.uv-cache uv run ipv6geo-run --config configs/default.json --targets data/processed/targets.csv --output outputs/predictions/batch_predictions.jsonl`
- 评测入口：`UV_CACHE_DIR=.uv-cache uv run ipv6geo-eval --config configs/default.json --output-dir outputs`
- 测试入口：`UV_CACHE_DIR=.uv-cache uv run python -m unittest discover -s tests -v`
- 环境创建：`UV_CACHE_DIR=.uv-cache uv sync`
- MCP 工具服务：`UV_CACHE_DIR=.uv-cache uv sync --extra mcp` 后运行 `UV_CACHE_DIR=.uv-cache uv run ipv6geo-mcp --config configs/default.json`
- TrustGeo 数据适配：`UV_CACHE_DIR=.uv-cache uv run ipv6geo-prepare-trustgeo --trustgeo-root /home/lzj/TrustGeo --output-dir data/trustgeo_processed`
- TrustGeo 评测：`UV_CACHE_DIR=.uv-cache uv run ipv6geo-eval --config configs/trustgeo.json --output-dir outputs/trustgeo`
- 可视化界面：`UV_CACHE_DIR=.uv-cache uv sync --extra ui` 后运行 `UV_CACHE_DIR=.uv-cache uv run ipv6geo-dashboard --config configs/trustgeo.json --server-port 8501 --server-address 127.0.0.1`
- 批量 rDNS/PTR 采集：`UV_CACHE_DIR=.uv-cache uv run ipv6geo-collect-rdns --input /home/lzj/TrustGeo/data/ipgeo_collected_data_20260114.csv --ip-version 6 --zdns-bin outputs/rdns_test/zdns --resolver 1.1.1.1 --output-jsonl outputs/rdns/zdns_ptr_results.jsonl --output-rdns-csv data/trustgeo_processed/rdns.csv --summary outputs/rdns/zdns_ptr_summary.json`

## 交付标准
- 能批量输入 IPv6 目标并输出位置、置信度、证据链和成本信息。
- 各工具能独立运行并记录失败原因。
- 融合与调度实验能复现，并有结构化指标输出。
- 研究结论能回答这个问题：
  在 `ModuGeo` 已较强的前提下，独立证据工具和 agent 调度是否能在部分样本上提升可靠性，或在相同精度下降低调用成本。
