# 互联网号码资源问答系统（fusionprocessing）

本仓库是“互联网号码资源问答系统”MVP 的融合处理与智能体实现，负责多源数据清洗、实体化落库、向量索引与图谱构建，并通过 FusionAgent 提供可解释问答能力。当前架构已升级为：**LangGraph 主编排 + FastMCP 工具层（HTTP） + LangSmith 追踪（编排层与 MCP 服务端工具 span）**。复杂任务通过 LangGraph 子图执行，不再依赖 A2A/子代理服务；主图状态以 `MessagesState` 为对话主线，`messages` 是唯一对话真相源，并通过 LangGraph `PostgresSaver` 以原生 `thread_id`/checkpoint 方式持久化线程状态。流式回答链路已切换为 LangGraph 原生 `graph.stream(..., stream_mode=["custom", "updates"])`，由 `generate_answer` 节点通过 `get_stream_writer()` 直接发出 assistant 增量文本。

## 数据层目录迁移（2026-03-04）

融合数据处理相关目录已统一迁入 `fusiondata/`：

- `fusiondata/src/`
- `fusiondata/data/`
- `fusiondata/bgp_data/`
- `fusiondata/export_as_entity.py`
- `fusiondata/setup.py`

如需执行融合 CLI，请使用：

```bash
python fusiondata/setup.py {run|db|auto} -h
```

## 快速启动

启动cli
python agent/cli/main.py

启动mcp
python -m uvicorn agent.services.mcp.server:app --host 0.0.0.0 --port 2032


## 图查询链路升级（2026-02-25）

1. 新增 MCP 工具 `neo4j_llamaindex_query`：由工具内部通过 LlamaIndex 读取 Neo4j 当前 schema，生成 Cypher 并执行返回结果。
2. LangGraph `graph` 步骤不再在主流程预生成 Cypher，而是直接把自然语言问题交给 `neo4j_llamaindex_query`。
3. MCP 对外仅暴露 `neo4j_llamaindex_query`，不再公开 `neo4j_query`。

## 编排链路简化（2026-02-26）

1. LangGraph 主图移除 `classify` 节点；当前入口节点为 `reset_turn_state`，先清空上一轮遗留执行态，再进入 `plan`。
2. `available_tools` 探测下沉到 `plan` 节点，并在每轮重规划前重新探测。
3. 运行时 metadata 不再输出 `question_type`，统一聚焦计划与执行证据。

## 重规划去重优化（2026-02-27）

1. `plan` 节点新增输入：`previous_plan_steps` 与 `previous_step_summaries`，重规划时可感知历史执行结果。
2. `LANGGRAPH_PLAN_PROMPT` 增加“基于历史结果补缺、不重复生成已完成步骤”的约束。
3. 执行层新增步骤签名去重：同工具+同目标+同参数命中历史成功步骤时直接复用结果，避免重复查询。

## 规划驱动 `query_mode` 与 LLM 上下文压缩（2026-02-27）

1. NL2SQL 意图收敛为单一真值位 `query_mode=COUNT|GROUP_BY|EXISTS|OTHER`，由 `plan` 阶段一次性产出。
2. `execute` 阶段不再做规则式意图判断，只消费并透传 `query_mode` 到 MCP/NL2SQL。
3. NL2SQL 不再执行“聚合硬拦截+重生”；改为在同次 SQL 生成 prompt 中按 `query_mode` 引导 SQL 形态。
4. MCP `nl2sql_query` 新增 `query_mode`；`intent_policy/intent_labels_required` 进入兼容保留（deprecated）状态。
5. ContextBuilder 的 `build_with_trace()` 仅在上下文超过 `max_tokens` 时才调用 LLM 压缩；未超窗时直接保留结构化上下文。
6. `build_context` 优先消费当前轮 `step_results` 的结构化结果，不再优先依赖 `evidence preview`，避免 SQL 结果在进入上下文前被二次截断。
7. LangGraph 主图入口新增 `reset_turn_state`，显式清空上一轮遗留的 `step_results/evidences/context/conflicts` 等易变状态，避免跨 turn 污染 `conflict_check` 与后续节点。
8. `validate_plan` 会把“数量统计 + 前 N 示例”这类混合 NL2SQL 请求拆成两个独立步骤，避免生成非法聚合 SQL。
9. 对问候/感谢/能力询问等纯 `none` 计划回合，主图不再调用数据工具与 note 检索；回答阶段改为用“system + 历史消息 + 当前 query”生成回复，避免直接短路，也避免简单问题被检索上下文污染。

