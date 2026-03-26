# OpenJudge 评测流水线（agent/evaluate）

本目录实现了完整的评测链路：

1. 生成问题（`queries.jsonl`）
2. 调用 `FusionAgent` 自动补齐回答并抓取 LangSmith trace（`answers.jsonl`）
3. 生成评分 Rubric（`rubrics.json`）
4. 执行多维评分并输出结果（`scored.jsonl` / `score_summary.json` / `manual_review.csv`）
5. 人工修订 `gold.readable.yaml` 后转换为 `gold.jsonl`（仅用于 grader 样本范例）

说明：`answers.jsonl` 会保存结构化证据字段：
- `evidence_items`：主链路产出的证据条目（title/source/content/score/metadata）
- `evidence_summary`：供评分器直接消费的证据摘要文本
- `tool_execution_records`：按实际执行顺序抽取的工具记录（step_id/name/arguments/status/error/result_preview）

已提供起步题集：
- `agent/evaluate/data/queries_seed_30.jsonl`（30 题）
- `agent/evaluate/data/queries_seed_26.jsonl`（同样内容，兼容旧文件名）

当前题库固定分布：`20 RAG（仅 Milvus 可答） + 5 NL2SQL + 5 Neo4j`。

## 目录结构

- `agent/evaluate/core/`
  - 数据契约、配置、题库、trace 提取、评分提示模板
- `agent/evaluate/pipelines/`
  - 四阶段流水线与总控实现
- `agent/evaluate/integrations/`
  - LangSmith 集成桥接
- `agent/evaluate/*.py`
  - 仅保留 CLI 兼容入口（薄封装，便于 `python -m agent.evaluate.xxx`）

## 1. 前置条件

- 安装依赖：
  - `pip install -r requirements.txt`
- 必要环境变量：
  - `LANGSMITH_API_KEY=...`
  - `LANGSMITH_PROJECT=internet-number-qa`（可选，默认该值）
  - 评分模型密钥（任选其一）：
    - `DASHSCOPE_API_KEY`
    - `OPENAI_API_KEY`

说明：
- `fill_answers` 与 `run_pipeline` 会在代码内自动写入 `LANGSMITH_TRACING=true`，无需每次手工导出该环境变量。

## 2. 分步执行

```bash
python -m agent.evaluate.pipelines.generate_queries --count 30 --out agent/evaluate/data/queries.jsonl

# 重建 rubrics
python -m agent.evaluate.pipelines.build_graders --out agent/evaluate/data/rubrics.json

# 会自动开启 LANGSMITH_TRACING=true
python -m agent.evaluate.pipelines.fill_answers --in agent/evaluate/data/queries.jsonl --out agent/evaluate/data/answers.jsonl

python -m agent.evaluate.pipelines.score_pipeline --in agent/evaluate/data/answers.jsonl --rubrics agent/evaluate/data/rubrics.json --out agent/evaluate/data/scored.jsonl --summary-out agent/evaluate/data/score_summary.json --manual-review-out agent/evaluate/data/manual_review.csv --push-langsmith --langsmith-mode writeback

# 对已存在的 answers.jsonl 做后补工具重评分：
# 1) 先基于 node_records/final_state_output 重建 tool_execution_records / trajectory_messages
# 2) 再重新计算三个 tool 子评分、tool_use_accuracy 与 overall
python -m agent.evaluate.pipelines.score_pipeline --in agent/evaluate/data/answers.jsonl --rubrics agent/evaluate/data/rubrics.json --out agent/evaluate/data/scored.posthoc.jsonl --summary-out agent/evaluate/data/score_summary.posthoc.json --manual-review-out agent/evaluate/data/manual_review.posthoc.csv --posthoc-tool-rescore --posthoc-answers-out agent/evaluate/data/answers.posthoc.jsonl --push-langsmith --langsmith-mode writeback

# 人工打分完成后，把可读版 YAML 转回 gold.jsonl（grader 范例集）
python -m agent.evaluate.pipelines.convert_gold_readable --readable agent/evaluate/data/gold.readable.yaml --out agent/evaluate/data/gold.jsonl --base-gold agent/evaluate/data/gold.jsonl --answers agent/evaluate/data/answers.jsonl

# 使用 gold.jsonl 驱动 Iterative Rubric（不会参与回答生成/自动评分输入）
# --rubric-labeled-data 使用 gold 数据驱动 rubic 产生
python -m agent.evaluate.pipelines.build_graders --out agent/evaluate/data/rubrics.json --rubric-labeled-data agent/evaluate/data/gold.jsonl
```

## 3. 一键执行

```bash
# 会自动开启 LANGSMITH_TRACING=true；默认将本地分数直写回 LangSmith
python -m agent.evaluate.pipelines.run_pipeline --count 30 --workdir agent/evaluate/data --push-langsmith --langsmith-mode writeback
# 可选：在流水线末尾自动转换 gold.readable.yaml -> gold.jsonl
# --gold-readable agent/evaluate/data/gold.readable.yaml --gold-out agent/evaluate/data/gold.jsonl --gold-base agent/evaluate/data/gold.jsonl
```

