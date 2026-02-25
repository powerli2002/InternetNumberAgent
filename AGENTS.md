# fusionprocessing - Codex 编程指导

## 项目目标（当前）
- 构建“互联网号码资源问答系统”MVP：以 fusionprocessing 数据融合层为基础，将 RIR/WHOIS/RDAP、BGP、DNS/网站等多源数据清洗对齐，形成 16 张核心表写入 PostgreSQL；同时提供 Milvus 向量索引与 Neo4j 语义图谱；在智能体层（FusionAgent）统一调度 NL2SQL/RAG/记忆，实现可解释问答与可观测链路。
- 结构化数据为事实源（PostgreSQL），向量/图谱可从结构化表重建；答复要有证据（SQL 结果/文档片段）。

## 系统结构与关键目录
- `src/`：数据处理流水线（解析/清洗/实体化/格式化器）。
- `agent/scripts/`：CSV 导入与辅助脚本（如 `python -m agent.scripts.load_all_csv`）。
- `agent/`：FusionAgent、上下文工程、记忆、工具、追踪；API 在 `agent/interfaces/http/server.py`。
- `agent/mcp/`：FastMCP 工具服务与客户端（NL2SQL/RAG/Neo4j/Note/Todo）。
- `agent/protocols/a2a/`：A2A 协议模型与客户端（HTTP+SSE）。
- `agent/workers/`：A2A Worker 服务与子代理执行器。
- `agent/tools/`：底层工具实现（由 MCP Server 封装暴露）。
- `conf/`：配置与 `.env`；`config.yaml`（本机）/`config.docker.yaml`（容器）。
- `data/format/`：实体 CSV 输出；多为日期快照。
- `docs/`：项目与部署文档；`summary.md` 为 16 表与关系的权威摘要。
- `agent-chat-ui/`：可选前端，使用 LangGraph 风格 API 访问 `agent/interfaces/http/server.py`。

## 数据与模型约束（必须遵守）
- **仅 16 张核心实体表**为默认落库目标；避免生成 `*_audit` 或原始表，除非明确要求。
- CSV 多为日期快照，**表名不带日期**；导入时选择最新或指定日期（`current_date`/`--date`）。
- 多值字段以 **Python 列表字符串**存储，导入时解析为数组类型（`text[]`/`bigint[]`）。
- `admin_info/tech_info/abuse_info` 为 **JSON 字符串**，落库为 `json/jsonb`。
- IP 单点不作为图谱节点，**以 Prefix 为核心实体**；Registry（inetnum/rdap/route）作为 Prefix 属性。
- `website_entity_base.csv` 使用 **`;` 分隔**且首列可能为空；与 `domain_cn.csv` 合并时注意。
- RIR 注册归属与 BGP 观测归属并行保留：`ip_bgp_entity.route` vs `ip_bgp_entity.bgp`。

## 运行与验证（常用）
- 导入 16 表：`python -m agent.scripts.load_all_csv --config conf/config.docker.yaml --root . --ensure-core`
- MCP 工具服务：`uvicorn agent.interfaces.mcp.server:app --host 0.0.0.0 --port 2032`
- A2A Worker 服务：`uvicorn agent.interfaces.a2a.server:app --host 0.0.0.0 --port 2031`
- API：`uvicorn agent.interfaces.http.server:app --host 0.0.0.0 --port 2025`
- 向量索引：`python agent/knowledge_ingest.py --root . --path agent/knowledge --reset`
- Neo4j 图谱：`python -m agent.tools.neo4j_graph_loader --batch-size 1000`
- AS 疆域分析：`python agent/tools/as_territory_tools.py --config conf/config.docker.yaml --root . [--load-neo4j]`

## 开发规范
- 严禁使用 回退策略，如果不可行，则报告并询问需要的决策。
- 代码优先放在：**智能体链路→`agent/`**；**工具/脚本→`agent/tools/`、`agent/scripts/`**。
- 保持脚本 **幂等**（可重复执行不重复写入）。
- 修改配置时优先更新 `conf/.env`，不要提交密钥。
- PostgreSQL 数据卷挂载路径需保持 `../mount/...`，避免数据损坏。
- 代码注释必须为简体中文，复杂逻辑先写思路再实现。
- 需求不清晰时先提问或给出可执行的具体方案。


## 重大修改必须同步文档（强制）
凡涉及以下任一项的“重大修改”，**必须回写文档**：
- 数据模型/表结构、字段语义、导入逻辑、核心关联关系。
- 关键链路（FusionAgent 路由、NL2SQL/RAG/记忆、上下文模板）。
- 部署方式、配置项、端口、数据卷、依赖服务。
- 重要脚本入口或运行流程。

至少更新以下文件中与变更相关的部分：
- `summary.md`（16 表与关系变更）
- `docs/互联网号码资源问答系统技术文档.md`（架构/工具/流程）
- `README.md` (部署/流程/架构)
必要时同步 `docs/` 其他说明文件。
