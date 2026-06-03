# 系统功能总览

## 系统目标

本项目构建的是“互联网号码资源问答系统”MVP，目标是把分散在 RIR/WHOIS/RDAP、BGP、DNS/网站等数据源中的互联网号码资源信息清洗对齐，形成统一事实底座，并通过智能体提供可解释问答。

系统坚持三条主线：
- 结构化事实以 PostgreSQL 16 张核心表为准。
- 向量索引和图谱都是派生索引，可从结构化数据或文档重新构建。
- 最终回答必须能给出证据，而不是只给模型结论。

## 当前能力
- 结构化事实问答：基于 NL2SQL 查询 PostgreSQL，适合统计、过滤、聚合、明细检索。
- 文档语义检索：基于 RAG 检索项目文档、知识库、笔记等非结构化资料。
- 图关系查询：基于 Neo4j 查询 AS、Prefix、Org、Country 等实体关系。
- 多源归属对齐：同时保留注册侧与 BGP 观测侧归属，支持差异分析。
- 可观测链路：通过 LangSmith、日志和节点审计追踪整个问答过程。

## 典型场景
- 查询某个 ASN、Prefix 或组织的归属与上下游关系。
- 比较注册归属和 BGP 观测归属是否一致。
- 结合文档知识解释 BGP、WHOIS、RDAP、RPKI 等概念。
- 对导入、索引构建、工具链路进行运维排障。

## 非目标与边界
- 当前系统默认不维护原始镜像表、审计表或临时分析表。
- 当前在线主链路不再使用历史 A2A/子代理服务。
- 图谱不是唯一事实源；统计和精确过滤应优先落到 PostgreSQL。
- 文档中的 `docs/90-archive/` 内容不应作为当前开发依据。

## 核心组件
- `services/fusiondata/`：多源数据融合、格式化、导出 CSV。
- `services/agent/scripts/load_all_csv.py`：把 CSV 导入 PostgreSQL，并可触发 Neo4j 导入。
- `services/agent/runtime/fusion_agent.py`：FusionAgent 入口。
- `services/agent/runtime/langgraph_orchestrator.py`：LangGraph 主编排。
- `services/agent/services/mcp/server.py`：FastMCP 服务。
- `services/agent/services/http/server.py`：HTTP API。
- `services/agent/tools/*.py`：NL2SQL、RAG、Neo4j、Note、Todo 等工具实现。

## 推荐阅读路径
1. 架构总览：`../02-architecture/overall-architecture.md`
2. 查询链路：`../02-architecture/query-pipelines.md`
3. 数据模型：`../03-data/core-schema.md`
4. 部署运行：`../04-operations/deployment.md`
5. AI 指南：`../05-ai/repo-guide.md`
