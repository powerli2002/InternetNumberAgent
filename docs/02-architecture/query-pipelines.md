# 查询链路

## 查询模式分工

当前系统把问答证据分为三类：
- PostgreSQL：精确过滤、聚合统计、明细查询。
- Neo4j：实体关系、多跳路径、拓扑关联。
- Milvus：文档语义检索、概念解释、操作知识。

选择原则很简单：
- 问“有多少、有哪些、按什么过滤”时，优先 NL2SQL。
- 问“谁与谁相关、上游/下游/归属链路”时，优先 Neo4j。
- 问“某个概念、流程、规范怎么解释”时，优先 RAG。

## 在线执行流程

1. `FusionAgent` 接收用户问题。
2. LangGraph 主图生成计划并判断需要的工具。
3. 通过 MCP 调用 `nl2sql_query`、`rag_search`、`neo4j_llamaindex_query` 或辅助工具。
4. `ContextBuilder` 汇总结构化结果、文档证据和图关系。
5. 回答节点生成最终答复，并输出证据来源。

## NL2SQL 链路
- 入口：`agent/tools/nl2sql_tool.py`
- 作用：面向 16 张核心表生成只读 SQL，并执行受控查询。
- 适合：计数、分组、排序、前 N 样本、字段过滤。
- 约束：只读、白名单、强制 LIMIT、超时控制。

## RAG 链路
- 入口：`agent/tools/rag_tool.py`
- 入库：`agent/knowledge_ingest.py`、`agent/tools/rag_ingest_pipeline.py`
- 作用：从项目文档、知识库、笔记中召回相关片段。
- 适合：概念说明、流程解释、运维知识、非结构化背景资料。

## Neo4j 链路
- 入口：`agent/tools/neo4j_llamaindex_tool.py`
- 导入：`agent/scripts/neo4j_graph_loader.py`
- 作用：基于图谱关系查询 Prefix、AS、Org、Country 等实体之间的关联。
- 适合：上下游、Peer、组织到前缀、国家到 AS 等关系问题。

## 证据组织规则
- PostgreSQL 结果是事实优先证据。
- 文档片段用于补充解释、术语说明和操作背景。
- 图谱结果用于补充关系链路，不替代结构化事实。
- 最终回答必须明确来源，不允许只给模型推断结论。

## 常见误区
- 不要用 RAG 替代结构化统计问题。
- 不要把 Neo4j 当作唯一事实源。
- 不要把历史 A2A/子代理文档当成当前实现。
- 不要在没有必要时同时调用三种检索，避免上下文噪声。

## 继续阅读
- `text2sql.md`
- `../03-data/core-schema.md`
- `../04-operations/observability.md`