## 稳定性修复（2026-02-08）

本次针对编排与记忆链路完成了以下修复：

1. 修复语义记忆写入 Neo4j 的类型错误（map 属性），改为 `metadata_json + 结构化字段` 存储并支持反序列化检索。
2. 增强 Todo 解析，兼容 `subtasks/items/todos/plan` 输出结构，避免退化为单任务。
3. 增强图谱查询 Cypher 后验校验，关系类型越界时自动走兜底查询模板。
4. 增强 NL2SQL 超时退化：列检索超时时自动降级为表级检索重试。
5. RAG 索引写入支持增量去重：按 `source + text` 哈希过滤批内与存量重复切片，避免重复入库。
6. 补齐 `agent/knowledge/bgp/hijack_detection.md` 示例文件，chapter_5 路径可直接复现。
7. LangGraph 执行层新增 `nl2sql/graph` 首错入上下文重试机制，并支持 `question/questions` 列表串行执行。

## RAG 升级（2026-02-22）

1. 入库流程统一为 `Any -> MarkItDown -> Markdown 智能分块 -> Milvus`，避免多套转换逻辑并行。
2. RAG embedding 默认改为本地离线 `BAAI/bge-m3`，不再依赖在线 embedding API。
3. 召回策略默认启用 `MQE + RRF`（多查询扩展 + 融合排序），提高复杂查询的覆盖率。
4. 入库脚本与 MCP 检索统一复用同一 embedding 构造逻辑，避免“入库模型/查询模型”不一致。
5. NL2SQL 表/列检索 embedding 默认改为本地离线 `BAAI/bge-m3`，与 RAG 一致。
6. RAG 与 NL2SQL 的本地 embedding 实现统一为 `HuggingFaceEmbedding`；Milvus 存储仍可分离（`fusion_docs` 与 `nl2sql_index`）。

## 启动与部署（简版）

### 方式一：Docker Compose（推荐）

1. 启动基础服务（PostgreSQL / Milvus / Neo4j 等）  
   ```bash
   docker compose -f docker/docker-compose.yml up -d postgres etcd minio milvus neo4j
   ```

2. 导入 CSV（默认同时导入 PostgreSQL + Neo4j，手动触发）
   ```bash
   # 本机执行
   python -m agent.scripts.load_all_csv --config conf/config.docker.yaml --root . --date 2024-08-12 --ensure-core

   # 或在现有 agent 镜像中执行（无需本机安装 Python 依赖）
   docker compose -f docker/docker-compose.yml run --rm agent-mcp \
     python -m agent.scripts.load_all_csv --config conf/config.docker.yaml --root /work --date 2024-08-12 --ensure-core
   ```
   - 导入流程会自动应用统一 DDL：`database/core_schema.sql`
   - 导入入库时会统一规范化列名：`lowercase + underscore`（如 `v4Prefixes -> v4prefixes`、`CIDR -> cidr`、`admin-c -> admin_c`）
   - `python -m agent.scripts.load_all_csv` 默认启用 PostgreSQL + Neo4j 双库导入；Neo4j 默认不含 `website/industry`，可用 `--include-website/--include-industry` 开启
   - 双库一致性基于 PostgreSQL prepared transaction + Neo4j 单事务；Neo4j 失败会重试一次，重试耗尽则回滚到旧快照
   - 若只导入 PostgreSQL，可追加 `--no-neo4j`
   - 若异常中断后需排查 prepared 事务：
     ```sql
     SELECT gid, prepared FROM pg_prepared_xacts;
     -- 按 gid 处理
     COMMIT PREPARED '<gid>';
     ROLLBACK PREPARED '<gid>';
     ```
   - 如需单独执行：`python -m agent.scripts.ensure_core_schema --config conf/config.docker.yaml --root .`

3. （可选）离线预构建 NL2SQL 索引
   ```bash
   python -m agent.scripts.build_nl2sql_indexes
   ```
   - NL2SQL 表/列索引将写入 Milvus（单 collection + 分区），本地仅保留轻量 manifest
   - 当前 MCP 服务启动时也会阻塞式校验/预构建索引；此脚本更适合部署前预热、强制重建或排障

