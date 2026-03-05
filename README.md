# 互联网号码资源问答系统（fusionprocessing）

本仓库是“互联网号码资源问答系统”MVP 的融合处理与智能体实现，负责多源数据清洗、实体化落库、向量索引与图谱构建，并通过 FusionAgent 提供可解释问答能力。当前架构已升级为：**LangGraph 主编排 + FastMCP 工具层（HTTP） + LangSmith 追踪（编排层与 MCP 客户端）**。复杂任务通过 LangGraph 子图执行，不再依赖 A2A/子代理服务。

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

1. LangGraph 主图移除 `classify` 节点，入口节点调整为 `plan`。
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
5. ContextBuilder 新增 LLM 压缩能力：`CONTEXT_COMPRESS_MODE=llm|truncate|hybrid`，LLM 失败自动回退截断。

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

3. （可选）预构建 NL2SQL 索引
   ```bash
   python -m agent.scripts.build_nl2sql_indexes
   ```
   - NL2SQL 表/列索引将写入 Milvus（单 collection + 分区），本地仅保留轻量 manifest

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
   # 可选：预构建 NL2SQL 索引
   python -m agent.scripts.build_nl2sql_indexes
   uvicorn agent.services.mcp.server:app --host 0.0.0.0 --port 2032
   uvicorn agent.services.http.server:app --host 0.0.0.0 --port 2025
   ```

2. （可选）本机启动 vLLM（OpenAI 兼容接口）
   ```bash
   python -m agent.scripts.start_vllm --model Qwen/Qwen3-4B --port 2222 --api-key your-local-key
   ```
   - 然后在 `conf/.env` 中设置：
     - `LLM_BACKEND=local`
     - `LOCAL_LLM_API_KEY=your-local-key`
     - `LOCAL_LLM_BASE_URL=http://127.0.0.1:2222/v1`
     - `LOCAL_LLM_MODEL=Qwen/Qwen3-4B`

3. 启动前端（Agent Chat UI）
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
- `MAX_CONTEXT_TOKENS`（上下文窗口上限，默认 `4096`）
- `LLM_BACKEND`（`cloud|local`，默认 `cloud`）
- `DASHSCOPE_API_KEY` / `DASHSCOPE_BASE_URL` / `DASHSCOPE_MODEL`（`LLM_BACKEND=cloud` 时必填）
- `LOCAL_LLM_API_KEY` / `LOCAL_LLM_BASE_URL` / `LOCAL_LLM_MODEL`（`LLM_BACKEND=local` 时必填）
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
- `GRAPH_REFRESH_SCHEMA_EACH_QUERY`（默认 `true`，图查询前刷新 schema）
- `CONTEXT_COMPRESS_MODE`（`llm|truncate|hybrid`，默认 `hybrid`）
- `CONTEXT_COMPRESS_TARGET_RATIO`（LLM 压缩目标比例，默认 `0.7`）
- `ALLOWED_TABLES`（NL2SQL 白名单，逗号分隔）

## 运行时表说明

FusionAgent 启动后会在 PostgreSQL 中自动创建运行时表（非 16 张核心实体表），用于对话与记忆持久化：

- `agent_threads` / `agent_messages`：线程与消息记录
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

MCP 服务端默认不写 LangSmith 运行记录；当前采用“单 trace + 客户端子 run”模式：

- 每次提问应只生成一个 LangSmith trace；
- trace 下会有多个自动 run（LangGraph 节点、LLM 调用等）；
- MCP 客户端会写 `mcp_tool:*` / `mcp_list_tools` 子 run，但仅在检测到有效 `root_run` 时创建，强制挂到同一 trace；
- 不再依赖手工 `graph_node:*` run。

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

起步题集已生成：`agent/evaluate/data/queries_seed_30.jsonl`（兼容保留 `queries_seed_26.jsonl`）。
当前默认分布：`20 RAG（仅 Milvus 可答） + 5 NL2SQL + 5 Neo4j`。

常用命令：

```bash
python -m agent.evaluate.pipelines.generate_queries --count 30 --out agent/evaluate/data/queries.jsonl
python -m agent.evaluate.pipelines.fill_answers --in agent/evaluate/data/queries.jsonl --out agent/evaluate/data/answers.jsonl
python -m agent.evaluate.pipelines.build_graders --out agent/evaluate/data/rubrics.json
python -m agent.evaluate.pipelines.score_pipeline --in agent/evaluate/data/answers.jsonl --rubrics agent/evaluate/data/rubrics.json --out agent/evaluate/data/scored.jsonl --summary-out agent/evaluate/data/score_summary.json --manual-review-out agent/evaluate/data/manual_review.csv --push-langsmith
python -m agent.evaluate.pipelines.convert_gold_readable --readable agent/evaluate/data/gold.readable.yaml --out agent/evaluate/data/gold.jsonl --base-gold agent/evaluate/data/gold.jsonl --answers agent/evaluate/data/answers.jsonl
python -m agent.evaluate.pipelines.build_graders --out agent/evaluate/data/rubrics.json --rubric-labeled-data agent/evaluate/data/gold.jsonl
```

一键串行：

```bash
python -m agent.evaluate.pipelines.run_pipeline --count 30 --workdir agent/evaluate/data --push-langsmith
# 若需要在一键流程末尾自动生成 gold.jsonl，可追加：
# --gold-readable agent/evaluate/data/gold.readable.yaml --gold-out agent/evaluate/data/gold.jsonl --gold-base agent/evaluate/data/gold.jsonl
```

## 详细文档

- 项目目标与数据结构：`summary.md`
- 部署与导入：`docs/部署.md`
- 系统技术文档：`docs/互联网号码资源问答系统技术文档.md`
- LangSmith 监控指南：`docs/LangSmith监控指南.md`
- Agent 目录说明：`agent/README.md`
- OpenJudge 评测说明：`agent/evaluate/README.md`
- 面试深潜文档：`agent/docs/system_architecture_deep_dive/README.md`
