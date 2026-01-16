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

3. 启动 API（FusionAgent）
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

## 详细文档

- 项目目标与数据结构：`summary.md`
- 部署与导入：`docs/部署.md`
- 系统技术文档：`docs/互联网号码资源问答系统技术文档.md`