4. 启动智能体服务（MCP / API）
   ```bash
   docker compose -f docker/docker-compose.yml up -d agent-mcp agent-api
   ```

> API 默认端口：`2025`（访问 `http://localhost:2025/info` 验证）

### 方式二：本地运行（开发）

1. 安装依赖并启动服务
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
    # 可选：离线预构建 NL2SQL 索引（MCP 启动时也会自动校验/预构建）
    python -m agent.scripts.build_nl2sql_indexes
   uvicorn agent.services.mcp.server:app --host 0.0.0.0 --port 2032
   uvicorn agent.services.http.server:app --host 0.0.0.0 --port 2025
   ```

2. （可选）同步 RFC 知识并做 RAG 验证
   ```bash
   python -m agent.scripts.sync_rfc_docs --root .
   python agent/knowledge_ingest.py --root . --path agent/knowledge/rfc --collection fusion_docs_rfc_eval --reset
   python -m agent.scripts.evaluate_rfc_rag --root . --collection fusion_docs_rfc_eval --json-out agent/store/rfc/rag_eval_report.json --fail-under-hit3 0.9 --fail-under-mrr 0.75
   ```
   - 当前内置只抓指定 RFC：BGP `4271/4760/6793/7606`，WHOIS/RDAP `3912/7480/7481/7482/7483/9082/9083`
   - `sync_rfc_docs` 会把 RFC Editor 官方 `txt + json` 组装为结构化 Markdown，并落到 `agent/knowledge/rfc/<topic>/`
   - 建议先写入独立 collection `fusion_docs_rfc_eval` 做隔离验证；确认召回效果后，再执行 `python agent/knowledge_ingest.py --root . --path agent/knowledge` 增量并入当前主 collection

3. （可选）本机启动 vLLM（OpenAI 兼容接口）
   ```bash
   python agent/model/start_vllm.py
   ```
   - 然后在 `conf/.env` 中设置：
     - `LLM_BACKEND=local`
     - `LOCAL_LLM_API_KEY=your-local-key`
     - `LOCAL_LLM_BASE_URL=http://127.0.0.1:2222/v1`
      - `LOCAL_LLM_MODEL=QuantTrio/Qwen3.5-4B-AWQ`
      - `LOCAL_VLLM_MAX_MODEL_LEN=16384`
      - `LOCAL_VLLM_QUANTIZATION=awq`
      - `LOCAL_VLLM_DTYPE=half`
      - `LOCAL_VLLM_TENSOR_PARALLEL_SIZE=1`
      - `LOCAL_VLLM_CUDA_VISIBLE_DEVICES=0`
      - `LLM_TEMPERATURE=0.2`
      - `LLM_TOOL_TEMPERATURE=0.0`
      - `LLM_CONTEXT_COMPRESS_TEMPERATURE=0.0`
    - `agent/model/start_vllm.py` 当前默认不显式透传 `trust_remote_code`，并在 `tensor_parallel_size > 2` 时自动追加 `--disable-custom-all-reduce`，减少当前 4 张 `RTX 2080 Ti` 环境下的无效告警。
    - 启动脚本会自动读取 `conf/.env` 中的 `LOCAL_LLM_MODEL`、`LOCAL_LLM_API_KEY`、`LOCAL_LLM_BASE_URL`、`LOCAL_VLLM_MAX_MODEL_LEN`、`LOCAL_VLLM_QUANTIZATION`、`LOCAL_VLLM_DTYPE`、`LOCAL_VLLM_TENSOR_PARALLEL_SIZE`、`LOCAL_VLLM_CUDA_VISIBLE_DEVICES`，命令行参数仅用于显式覆盖默认值。
    - 当前默认本机模型改为 `QuantTrio/Qwen3.5-4B-AWQ`，它是基于 `Qwen/Qwen3.5-4B` 的 4-bit AWQ 量化版本；脚本会自动追加 `--quantization awq`、`--dtype half`。
    - 当前默认部署为单卡：`LOCAL_VLLM_TENSOR_PARALLEL_SIZE=1` 且 `LOCAL_VLLM_CUDA_VISIBLE_DEVICES=0`，vLLM 仅使用第 0 张 GPU。
    - 对 `Qwen3.5` 系列，脚本仍会额外默认追加 `--attention-backend TRITON_ATTN`、`--mm-encoder-attn-backend TRITON_ATTN`、`--language-model-only`、`--skip-mm-profiling`，并通过 `--default-chat-template-kwargs '{"enable_thinking": false}'` 默认关闭 thinking，避免本地 Agent 请求被长 `<think>` 链路拖慢。
    - `QuantTrio/Qwen3.5-4B-AWQ` 首次冷启动会先从 Hugging Face 下载约 6.1GB 权重；下载完成前 `2222` 端口不会进入监听状态。

