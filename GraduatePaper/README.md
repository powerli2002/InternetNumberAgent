# Agentic IPv6 Geolocation

本目录实现“基于 Agent 调度的 IPv6 地理位置推断系统”毕业论文实验。系统不让 LLM 直接预测经纬度，而是调度可复现工具，并输出位置、置信度、证据链、失败原因和调用成本。

## 快速运行

```bash
UV_CACHE_DIR=.uv-cache uv sync
UV_CACHE_DIR=.uv-cache uv run python -m unittest discover -s tests -v
UV_CACHE_DIR=.uv-cache uv run ipv6geo-eval --config configs/default.json --output-dir outputs
UV_CACHE_DIR=.uv-cache uv run ipv6geo-run --config configs/default.json --targets data/processed/targets.csv --output outputs/predictions/batch_predictions.jsonl
```

## 使用 TrustGeo 数据

```bash
UV_CACHE_DIR=.uv-cache uv run ipv6geo-prepare-trustgeo --trustgeo-root /home/lzj/TrustGeo --output-dir data/trustgeo_processed
UV_CACHE_DIR=.uv-cache uv run ipv6geo-validate --config configs/trustgeo.json --output outputs/trustgeo/metrics/data_validation.json
UV_CACHE_DIR=.uv-cache uv run ipv6geo-eval --config configs/trustgeo.json --output-dir outputs/trustgeo
UV_CACHE_DIR=.uv-cache uv run ipv6geo-run --config configs/trustgeo.json --targets data/trustgeo_processed/targets.csv --output outputs/trustgeo/predictions/batch_predictions.jsonl
```

TrustGeo 适配器会复用 `pfxgeo_v11/predictions.csv`、`probe_results_0122.csv`、`pfx2as_v6_processed.csv`、AS WHOIS GPS 与城市坐标表。实现细节见 `实现过程.md`。

## 可视化界面

安装并启动 Streamlit Dashboard：

```bash
UV_CACHE_DIR=.uv-cache uv sync --extra ui
UV_CACHE_DIR=.uv-cache uv run ipv6geo-dashboard --config configs/trustgeo.json --server-port 8501 --server-address 127.0.0.1
```

界面支持 TrustGeo 数据适配、数据校验、单 IP 自动定位、规则调度/Bandit 调度选择、各工具输出对比、置信度与误差展示、评测运行、成本-精度前沿和实验报告查看。自动定位页会用类似 LangSmith trace 的节点流展示工具选择情况、调用/跳过原因、节点状态和最终融合结果。

## 主动探测与密钥

默认配置保持离线复现，不会自动发起 RIPE Atlas、scamper 或 Qwen 请求。若要启用真实主动探测，需要在配置中设置 `active_probe.allow_live_measurements=true`，并通过环境变量提供凭据：

```bash
export RIPE_ATLAS_API_KEY="..."
# 或者在只拿到完整 Authorization header 时：
export RIPE_ATLAS_AUTH_HEADER="Authorization header value"
export QWEN_API_KEY="..."
export QWEN_BASE_URL="https://..."
```

API key 不写入 `configs/*.json`。RIPE Atlas 实现规范见 `skills/ripe-atlas/SKILL.md`。

## 模块

- `src/agentic_ipv6_geo/data/`：CSV 数据加载与训练/评测切分。
- `src/agentic_ipv6_geo/tools/`：`ModuGeoTool`、`RDnsGeoTool`、`ActiveTriangulationTool`、`PassiveIpDbGeoTool`、`WhoisBgpContextTool`。
- `src/agentic_ipv6_geo/providers/`：scamper、rDNS、RIPE Atlas 主动探测 provider。
- `src/agentic_ipv6_geo/tools/registry.py`：统一方法注册表，前端、调度器和评测器通过同一入口构造方法，后续新增方法时优先扩展这里。
- `src/agentic_ipv6_geo/fusion/`：置信度加权融合与冲突惩罚。
- `src/agentic_ipv6_geo/scheduler/`：规则式调度、Contextual Bandit、Qwen3.5 baseline、离线奖励 policy。
- `src/agentic_ipv6_geo/evaluation/`：单工具、融合方案、调度策略评测与 RL trajectory 输出。
- `configs/default.json`：默认实验配置。
- `data/processed/*.csv`：可复跑样例数据，也可替换为真实处理后数据。

`ActiveTriangulationTool` 默认复用 `GraduatePaper/cbgtool` 中已经实现的 CBG 约束圆交集方法；NCRGeo 与 NCR-CBG 混合方法保留为配置级备选。默认流程不强制安装 NCR 所需的 SciPy/ujson；如要单独实验 NCR/NCR-CBG，可运行 `UV_CACHE_DIR=.uv-cache uv sync --extra active` 后将 `active_triangulation.algorithm` 改为 `ncr` 或 `ncr-cbg`。

## 数据表

默认读取以下 CSV：

- `targets.csv`：`ip,lat,lon,region,city,asn,operator,observed_at`
- `traces.csv`：`target_ip,probe_id,hop_ip,hop_index,rtt_ms,measured_at`
- `probes.csv`：`probe_id,lat,lon,region,city,operator,network_type`
- `metadata.csv`：`prefix,bgp_prefix,asn,org,operator,registered_region,registered_city`
- `rdns.csv`：`ip,hostname,resolved_at`
- `landmarks.csv`：`ip,lat,lon,region,city,rtt_ms`

缺失数据不会被伪造；对应工具会返回 `unavailable` 并写入失败原因。

被动 IPDB 可使用独立 CSV，推荐字段为 `ip,prefix,lat,lon,region,city,granularity,confidence,database,version`。如果同时存在 `ip` 和 `prefix`，工具优先匹配单 IP，其次做最长前缀匹配。
