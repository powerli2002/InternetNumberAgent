# 互联网号码资源问答系统（fusionprocessing）

本仓库是“互联网号码资源问答系统”MVP 的融合处理与智能体实现，负责多源数据清洗、实体化落库、向量索引与图谱构建，并通过 FusionAgent 提供可解释问答能力。NL2SQL 基于 LlamaIndex 的表检索与列值索引增强生成准确率。

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

3. （可选）预构建 NL2SQL 索引
   ```bash
   python scripts/build_nl2sql_indexes.py
   ```

4. 启动 API（FusionAgent）
   ```bash
   docker compose -f docker/docker-compose.yml up -d agent-api
   ```

> API 默认端口：`2025`（访问 `http://localhost:2025/info` 验证）

### 方式二：本地运行（开发）

1. 安装依赖并启动 API
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   # 可选：预构建 NL2SQL 索引
   python scripts/build_nl2sql_indexes.py
   uvicorn agent.api_server:app --host 0.0.0.0 --port 2025
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
- PostgreSQL：`5432`
- Neo4j：`7474/7687`
- Milvus：`19530/9091`
- Agent Chat UI：`3012`

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

## 详细文档

- 项目目标与数据结构：`summary.md`
- 部署与导入：`docs/部署.md`
- 系统技术文档：`docs/互联网号码资源问答系统技术文档.md`