4. 启动前端（Agent Chat UI）
   ```bash
   cd agent-chat-ui
   pnpm install
   pnpm dev --port 3012
   ```

> 前端默认连接 `http://localhost:2025`，assistantId 为 `fusion-agent`（可在页面配置或设置环境变量）。

## 常用端口

- API：`2025`
- MCP Tool Server：`2032`
- PostgreSQL：`5432`
- Neo4j：`7474/7687`
- Milvus：`19530/9091`
- Agent Chat UI：`3012`

关键环境变量：
- `MCP_SERVER_URL`（默认 `http://127.0.0.1:2032/mcp`）
- `AGENT_STORE_DIR`（统一存储根目录，默认 `agent/store`）
- `MEMORY_STORE_DIR`（情景记忆本地目录，默认 `agent/store/memory`）
- `NOTES_DIR`（笔记目录，默认 `agent/store/notes`）
- `NL2SQL_INDEX_CACHE_DIR`（NL2SQL 索引 manifest 目录，默认 `agent/store/index/nl2sql`）
- `NL2SQL_VECTOR_COLLECTION`（NL2SQL 向量索引的 Milvus collection 名称，默认 `nl2sql_index`）
- `REQUEST_TIMEOUT_SECONDS` / `AGENT_REQUEST_TIMEOUT_SECONDS`（统一默认超时，默认 `180` 秒）
- `CLI_TIMEOUT_SECONDS`（保留配置；当前 CLI 不设置外层超时，持续执行直到任务结束）
- `MCP_TIMEOUT_SECONDS`（MCP 客户端超时，默认继承 `REQUEST_TIMEOUT_SECONDS`）
- `LOCAL_VLLM_MAX_MODEL_LEN`（同时控制 Agent 上下文预算与本机 vLLM 总窗口，默认 `4096`）
- `LLM_BACKEND`（`cloud|local`，默认 `cloud`）
- `DASHSCOPE_API_KEY` / `DASHSCOPE_BASE_URL` / `DASHSCOPE_MODEL`（`LLM_BACKEND=cloud` 时必填）
- `LOCAL_LLM_API_KEY` / `LOCAL_LLM_BASE_URL` / `LOCAL_LLM_MODEL`（`LLM_BACKEND=local` 时必填）
- `LLM_TEMPERATURE`（普通文本生成温度，默认 `0.2`，用于最终回答与普通结构化文本生成）
- `LLM_TOOL_TEMPERATURE`（工具/规划温度，默认 `0.0`，用于 function calling、NL2SQL 与图查询）
- `LLM_CONTEXT_COMPRESS_TEMPERATURE`（上下文压缩温度，默认 `0.0`，优先保证压缩保真）
- `WORKING_MEMORY_SIZE` / `EPISODIC_MEMORY_SIZE` / `SEMANTIC_MEMORY_SIZE`（三层记忆容量）
- `RAG_EMBEDDING_BACKEND`（默认 `local_bge`）
- `RAG_EMBEDDING_MODEL`（默认 `BAAI/bge-m3`，也可填本地模型目录）
- `RAG_EMBEDDING_DEVICE`（默认 `cpu`）
- `NL2SQL_EMBEDDING_BACKEND`（默认 `local_bge`）
- `NL2SQL_EMBEDDING_MODEL`（默认 `BAAI/bge-m3`，也可填本地模型目录）
- `NL2SQL_EMBEDDING_DEVICE`（默认 `cpu`）
- `NL2SQL_EMBEDDING_BATCH_SIZE`（默认 `16`）
- `NL2SQL_EMBEDDING_NORMALIZE`（默认 `true`）
- `RAG_ENABLE_MQE`（默认 `true`）
- `VECTOR_COLLECTION`（RAG 向量集合，默认 `fusion_docs`）
- `NEO4J_DATABASE`（默认 `neo4j`）
- `GRAPH_MAX_ROWS` / `GRAPH_MAX_CYPHER_LENGTH`（图查询行数与 Cypher 长度上限）
- `NL2SQL_MAX_ROWS`（NL2SQL 默认基线行数上限；当前明细模式不单独抬高，统一保持该 LIMIT）
- `GRAPH_REFRESH_SCHEMA_EACH_QUERY`（默认 `true`，图查询前刷新 schema）
- `CONTEXT_COMPRESS_MODE`（兼容保留字段，当前固定按 `llm` 处理）
- `CONTEXT_COMPRESS_TARGET_RATIO`（LLM 压缩目标比例，默认 `0.7`）
- `ALLOWED_TABLES`（NL2SQL 白名单，逗号分隔）

