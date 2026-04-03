# 部署与运行

## 依赖服务
- PostgreSQL：结构化事实源。
- Milvus：文档向量索引。
- Neo4j：关系图谱。
- Agent API：`2025`。
- MCP Tool Server：`2032`。

## 推荐启动顺序

### 1. 启动基础服务

```bash
docker compose -f docker/docker-compose.yml up -d postgres etcd minio milvus neo4j
```

### 2. 导入 16 张核心表

```bash
python -m agent.scripts.load_all_csv --config conf/config.docker.yaml --root . --ensure-core
```

如需指定日期：

```bash
python -m agent.scripts.load_all_csv --config conf/config.docker.yaml --root . --date 2024-08-12 --ensure-core
```

### 3. 可选：预构建 NL2SQL 索引

```bash
python -m agent.scripts.build_nl2sql_indexes
```

### 4. 启动 MCP 与 API

```bash
uvicorn agent.services.mcp.server:app --host 0.0.0.0 --port 2032
uvicorn agent.services.http.server:app --host 0.0.0.0 --port 2025
```

## 常用任务

### 构建文档向量索引

```bash
python agent/knowledge_ingest.py --root . --path agent/knowledge --reset
```

### 构建 Neo4j 图谱

```bash
python -m agent.scripts.neo4j_graph_loader --batch-size 1000
```

### AS 疆域分析

```bash
python agent/tools/as_territory_tools.py --config conf/config.docker.yaml --root .
```

## 关键端口
- API：`2025`
- MCP：`2032`
- PostgreSQL：`5432`
- Neo4j：`7474/7687`
- Milvus：`19530/9091`

## 配置原则
- 优先修改 `conf/.env`。
- PostgreSQL 数据卷挂载路径必须保持 `../mount/...`。
- 不要在默认链路中引入 `_audit` 或 `csv__*` 原始表。

## 推荐排查入口
- 运行链路看 `observability.md`
- 环境或数据卷问题看 `troubleshooting.md`
- UI 接入看 `agent-chat-ui.md`