## 4. 评分维度与总分

- `reasoning_planning = PlanFeasibilityGrader(plan_text, observation_text, memory_text)`
- `tool_selection_accuracy = F1(expected_tools, actual_tools)`
- `tool_argument_quality = ToolParameterCheckGrader(query, tool_definitions, tool_calls)`
- `tool_outcome_effectiveness = TrajectoryComprehensiveGrader(query, trajectory_messages, answer)`
- `tool_use_accuracy = 0.4*tool_selection_accuracy + 0.3*tool_argument_quality + 0.3*tool_outcome_effectiveness`
- `final_response_quality = grader(final_response_quality)`
- `evidence_groundedness = grader(evidence_groundedness)`

说明：
- 对外主维度仍保持 4 个，其中 `tool_use_accuracy` 改为工具子评分聚合项，便于维持历史 `overall` 口径可比。
- `tool_selection_accuracy` 当前使用集合级 F1：只看“是否选到了必要工具、是否引入了无关工具”，不把同一工具的重复调用次数直接记为选择错误。
- `tool_argument_quality` 使用 OpenJudge 内置 `ToolParameterCheckGrader`，重点检查参数完整性、正确性、类型与是否幻觉。
- `tool_outcome_effectiveness` 使用 OpenJudge `TrajectoryComprehensiveGrader`，从完整工具轨迹判断每一步是否真正推动了解题。

总分：

```text
overall = 0.15*reasoning_planning + 0.15*tool_use_accuracy + 0.35*final_response_quality + 0.35*evidence_groundedness
```

其中：

```text
tool_use_accuracy = 0.4*tool_selection_accuracy + 0.3*tool_argument_quality + 0.3*tool_outcome_effectiveness
```

人工 gold 转换时额外写入：

```text
main_score = 0.15*tool_use_accuracy + 0.15*reasoning_planning + 0.35*final_response_quality + 0.35*evidence_groundedness
tool_score = mean(tool_call_scores)（无评分时为 -1）
label_score = final_response_quality 二值化（>=0.5 记 1，否则记 0）
```

说明：`build_graders --rubric-labeled-data` 当前仅消费 `label_score`（0/1），不再从 `scores_dim/main_score/overall_score` 回退派生。

自动评分产物补充：

- `scored.jsonl -> scores_raw` 会额外保留 `tool_selection_accuracy` / `tool_argument_quality` / `tool_outcome_effectiveness`
- `score_summary.json` 新增 `avg_tool_subscores` 与 `tool_subscore_weights`
- `manual_review.csv` 新增三个工具子评分列，便于快速定位“选工具 / 传参数 / 用结果”哪一层退化
- `--posthoc-tool-rescore` 模式会基于已保存 trace 重建工具链路输入，并在 `score_summary.json` 里写入 `posthoc_tool_rescore=true`
- 若传入 `--posthoc-answers-out`，会额外落盘重建后的 `answers.posthoc.jsonl`，便于后续复查或再次推送 LangSmith
- `--langsmith-mode writeback` 会把本地已算好的 `scores_raw/scores_dim/overall_score` 直接写成 LangSmith run outputs + feedback，不再重复调用 grader；`--langsmith-mode evaluate` 保留旧行为，会在 LangSmith 中再次执行 evaluator

## 5. LangSmith 双记录

- Trace：`fill_answers` 阶段由 `FusionAgent` 写入 LangSmith trace。
- Experiment：`score_pipeline --push-langsmith` 支持两种模式：
  - `--langsmith-mode writeback`：直接把本地分数写成 run outputs + feedback，适合常规评测与后补重评分。
  - `--langsmith-mode evaluate`：在 LangSmith 中再次执行 evaluator，便于核对 LangSmith evaluator 行为，但会重复调用 grader。
- 重复执行 `--push-langsmith` 时，会按稳定 `sample_id` 对 dataset example 做 create/update 分流，避免因重复样本触发 409。

可视化建议：

1. 运行 `score_pipeline --push-langsmith` 后，查看 `score_summary.json` 中的 `langsmith.experiment_url`。
2. 打开 Experiment 后，在 `Feedback` 侧栏按评分 key 过滤：`overall_score`、`tool_selection_accuracy`、`tool_argument_quality`、`tool_outcome_effectiveness`、`tool_use_accuracy` 等。
3. 点开单个 example，可在 `Outputs` 查看 `scores_raw`、`scores_dim`、`overall_score`、`score_reasons`，以及 `tool_execution_records`、`tool_calls`、`trajectory_messages`、`evidence_summary`，对照 feedback/comment 判断哪一层退化。
4. 若想看单样本链路细节，回到同 `trace_id` 对应的 Trace，结合计划节点、工具分发节点和 root outputs 联动排查。

## 6. 人工复核

- `manual_review.csv` 已输出：
  - 模型总分与四维分
  - `human_score`、`human_comment` 待人工回填字段
- 推荐流程：
  1. 先按 `overall_score` 升序抽查低分样本。
  2. 再按 `status=error` 全量复核。
  3. 对分歧样本补充 `reference_answer`，用于下一轮增强评分一致性。