## 运行时表说明

FusionAgent 启动后会在 PostgreSQL 中自动创建运行时表（非 16 张核心实体表），用于线程注册、LangGraph checkpoint 与记忆持久化：

- `agent_threads`：HTTP 线程注册与 metadata
- `checkpoint_migrations` / `checkpoints` / `checkpoint_blobs` / `checkpoint_writes`：LangGraph `PostgresSaver` 内部 checkpoint 表
- `agent_episodic_memory`：情景记忆条目

## 日志

后端 API 会使用统一 logger 记录请求与回复日志，默认写入：

- `logs/YYYY-MM/DD/fusion-YYYY-MM-DD-<pid>.log`

可通过环境变量控制：

- `API_LOG_ENABLED`：是否开启请求/回复日志（默认 `true`）
- `API_LOG_BODY_LIMIT`：日志中请求/回复体的最大长度（默认 `2000` 字节）
- `MODULE_LOG_ENABLED`：是否记录模块输入/输出（默认 `true`）
- `MODULE_LOG_BODY_LIMIT`：模块日志中单字段最大长度（默认 `2000` 字符）
- `MODULE_LOG_MAX_ITEMS`：模块日志最多记录的返回项数量（默认 `5`）
- MCP 工具调用会输出开始/结束（成功/失败）日志，并带 `elapsed` 耗时

当前采用“单 trace + 自动节点审计 + 服务端工具 span”模式：

- 每次提问应只生成一个 LangSmith trace；
- trace 下会有多个自动 run（LangGraph 节点、LLM 调用等）；
- MCP 客户端只透传 LangSmith 分布式追踪 headers，不再手工创建 `mcp_tool:*` / `mcp_list_tools` 子 run；
- MCP 服务端通过 `TracingMiddleware + ls_trace()` 记录工具 span，并自动挂到当前节点 run 下；
- 节点输入、prompt、上下文、输出直接写入自动节点 run，root 仅保留兼容性聚合字段。

按 `run.trace_id`（优先）或 `metadata.trace_id`（兼容）聚合链路：

```bash
python -m agent.scripts.trace_by_metadata_id \
  --project "${LANGSMITH_PROJECT}" \
  --trace-id "<run.trace_id 或 metadata.trace_id>" \
  --since-hours 24 \
  --show-io
```

更多监控与排障细节见：`docs/LangSmith监控指南.md`。

## Agent 目录分层（2026-02-06）

为降低耦合并便于扩展，`agent/` 已按分层重构：

- `agent/core/`：配置、模型、提示词、LLM、追踪、Schema
- `agent/runtime/`：FusionAgent 运行时编排（LangGraph 主图）
- `agent/services/http/`：FastAPI 接口与线程消息存储
- `agent/services/mcp/`：MCP 服务与客户端
- `agent/cli/`：命令行入口
- `agent/runtime/context_builder.py`、`agent/memory/`、`agent/tools/`：上下文、记忆、工具
- `agent/store/`：统一运行时存储目录（memory/index/notes）

注意：旧入口文件已移除，需统一使用新分层路径。

## OpenJudge 评测流水线（2026-03-03）

项目已提供数据驱动评测入口，目录在 `agent/evaluate/`，支持：

