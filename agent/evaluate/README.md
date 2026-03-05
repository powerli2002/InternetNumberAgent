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
  - `LANGSMITH_TRACING=true`
  - `LANGSMITH_API_KEY=...`
  - `LANGSMITH_PROJECT=internet-number-qa`（可选，默认该值）
  - 评分模型密钥（任选其一）：
    - `DASHSCOPE_API_KEY`
    - `OPENAI_API_KEY`

## 2. 分步执行

```bash
python -m agent.evaluate.pipelines.generate_queries --count 30 --out agent/evaluate/data/queries.jsonl

# 重建 rubrics
python -m agent.evaluate.pipelines.build_graders --out agent/evaluate/data/rubrics.json

python -m agent.evaluate.pipelines.fill_answers --in agent/evaluate/data/queries.jsonl --out agent/evaluate/data/answers.jsonl

python -m agent.evaluate.pipelines.score_pipeline --in agent/evaluate/data/answers.jsonl --rubrics agent/evaluate/data/rubrics.json --out agent/evaluate/data/scored.jsonl --summary-out agent/evaluate/data/score_summary.json --manual-review-out agent/evaluate/data/manual_review.csv --push-langsmith

# 人工打分完成后，把可读版 YAML 转回 gold.jsonl（grader 范例集）
python -m agent.evaluate.pipelines.convert_gold_readable --readable agent/evaluate/data/gold.readable.yaml --out agent/evaluate/data/gold.jsonl --base-gold agent/evaluate/data/gold.jsonl --answers agent/evaluate/data/answers.jsonl

# 使用 gold.jsonl 驱动 Iterative Rubric（不会参与回答生成/自动评分输入）
# --rubric-labeled-data 使用 gold 数据驱动 rubic 产生
python -m agent.evaluate.pipelines.build_graders --out agent/evaluate/data/rubrics.json --rubric-labeled-data agent/evaluate/data/gold.jsonl
```

## 3. 一键执行

```bash
python -m agent.evaluate.pipelines.run_pipeline --count 30 --workdir agent/evaluate/data --push-langsmith
# 可选：在流水线末尾自动转换 gold.readable.yaml -> gold.jsonl
# --gold-readable agent/evaluate/data/gold.readable.yaml --gold-out agent/evaluate/data/gold.jsonl --gold-base agent/evaluate/data/gold.jsonl
```

## 4. 评分维度与总分

- `reasoning_planning = grader(reasoning_planning)`
- `tool_use_accuracy = grader(tool_use_accuracy)`
- `final_response_quality = grader(final_response_quality)`
- `evidence_groundedness = grader(evidence_groundedness)`

说明：
- 当前评分已收敛为 4 个 grader（每维 1 个），不再做维度内二次聚合。

总分：

```text
overall = 0.15*reasoning_planning + 0.15*tool_use_accuracy + 0.35*final_response_quality + 0.35*evidence_groundedness
```

人工 gold 转换时额外写入：

```text
main_score = 0.15*tool_use_accuracy + 0.15*reasoning_planning + 0.35*final_response_quality + 0.35*evidence_groundedness
tool_score = mean(tool_call_scores)（无评分时为 -1）
label_score = final_response_quality 二值化（>=0.5 记 1，否则记 0）
```

## 5. LangSmith 双记录

- Trace：`fill_answers` 阶段由 `FusionAgent` 写入 LangSmith trace。
- Experiment：`score_pipeline --push-langsmith` 阶段将缓存结果写入 dataset，并用 OpenJudge grader 作为 evaluator 回写评分反馈。

## 6. 人工复核

- `manual_review.csv` 已输出：
  - 模型总分与四维分
  - `human_score`、`human_comment` 待人工回填字段
- 推荐流程：
  1. 先按 `overall_score` 升序抽查低分样本。
  2. 再按 `status=error` 全量复核。
  3. 对分歧样本补充 `reference_answer`，用于下一轮增强评分一致性。
