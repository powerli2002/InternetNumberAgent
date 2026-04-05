# 互联网号码资源问答系统（fusionprocessing）

本仓库是“互联网号码资源问答系统”的融合处理与智能体实现，负责把 RIR/WHOIS/RDAP、BGP、DNS/网站等多源数据清洗为结构化事实，并通过 `FusionAgent` 提供带证据的问答能力。

当前实现以 **PostgreSQL 16 张核心表** 为事实源，配套 **Milvus 文档向量索引** 与 **Neo4j 图谱/关系查询**。在线链路采用 **LangGraph + FastMCP**，不再使用历史 A2A/子代理方案。

## 快速入口
- 文档总入口：`docs/README.md`
- 系统功能总览：`docs/01-overview/system-overview.md`
- 当前架构：`docs/02-architecture/overall-architecture.md`
- 数据模型：`docs/03-data/core-schema.md`
- 部署与运行：`docs/04-operations/deployment.md`
- 配置说明：`docs/04-operations/configuration.md`
- 评测流水线：`docs/04-operations/evaluation.md`
- AI 协作规则：`docs/05-ai/repo-guide.md`

## 目录
- `fusiondata/`：离线融合处理流水线。
- `agent/runtime/`：FusionAgent、LangGraph 编排、上下文构建。
- `agent/services/http/`：HTTP API。
- `agent/services/mcp/`：FastMCP 服务与客户端。
- `agent/tools/`：NL2SQL、RAG、Neo4j、Note、Todo 等工具。
- `agent/scripts/`：导入、建索引、评测与排障脚本。
- `conf/`：配置与 `.env`。
- `docs/`：当前权威文档与历史归档。

## 常用命令

### 数据与服务

```bash
# 导入 16 张核心表
python -m agent.scripts.load_all_csv --config conf/config.docker.yaml --root . --ensure-core

# 启动 MCP
uvicorn agent.services.mcp.server:app --host 0.0.0.0 --port 2032

# 启动 API
uvicorn agent.services.http.server:app --host 0.0.0.0 --port 2025

# 构建文档向量索引
python agent/knowledge_ingest.py --root . --path agent/knowledge --reset

# 构建 Neo4j 图谱
python -m agent.scripts.neo4j_graph_loader --batch-size 1000
```

### 本地调试

```bash
# 启动 CLI
python agent/cli/main.py

# 启动 LangGraph 本地调试入口
.venv/bin/python -m agent.scripts.langgraph_dev --config langgraph.json --port 8123 --no-reload

# 启动前端
cd agent-chat-ui && pnpm exec next dev -H 0.0.0.0 -p 2225
```

### 本地 LLM

```bash
# 清理旧的 vLLM 进程
kill $(lsof -ti tcp:2222)
pkill -f "VLLM::EngineCore"

# 启动本地 vLLM
python agent/model/start_vllm.py
```

### 评测

```bash
# 评测入口会自动读取 conf/.env；若未激活虚拟环境，直接使用 .venv/bin/python

# 一键运行评测并写回 LangSmith
.venv/bin/python -m agent.evaluate.pipelines.run_pipeline --count 30 --workdir agent/evaluate/data --push-langsmith --langsmith-mode writeback

# 分步生成题目
.venv/bin/python -m agent.evaluate.pipelines.generate_queries --count 30 --out agent/evaluate/data/queries.jsonl

# 构建评分 rubric
.venv/bin/python -m agent.evaluate.pipelines.build_graders --out agent/evaluate/data/rubrics.json

# 生成 answers
.venv/bin/python -m agent.evaluate.pipelines.fill_answers --in agent/evaluate/data/queries.jsonl --out agent/evaluate/data/answers.jsonl

# 执行评分
.venv/bin/python -m agent.evaluate.pipelines.score_pipeline --in agent/evaluate/data/answers.jsonl --rubrics agent/evaluate/data/rubrics.json --out agent/evaluate/data/scored.jsonl --summary-out agent/evaluate/data/score_summary.json --manual-review-out agent/evaluate/data/manual_review.csv --push-langsmith --langsmith-mode writeback
```

## 核心原则
- PostgreSQL 是事实源，Milvus 与 Neo4j 可从结构化数据重建。
- 默认只维护 16 张核心实体表，不引入额外审计表或原始镜像表。
- 回答要带证据，优先给出 SQL 结果、文档片段或图谱关系。
- 文档保持单一权威入口，历史文档统一放到 `docs/90-archive/`。

## 兼容入口
- `AGENTS.md`：AI/Harness 入口规范。
- `summary.md`：兼容性入口，当前数据模型以 `docs/03-data/core-schema.md` 为准。