1. 生成起步评测题（默认 30 题）
2. 调用 FusionAgent 自动补齐答案并提取 trace
3. 生成 Rubric（Simple / Iterative）
4. 运行多维评分并写入 LangSmith Experiment
5. 人工修订 `gold.readable.yaml` 后转换为 `gold.jsonl`（仅作为 grader 范例集）

当前评分对外仍保持 4 个主维度：`reasoning_planning / tool_use_accuracy / final_response_quality / evidence_groundedness`。
其中 `tool_use_accuracy` 已升级为 3 个工具子评分聚合：

- `tool_selection_accuracy`：是否选对工具（集合级 F1）
- `tool_argument_quality`：工具参数是否完整、正确、无幻觉
- `tool_outcome_effectiveness`：工具结果是否真正推动最终回答

起步题集已生成：`agent/evaluate/data/queries_seed_30.jsonl`（兼容保留 `queries_seed_26.jsonl`）。
当前默认分布：`20 RAG（仅 Milvus 可答） + 5 NL2SQL + 5 Neo4j`。

常用命令：

```bash
python -m agent.evaluate.pipelines.generate_queries --count 30 --out agent/evaluate/data/queries.jsonl
# `fill_answers` 会自动开启 LANGSMITH_TRACING=true
python -m agent.evaluate.pipelines.fill_answers --in agent/evaluate/data/queries.jsonl --out agent/evaluate/data/answers.jsonl
python -m agent.evaluate.pipelines.build_graders --out agent/evaluate/data/rubrics.json
python -m agent.evaluate.pipelines.score_pipeline --in agent/evaluate/data/answers.jsonl --rubrics agent/evaluate/data/rubrics.json --out agent/evaluate/data/scored.jsonl --summary-out agent/evaluate/data/score_summary.json --manual-review-out agent/evaluate/data/manual_review.csv --push-langsmith --langsmith-mode writeback
# 对已完成的 answers.jsonl 做后补工具重评分
python -m agent.evaluate.pipelines.score_pipeline --in agent/evaluate/data/answers.jsonl --rubrics agent/evaluate/data/rubrics.json --out agent/evaluate/data/scored.posthoc.jsonl --summary-out agent/evaluate/data/score_summary.posthoc.json --manual-review-out agent/evaluate/data/manual_review.posthoc.csv --posthoc-tool-rescore --posthoc-answers-out agent/evaluate/data/answers.posthoc.jsonl --push-langsmith --langsmith-mode writeback
python -m agent.evaluate.pipelines.convert_gold_readable --readable agent/evaluate/data/gold.readable.yaml --out agent/evaluate/data/gold.jsonl --base-gold agent/evaluate/data/gold.jsonl --answers agent/evaluate/data/answers.jsonl
python -m agent.evaluate.pipelines.build_graders --out agent/evaluate/data/rubrics.json --rubric-labeled-data agent/evaluate/data/gold.jsonl
```

一键串行：

```bash
# `run_pipeline` 会自动开启 LANGSMITH_TRACING=true；默认推荐直写本地分数到 LangSmith
python -m agent.evaluate.pipelines.run_pipeline --count 30 --workdir agent/evaluate/data --push-langsmith --langsmith-mode writeback
# 若需要在一键流程末尾自动生成 gold.jsonl，可追加：
# --gold-readable agent/evaluate/data/gold.readable.yaml --gold-out agent/evaluate/data/gold.jsonl --gold-base agent/evaluate/data/gold.jsonl
```

说明：重复执行 `--push-langsmith` 时，会按稳定 sample id 更新 LangSmith dataset example，不再因重复样本返回 409。推荐使用 `--langsmith-mode writeback`，这样 LangSmith 里能直接看到 `overall_score`、四维主分、三个 tool 子分及其原因，且不会二次调用 grader；如需保留旧行为，可改用 `--langsmith-mode evaluate`。

## 详细文档

- 项目目标与数据结构：`summary.md`
- 部署与导入：`docs/部署.md`
- 系统技术文档：`docs/互联网号码资源问答系统技术文档.md`
- LangSmith 监控指南：`docs/LangSmith监控指南.md`
- Agent 目录说明：`agent/README.md`
- OpenJudge 评测说明：`agent/evaluate/README.md`
- 面试深潜文档：`agent/docs/system_architecture_deep_dive/README.md`
