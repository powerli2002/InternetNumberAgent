# 互联网号码资源问答系统（fusionprocessing）

本仓库是“互联网号码资源问答系统”MVP 的融合处理与智能体实现，负责多源数据清洗、实体化落库、向量索引与图谱构建，并通过 FusionAgent 提供可解释问答能力。当前架构已升级为：**工具层 FastMCP（HTTP） + 代理协同 A2A（HTTP+SSE） + 全链路 LangSmith 追踪**。主代理仍使用 Function Calling 做工具路由，但工具执行与子代理执行已全部协议化。

## 稳定性修复（2026-02-08）

本次针对多代理与记忆链路完成了以下修复：

1. 修复 A2A supervisor 路由提示模板格式化异常，恢复 `supervisor -> 子代理` 主链路。
2. 修复语义记忆写入 Neo4j 的类型错误（map 属性），改为 `metadata_json + 结构化字段` 存储并支持反序列化检索。
3. 增强 Todo 解析，兼容 `subtasks/items/todos/plan` 输出结构，避免退化为单任务。
4. 增强图谱子代理 Cypher 后验校验，关系类型越界时自动走兜底查询模板。
5. 增强 NL2SQL 超时退化：列检索超时时自动降级为表级检索重试。

## 启动与部署（简版）

### 方式一：Docker Compose（推荐）

1. 启动基础服务（PostgreSQL / Milvus / Neo4j 等）  
   ```bash
   docker compose -f docker/docker-compose.yml up -d postgres etcd minio milvus neo4j
   ```

2. 导入 CSV（仅 16 张核心表）
   ```bash
   docker compose -f docker/docker-compose.yml build loader
   docker compose -f docker/docker-compose.yml run --rm loader
   ```
   - 导入流程会自动应用统一 DDL：`database/core_schema.sql`
   - 如需单独执行：`python scripts/ensure_core_schema.py --config conf/config.docker.yaml --root .`

3. （可选）预构建 NL2SQL 索引
   ```bash
   python scripts/build_nl2sql_indexes.py
   ```

4. 启动智能体三层服务（MCP / A2A / API）
   ```bash
   docker compose -f docker/docker-compose.yml up -d agent-mcp agent-a2a agent-api
   ```

> API 默认端口：`2025`（访问 `http://localhost:2025/info` 验证）

### 方式二：本地运行（开发）

1. 安装依赖并启动三层服务
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   # 可选：预构建 NL2SQL 索引
   python scripts/build_nl2sql_indexes.py
   uvicorn agent.interfaces.mcp.server:app --host 0.0.0.0 --port 2032
   uvicorn agent.interfaces.a2a.server:app --host 0.0.0.0 --port 2031
   uvicorn agent.interfaces.http.server:app --host 0.0.0.0 --port 2025
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
- A2A Worker：`2031`
- MCP Tool Server：`2032`
- PostgreSQL：`5432`
- Neo4j：`7474/7687`
- Milvus：`19530/9091`
- Agent Chat UI：`3012`

关键环境变量：
- `MCP_SERVER_URL`（默认 `http://127.0.0.1:2032/mcp`）
- `A2A_SERVER_URL`（默认 `http://127.0.0.1:2031/a2a`）
- `REQUEST_TIMEOUT_SECONDS` / `AGENT_REQUEST_TIMEOUT_SECONDS`（统一默认超时，默认 `180` 秒）
- `CLI_TIMEOUT_SECONDS`（CLI 外层超时，默认继承 `REQUEST_TIMEOUT_SECONDS`）
- `MCP_TIMEOUT_SECONDS`（MCP 客户端超时，默认继承 `REQUEST_TIMEOUT_SECONDS`）
- `A2A_TIMEOUT_SECONDS`（A2A 客户端超时，默认继承 `REQUEST_TIMEOUT_SECONDS`）
- `A2A_EVENT_POLL_TIMEOUT_SECONDS`（A2A Worker SSE 轮询超时/心跳间隔，默认 `15` 秒）

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

按 `metadata.trace_id` 拼接 LangSmith 跨服务链路（推荐用于排查 `tool_router plan`、MCP/A2A 断点）：

```bash
python scripts/trace_by_metadata_id.py \
  --project "${LANGSMITH_PROJECT}" \
  --trace-id "<metadata.trace_id>" \
  --since-hours 24 \
  --show-io
```

## Agent 目录分层（2026-02-06）

为降低耦合并便于扩展，`agent/` 已按分层重构：

- `agent/core/`：配置、模型、提示词、LLM、追踪、Schema
- `agent/runtime/`：FusionAgent 运行时编排、主路由协议
- `agent/interfaces/http/`：FastAPI 接口与线程消息存储
- `agent/interfaces/mcp/`：MCP 服务入口
- `agent/interfaces/a2a/`：A2A 服务入口
- `agent/mcp/`：FastMCP 工具服务与客户端
- `agent/protocols/a2a/`：A2A 协议模型与客户端
- `agent/workers/`：A2A Worker 执行器与服务
- `agent/cli/`：命令行入口
- `agent/context/`、`agent/memory/`、`agent/tools/`、`agent/subagents/`：上下文、记忆、工具、子代理

注意：旧入口文件已移除，需统一使用新分层路径。

## 详细文档

- 项目目标与数据结构：`summary.md`
- 部署与导入：`docs/部署.md`
- 系统技术文档：`docs/互联网号码资源问答系统技术文档.md`
- 子代理方案：`docs/子代理构建.md`
- Agent 目录说明：`agent/README.md`
- 面试深潜文档：`agent/docs/system_architecture_deep_dive/README.md`
