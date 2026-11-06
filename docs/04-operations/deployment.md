# 部署与运行

## 依赖服务
- PostgreSQL：结构化事实源。
- Milvus：文档向量索引。
- Neo4j：关系图谱。
- Agent HTTP API：`2025`（仅调试/兼容入口）。
- MCP Tool Server：`2032`。
- Product Backend：`2026`。
- OpenSandbox Server：按 `OPENSANDBOX_DOMAIN` 配置。

## 启动前置条件

- 仓库根目录已创建并安装 `.venv/`；`deploy/` 下的 Python 脚本默认直接调用 `.venv/bin/python`。
- 如需启动 `services/webapp/`，宿主机需已安装 `pnpm`。

迁移后若缺少环境或前端依赖，在仓库根目录重建：

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
pnpm --dir services/webapp install --frozen-lockfile
```

清理前的实际 Python 包版本记录在 `python_environments_20261106.json`。前端的 `.next/` 和 `tsconfig.tsbuildinfo` 是构建缓存，不随 Git 保存；生产部署时重新运行 `pnpm --dir services/webapp build`。

## deploy 启动链路

- `./deploy/start_dev_chain.sh`：启动开发链路（MCP + LangGraph 调试）。
- `./deploy/start_ui_chain.sh`：启动用户界面链路（MCP + Backend + Agent API + WebApp）。
- `./deploy/start_evaluation.sh`：执行默认评测流水线。

## 推荐启动顺序

### 1. 启动基础服务

```bash
docker compose -f docker/docker-compose.yml up -d postgres etcd minio milvus neo4j
```

### 2. 安装并启动 OpenSandbox

按 OpenSandbox 官方 Docker 示例，当前仓库统一使用 `docker/docker-compose.yml` 管理 OpenSandbox：

```bash
services/backend/scripts/pull_opensandbox_images.sh
docker compose -f docker/docker-compose.yml up -d opensandbox
```

首次启动后，可用最小联调脚本验证：

```bash
.venv/bin/python services/backend/scripts/opensandbox_smoke_test.py
```

默认配置说明：
- OpenSandbox Server 由 `docker/docker-compose.yml` 管理
- OpenSandbox 容器镜像由根目录 `Dockerfile.opensandbox` 构建
- OpenSandbox Server 配置文件位于 `conf/opensandbox.toml`
- 默认地址是 `127.0.0.1:8080`
- 默认模板镜像是 `sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.2`
- `services/backend/scripts/start_opensandbox.sh` 是对 `docker compose -f docker/docker-compose.yml up -d opensandbox` 的封装

### 3. 导入 16 张核心表

```bash
PYTHONPATH=services .venv/bin/python -m agent.scripts.load_all_csv --config conf/config.docker.yaml --root . --date 2024-08-12 --ensure-core
```

本机保留的最新完整实体快照为 `2024-08-12`。如需导入旧日期，先从 `DATA_CATALOG.md` 登记的归档恢复对应文件，再显式指定日期：

```bash
python -m agent.scripts.load_all_csv --config conf/config.docker.yaml --root . --date 2024-08-12 --ensure-core
```

### 4. 可选：预构建 NL2SQL 索引

```bash
python -m agent.scripts.build_nl2sql_indexes
```

### 5. 启动用户界面链路

```bash
./deploy/start_ui_chain.sh
```

如需启动开发链路：

```bash
./deploy/start_dev_chain.sh
```

如需执行默认评测流水线：

```bash
./deploy/start_evaluation.sh
```

## 常用任务

### 构建文档向量索引

```bash
python services/agent/knowledge_ingest.py --root . --path services/agent/knowledge --reset
```

### 构建 Neo4j 图谱

```bash
python -m agent.scripts.neo4j_graph_loader --batch-size 1000
```

### 启动脚本目录

- `deploy/start_dev_chain.sh`：启动 MCP 与 LangGraph 调试。
- `deploy/start_ui_chain.sh`：启动 MCP、产品后端、兼容 Agent API 与正式前端。
- `deploy/start_evaluation.sh`：执行默认评测流水线，参数会透传给 `run_pipeline`。

### AS 疆域分析

```bash
python services/agent/tools/as_territory_tools.py --config conf/config.docker.yaml --root .
```

## 关键端口
- Agent HTTP API：`2025`
- MCP：`2032`
- Backend：`2026`
- PostgreSQL：`5432`
- Neo4j：`7474/7687`
- Milvus：`19530/9091`
- OpenSandbox：`8080`

## 配置原则
- 优先修改 `conf/.env`。
- PostgreSQL 数据卷挂载路径必须保持 `../mount/...`。
- 不要在默认链路中引入 `_audit` 或 `csv__*` 原始表。

## 推荐排查入口
- 运行链路看 `observability.md`
- 环境或数据卷问题看 `troubleshooting.md`
- UI 接入看 `agent-chat-ui.md`
