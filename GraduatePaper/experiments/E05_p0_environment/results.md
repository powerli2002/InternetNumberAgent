# E05 P0 Agent 训练环境建设结果

**状态**：完成  
**日期**：2026-06-08  
**配置**：`configs/trustgeo.json`  
**运行命令**：

```bash
UV_CACHE_DIR=.uv-cache uv run ipv6geo-build-p0 \
  --config configs/trustgeo.json \
  --output-dir outputs/p0
```

## 建设内容

1. 定义统一的 Agent 动作、工具观察、候选位置、私有真值和奖励 Schema。
2. 将模型可见任务与私有真值分离，修复旧 SFT/trajectory 中的真值泄漏。
3. 实现真值与奖励字段自动泄漏扫描。
4. 实现基于离线工具回放的确定性多轮 `GeoAgentEnv`。
5. 按 `/48` 隔离划分 Train、Validation、Test 和 Prefix-OOD。
6. 为全部目标生成五类工具回放。
7. 生成无泄漏 SFT 种子轨迹和 GRPO prompts。
8. 实现并运行 Oracle 工具效用审计。

## 数据产物

| 产物 | 数量 | 路径 |
| --- | ---: | --- |
| 模型可见任务 | 929 | `outputs/p0/dataset/tasks.jsonl` |
| 私有真值 | 929 | `outputs/p0/dataset/private_truth.jsonl` |
| 工具回放 | 4,645 | `outputs/p0/dataset/tool_replay.jsonl` |
| SFT 种子轨迹 | 650 | `outputs/p0/dataset/sft_seed.jsonl` |
| GRPO prompts | 650 | `outputs/p0/dataset/grpo_prompts.jsonl` |
| Oracle 审计 | 929 | `outputs/p0/audit/oracle_audit.json` |
| 构建清单 | 1 | `outputs/p0/build_manifest.json` |

划分为 Train 650、Validation 93、Test 93、Test-Prefix-OOD 93；所有 `/48` 前缀只属于一个划分。

## 工具回放状态

| 工具 | OK | Unavailable |
| --- | ---: | ---: |
| ModuGeo | 929 | 0 |
| rDNS | 0 | 929 |
| 主动定位 | 565 | 364 |
| 被动 IPDB | 0 | 929 |
| WHOIS/BGP | 929 | 0 |

## P0 质量门禁

| 门禁 | 结果 |
| --- | --- |
| 模型可见任务真值泄漏 | 0，通过 |
| 工具回放真值泄漏 | 0，通过 |
| SFT messages 真值泄漏 | 0，通过 |
| GRPO prompts 真值泄漏 | 0，通过 |
| 环境确定性重放 | 通过 |
| 自动化测试 | 12/12 通过 |
| 定位纠错型 GRPO Oracle 门禁 | 未通过 |

P0 全量建设最初使用以下等价 Python 入口完成：

```bash
PYTHONPATH=src /opt/conda3/envs/netloc/bin/python -c \
  'from agentic_ipv6_geo.cli import build_p0_main; build_p0_main()' \
  --config configs/trustgeo.json \
  --output-dir outputs/p0
```

2026-06-08 已安装 `uv 0.11.19`，使用 Python 3.12 重建标准 `.venv`，并补充验证：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --python /opt/conda3/bin/python3.12
UV_CACHE_DIR=/tmp/uv-cache uv run python -m unittest discover -s tests -v
UV_CACHE_DIR=/tmp/uv-cache uv run ipv6geo-build-p0 --help
```

结果：依赖同步成功，12/12 测试通过，P0 entry point 可用。原 root 环境保留为 `.venv-root-broken-20260608`。

## Oracle 工具效用审计

| 指标 | ModuGeo | Oracle |
| --- | ---: | ---: |
| Median | 30.234 km | 30.022 km |
| Mean | 61.169 km | 60.628 km |
| P90 | 125.048 km | 125.048 km |

- 非 ModuGeo 工具改善目标：48/929，改善率 5.17%。
- 平均每目标改善：0.541 km。
- Oracle 最优工具：ModuGeo 881 次，主动定位 48 次。
- rDNS 与被动 IPDB 当前没有产生坐标候选。

## SFT 种子数据评估

650 条训练轨迹已经无泄漏并可用于数据构建验证，但不能直接作为正式 SFT 数据：

- 所有轨迹均包含 `finalize`。
- 只有 35 条训练轨迹调用非 ModuGeo 工具。
- 动作分布严重偏向直接采用 ModuGeo。
- 当前缺少足够的工具失败识别、质量判断、冲突、拒答和多轮轨迹。

## 结论

> P0 基础环境建设完成。当前系统已经具备无标签泄漏、前缀隔离、可确定性重放、可自动验证的 Agent 数据与环境基础，可以进入工具适用性、风险控制和多轮 SFT 数据构造阶段。

但当前工具动作空间没有达到定位纠错型 GRPO 的进入门禁：非 ModuGeo 工具仅改善 5.17% 的目标，Oracle P90 不变，rDNS 与被动 IPDB 当前没有定位候选。

下一阶段应优先：

1. 基于当前回放构造平衡的工具适用性与风险控制 SFT 数据。
2. 验证 landmarks 主动约束扩充能否提高主动定位互补收益。
3. 补充有效被动 IPv6 证据。
4. 工具适配后重新运行 Oracle 审计。
5. Oracle 改善率达到至少 10% 后，再进入定位纠错型 GRPO。

## W&B 同步

- Project：`powerli_team/GraduateProject`
- Run：https://wandb.ai/powerli_team/GraduateProject/runs/a5ygd2uv
- Report：https://wandb.ai/powerli_team/GraduateProject/reports/GeoAgent-R1-P0-建设结果与结论--VmlldzoxNzE2MDE2Nw==
- Artifact：`powerli_team/GraduateProject/geoagent-p0-construction:latest`

W&B 仅同步建设报告、聚合指标、构建清单和审计结果；未上传 `private_truth.jsonl` 与原始定位数据。
