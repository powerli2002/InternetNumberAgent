# GraduatePaper — AI 协作规范

## 角色定位

本目录是"基于 Agent 调度的 IPv6 地理位置推断系统"毕业论文实验区，与主仓库 `services/` 的产品链路隔离。目标是用可复现实验验证：在 ModuGeo 已较强的前提下，多工具 Agent 调度能否在部分样本上提升可靠性或降低成本。

## 进度看板（首先读这里）

**`GraduatePaper/DASHBOARD.md`** — 实验台账、阻塞项、下一步任务、目录结构全在此文件。每次做实验前先读，做完后更新。

## 当前实验阶段

| ID | 名称 | 状态 |
|----|------|------|
| E01 | TrustGeo 基线 | ✅ 完成 |
| E02 | rDNS 覆盖率提升 | 📋 规划中 |
| E03 | CBG 探针扩充 | 📋 规划中（高优先级） |
| E04 | 被动 IPDB 接入 | 📋 规划中 |

## 必读文件

1. `GraduatePaper/DASHBOARD.md` — 进度总控
2. `GraduatePaper/Agentic_IPv6_Geolocation_Plan.md` — 技术设计方案
3. `GraduatePaper/experiments/E01_baseline_trustgeo/results.md` — 基线数据

## 当前运行入口

```bash
# 环境
UV_CACHE_DIR=.uv-cache uv sync

# TrustGeo 全量评测（主命令）
UV_CACHE_DIR=.uv-cache uv run ipv6geo-eval \
  --config configs/trustgeo.json \
  --output-dir outputs/trustgeo

# rDNS 重采集（E02）
UV_CACHE_DIR=.uv-cache uv run ipv6geo-collect-rdns \
  --input /home/lzj/TrustGeo/data/ipgeo_collected_data_20260114.csv \
  --ip-version 6 --resolver 8.8.8.8 \
  --output-jsonl outputs/rdns/zdns_ptr_results.jsonl \
  --output-rdns-csv data/trustgeo_processed/rdns.csv

# 测试
UV_CACHE_DIR=.uv-cache uv run python -m unittest discover -s tests -v
```

关键代码路径：

| 任务 | 文件 |
|------|------|
| CBG 修改入口（E03） | `src/agentic_ipv6_geo/tools/active_triangulation.py` |
| rDNS 采集（E02） | `src/agentic_ipv6_geo/providers/zdns.py` |
| 数据适配 | `src/agentic_ipv6_geo/data/trustgeo_adapter.py` |

## 强约束

- 工具不可在缺失输入时伪造输出；无法定位时必须明确返回失败或 `unavailable`。
- 所有实验结论必须能回溯到输入数据、配置、日志和评测结果。
- 代码注释使用简体中文。
- 不要把临时原型或未稳定模块直接混入主仓库 `services/` 链路。
- 前缀先验与 last-hop/RTT 条件调制属于 ModuGeo 内部，不要重复封装。

## 实验记录规范

- 实验完成后：在 `experiments/E0N_*/` 写 `results.md`，更新 `DASHBOARD.md` 实验台账。
- 解决阻塞项：从 `DASHBOARD.md` 第三节删除或标注已解决。
- 不追加"更新日志"：直接改正文，保持文档始终为当前真实状态。
