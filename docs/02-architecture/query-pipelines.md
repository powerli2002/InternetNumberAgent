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
4. 若进入 Python 沙箱，Agent 会先做意图判断：只有在绘图、文件导出或确需 Python 处理时，才整理依赖结果给沙箱。
5. 进入 Python 沙箱时，依赖步骤结果会拆成两层：
   - 轻量元数据写入 `/workspace/input/input.json`
   - 真实表格数据按 CSV 文件写入 `/workspace/input/datasets/*.csv`
   这样既避免把大表塞进回答上下文，也避免让 Python 代码从自然语言描述里反向猜数据。
6. `ContextBuilder` 汇总结构化结果、文档证据和图关系；对大表默认只保留摘要和少量预览行，降低回答阶段的上下文体积。
7. 回答节点生成最终答复，并输出证据来源。
8. 若本轮存在图片 artifact，回答阶段会把图片以 `![标题](artifact://artifact_id)` 的 Markdown 引用附加到最终消息中；前端负责把该引用解析成当前线程中的真实产物预览。

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

## Python 沙箱链路
- 入口：`agent/tools/python_sandbox_tool.py`
- 执行：`backend/main.py`、`backend/sandbox/opensandbox_provider.py`
- 作用：基于上游工具的结构化结果做绘图、表格整理、文件生成。
- 数据传递：
  - Agent 会把依赖步骤结果整理成轻量 `input_data` 元数据。
  - 对表格型结果，Agent 会额外序列化为 CSV，通过沙箱文件系统 API 写入 `/workspace/input/datasets/*.csv`。
  - `/workspace/input/input.json` 中只保留任务说明、依赖摘要、数据集清单、列信息、行数与少量预览，不再内嵌整表数据。
- 产物约束：所有图片和文件必须写入 `/workspace/artifacts`，由产品后端落盘并挂载到线程 artifact 列表。
- 回答挂图：Python 步骤返回的图片 artifact 会保留 `id/title/mime_type`，回答阶段只暴露 `artifact://...` 引用，不暴露内部路径。
- 详细原理、数据契约与命名规则见 `python-sandbox.md`。

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
- `python-sandbox.md`
- `text2sql.md`
- `../03-data/core-schema.md`
- `../04-operations/observability.md`
