# Text2SQL

## 定位

Text2SQL 只面向 PostgreSQL 的 16 张核心实体表，职责是把自然语言问题转换为只读 SQL，并在安全边界内执行查询。当前实现位于 `services/agent/tools/nl2sql_tool.py`。

## 核心约束
- 只允许查询 16 张核心表。
- 只允许只读 SQL，不允许写操作、DDL、多语句。
- 强制 LIMIT 和超时，避免大结果集或慢查询。
- 结果用于证据生成，不作为模型自由推断的替代品。

## 查询流程
1. 加载 SQLDatabase 与允许访问的表。
2. 基于表/列索引筛选相关 Schema。
3. 生成 SQL 草案。
4. 通过 `SQLGuard` 做安全校验与 LIMIT 收敛。
5. 执行 SQL，返回结构化结果。

## 相关代码
- `services/agent/tools/nl2sql_tool.py`：NL2SQL 主实现。
- `services/agent/core/schema.py`：表结构与字段上下文提示。
- `services/agent/core/prompts.py`：Text2SQL 提示词。
- `services/agent/scripts/build_nl2sql_indexes.py`：预构建表/列索引。

## 关键配置
- `ALLOWED_TABLES`：NL2SQL 白名单。
- `NL2SQL_MAX_ROWS`：查询结果行数上限。
- `NL2SQL_STATEMENT_TIMEOUT_MS`：SQL 超时。
- `NL2SQL_MAX_SQL_LENGTH`：SQL 长度上限。
- `NL2SQL_EMBEDDING_*`：索引向量化配置。

## 使用建议
- 数量统计、聚合分析、字段过滤优先走 NL2SQL。
- 问题中若同时包含“总数 + 示例”，应拆为两个查询步骤。
- 对数组列应使用 PostgreSQL 合法数组谓词，不能把数组当标量比较。
- 当字段名包含特殊字符或大小写差异时，必须尊重真实 Schema。

## 与文档和图谱的边界
- Text2SQL 负责结构化事实，不负责解释 RFC、术语和手册。
- 关系链路可以通过 Neo4j 辅助，但最终注册/统计事实仍以 PostgreSQL 为准。

## 继续阅读
- `query-pipelines.md`
- `../03-data/core-schema.md`
- `../04-operations/troubleshooting.md`
