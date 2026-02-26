# 互联网号码资源问答系统（fusionprocessing）

本仓库是“互联网号码资源问答系统”MVP 的融合处理与智能体实现，负责多源数据清洗、实体化落库、向量索引与图谱构建，并通过 FusionAgent 提供可解释问答能力。当前架构已升级为：**LangGraph 主编排 + FastMCP 工具层（HTTP） + 全链路 LangSmith 追踪**。复杂任务通过 LangGraph 子图执行，不再依赖 A2A/子代理服务。

## 图查询链路升级（2026-02-25）

1. 新增 MCP 工具 `neo4j_llamaindex_query`：由工具内部通过 LlamaIndex 读取 Neo4j 当前 schema，生成 Cypher 并执行返回结果。
2. LangGraph `graph` 步骤不再在主流程预生成 Cypher，而是直接把自然语言问题交给 `neo4j_llamaindex_query`。
3. 保留 `neo4j_query` 作为显式 Cypher 只读执行工具，便于测试与运维排障。

## 稳定性修复（2026-02-08）

本次针对编排与记忆链路完成了以下修复：

1. 修复语义记忆写入 Neo4j 的类型错误（map 属性），改为 `metadata_json + 结构化字段` 存储并支持反序列化检索。
2. 增强 Todo 解析，兼容 `subtasks/items/todos/plan` 输出结构，避免退化为单任务。
3. 增强图谱查询 Cypher 后验校验，关系类型越界时自动走兜底查询模板。
4. 增强 NL2SQL 超时退化：列检索超时时自动降级为表级检索重试。
5. RAG 索引写入支持增量去重：按 `source + text` 哈希过滤批内与存量重复切片，避免重复入库。
6. 补齐 `agent/knowledge/bgp/hijack_detection.md` 示例文件，chapter_5 路径可直接复现。

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

2. 导入 CSV（仅 16 张核心表，手动触发）
   ```bash
   # 本机执行
   python -m agent.scripts.load_all_csv --config conf/config.docker.yaml --root . --date 2024-08-12 --ensure-core

   # 或在现有 agent 镜像中执行（无需本机安装 Python 依赖）
   docker compose -f docker/docker-compose.yml run --rm agent-mcp \
     python -m agent.scripts.load_all_csv --config conf/config.docker.yaml --root /work --date 2024-08-12 --ensure-core
   ```
   - 导入流程会自动应用统一 DDL：`database/core_schema.sql`
   - `python -m agent.scripts.load_all_csv` 默认启用 `--single-transaction`，16 张核心表导入失败或核心 CSV 缺失会整批回滚
   - 如需单独执行：`python -m agent.scripts.ensure_core_schema --config conf/config.docker.yaml --root .`

3. （可选）一体化顺序导入 PostgreSQL + Neo4j
   ```bash
   python -m agent.scripts.load_network_data_atomic --root . --config conf/config.docker.yaml --ensure-core
   ```
   - 执行顺序：先 PostgreSQL（单事务）→ 后 Neo4j
   - PostgreSQL 失败时不会触发 Neo4j 导入
   - Neo4j 可通过 `--neo4j-single-transaction` 控制是否整批事务写入

4. （可选）预构建 NL2SQL 索引
   ```bash
   python -m agent.scripts.build_nl2sql_indexes
   ```
   - NL2SQL 表/列索引将写入 Milvus（单 collection + 分区），本地仅保留轻量 manifest

5. 启动智能体服务（MCP / API）
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

2. 启动前端（Agent Chat UI）
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
- `CLI_TIMEOUT_SECONDS`（CLI 外层超时，默认继承 `REQUEST_TIMEOUT_SECONDS`）
- `MCP_TIMEOUT_SECONDS`（MCP 客户端超时，默认继承 `REQUEST_TIMEOUT_SECONDS`）
- `RAG_EMBEDDING_BACKEND`（默认 `local_bge`）
- `RAG_EMBEDDING_MODEL`（默认 `BAAI/bge-m3`，也可填本地模型目录）
- `RAG_EMBEDDING_DEVICE`（默认 `cpu`）
- `NL2SQL_EMBEDDING_BACKEND`（默认 `local_bge`）
- `NL2SQL_EMBEDDING_MODEL`（默认 `BAAI/bge-m3`，也可填本地模型目录）
- `NL2SQL_EMBEDDING_DEVICE`（默认 `cpu`）
- `NL2SQL_EMBEDDING_BATCH_SIZE`（默认 `16`）
- `NL2SQL_EMBEDDING_NORMALIZE`（默认 `true`）
- `RAG_ENABLE_MQE`（默认 `true`）
- `NEO4J_DATABASE`（默认 `neo4j`）
- `GRAPH_REFRESH_SCHEMA_EACH_QUERY`（默认 `true`，图查询前刷新 schema）

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

按 `metadata.trace_id` 拼接 LangSmith 跨服务链路（推荐用于排查 `graph_node:plan` 与 MCP 断点）：

```bash
python -m agent.scripts.trace_by_metadata_id \
  --project "${LANGSMITH_PROJECT}" \
  --trace-id "<metadata.trace_id>" \
  --since-hours 24 \
  --show-io
```

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

## 详细文档

- 项目目标与数据结构：`summary.md`
- 部署与导入：`docs/部署.md`
- 系统技术文档：`docs/互联网号码资源问答系统技术文档.md`
- Agent 目录说明：`agent/README.md`
- 面试深潜文档：`agent/docs/system_architecture_deep_dive/README.md`
