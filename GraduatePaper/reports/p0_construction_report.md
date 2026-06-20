# GeoAgent-R1 P0 建设报告

> 日期：2026-06-08  
> 状态：P0 基础环境建设完成；定位纠错型 GRPO 门禁未通过

## 目标

P0 建设在正式 SFT/GRPO 前建立可信训练基础：模型可见数据与私有真值分离、工具输出统一、多轮轨迹可确定性重放、数据按前缀隔离，并使用 Oracle 判断动作空间是否存在可学习定位收益。

## 实现

- `environment/schemas.py`：统一 Schema 与工具失败分类。
- `environment/leakage.py`：真值与奖励泄漏扫描。
- `environment/env.py`：多轮确定性回放环境。
- `environment/io.py`：从 P0 磁盘产物加载环境。
- `data/p0_builder.py`：前缀隔离划分、工具回放、SFT/GRPO 种子数据与 Oracle 审计。
- `ipv6geo-build-p0`：统一 P0 构建命令。
- `build_manifest.json`：记录输入文件 SHA-256、配置哈希、划分规模和门禁状态。

旧评测器不再将 `truth_region`、`truth_city` 写入 SFT 状态和 trajectory state，公开 SFT 样本不再保存奖励字段。

## 验证结果

| 检查项 | 结果 |
| --- | --- |
| 自动化测试 | 12/12 通过 |
| `/48` 隔离划分 | 通过 |
| 模型可见真值泄漏 | 0 |
| 确定性回放 | 通过 |
| 全量 P0 构建 | 929 个目标完成 |
| 工具回放 | 4,645 条 |
| SFT 种子 / GRPO prompts | 650 / 650 |

2026-06-08 已安装 `uv 0.11.19`，使用 Python 3.12 重建标准 `.venv`。`uv sync`、12/12 自动化测试和 `ipv6geo-build-p0` entry point 均已验证。原 root 环境保留为 `.venv-root-broken-20260608`。

## Oracle 结论

| 指标 | ModuGeo | Oracle |
| --- | ---: | ---: |
| Median | 30.234 km | 30.022 km |
| Mean | 61.169 km | 60.628 km |
| P90 | 125.048 km | 125.048 km |

非 ModuGeo 工具仅在 48/929 个目标上优于 ModuGeo，改善率 5.17%。现有动作空间不足以支撑以定位精度提升为主要奖励的正式 GRPO。

## 最终结论

P0 的工程建设目标已经完成：当前系统具备无泄漏、可隔离、可回放、可自动验证的训练环境基础。

P0 的研究门禁结论是条件性通过：

- **允许进入**：平衡 SFT 数据构造、工具适用性判断、失败识别、风险控制和多轮环境训练。
- **暂不允许进入**：以提升总体定位精度为核心目标的正式 GRPO。

下一阶段应先提高非 ModuGeo 工具的互补收益，或将 GRPO 奖励重点放在降低无效调用、抑制错误融合和可信停止上。

## W&B 同步

- Run：https://wandb.ai/powerli_team/GraduateProject/runs/a5ygd2uv
- Report：https://wandb.ai/powerli_team/GraduateProject/reports/GeoAgent-R1-P0-建设结果与结论--VmlldzoxNzE2MDE2Nw==
- Artifact：`powerli_team/GraduateProject/geoagent-p0-construction:latest`

同步内容不包含私有真值和原始定位数据。
