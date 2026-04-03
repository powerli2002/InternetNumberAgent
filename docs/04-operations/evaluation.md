# 评测流水线

## 目标

评测链路用于批量生成问题、调用 `FusionAgent` 回答、抓取 LangSmith trace，并基于评分规则输出结构化评分结果。

当前实现位于 `agent/evaluate/`，默认流程包括：
- 生成问题集
- 生成回答与证据
- 构建评分 rubric
- 执行多维评分
- 将结果写回 LangSmith 或输出本地文件

## 目录结构
- `agent/evaluate/core/`：数据契约、配置、题库与评分提示模板
- `agent/evaluate/pipelines/`：四阶段流水线与总控入口
- `agent/evaluate/integrations/`：LangSmith 集成

## 前置条件
- 安装仓库依赖：`pip install -r requirements.txt`
- 配置 `LANGSMITH_API_KEY`
- 配置评分模型所需密钥，如 `DASHSCOPE_API_KEY` 或 `OPENAI_API_KEY`
- `fill_answers` 与 `run_pipeline` 会自动开启 LangSmith tracing，无需额外手工导出 `LANGSMITH_TRACING=true`

## 一键执行

```bash
python -m agent.evaluate.pipelines.run_pipeline --count 30 --workdir agent/evaluate/data --push-langsmith --langsmith-mode writeback
```

## 分步执行

```bash
python -m agent.evaluate.pipelines.generate_queries --count 30 --out agent/evaluate/data/queries.jsonl
python -m agent.evaluate.pipelines.build_graders --out agent/evaluate/data/rubrics.json
python -m agent.evaluate.pipelines.fill_answers --in agent/evaluate/data/queries.jsonl --out agent/evaluate/data/answers.jsonl
python -m agent.evaluate.pipelines.score_pipeline --in agent/evaluate/data/answers.jsonl --rubrics agent/evaluate/data/rubrics.json --out agent/evaluate/data/scored.jsonl --summary-out agent/evaluate/data/score_summary.json --manual-review-out agent/evaluate/data/manual_review.csv --push-langsmith --langsmith-mode writeback
```

## 主要产物
- `queries.jsonl`
- `answers.jsonl`
- `rubrics.json`
- `scored.jsonl`
- `score_summary.json`
- `manual_review.csv`

其中：
- `answers.jsonl` 会保留证据摘要、工具执行记录和 trace 相关字段
- `score_summary.json` 用于快速看总体分数和子评分均值
- `manual_review.csv` 用于人工复核低分样本

## 评分维度
- `reasoning_planning`
- `tool_selection_accuracy`
- `tool_argument_quality`
- `tool_outcome_effectiveness`
- `tool_use_accuracy`
- `final_response_quality`
- `evidence_groundedness`

当前总分口径：

```text
overall = 0.15*reasoning_planning + 0.15*tool_use_accuracy + 0.35*final_response_quality + 0.35*evidence_groundedness
```

其中：

```text
tool_use_accuracy = 0.4*tool_selection_accuracy + 0.3*tool_argument_quality + 0.3*tool_outcome_effectiveness
```

## LangSmith 写回
- `--langsmith-mode writeback`：把本地分数直接写回 LangSmith run outputs 和 feedback
- `--langsmith-mode evaluate`：在 LangSmith 中再次执行 evaluator，适合校验评分器行为

常规评测推荐使用 `writeback`。

## 人工复核建议
1. 先按 `overall_score` 升序抽查低分样本。
2. 再全量查看 `status=error` 的样本。
3. 重点看 `manual_review.csv` 中工具子评分，用于区分是选工具错、传参数错，还是结果未推动解题。

## 说明
- `fill_answers` 和 `run_pipeline` 会自动打开 LangSmith tracing。
- `answers.jsonl` 会保留证据摘要和工具执行记录，方便后续评分与人工复核。
- 若只需要模块说明，请看 `agent/evaluate/README.md`；实际命令入口以根 `README.md` 和本页为准。
