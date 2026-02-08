# Text2SQL 说明（fusionprocessing）

本文档介绍当前项目 Text2SQL（NL2SQL）实现与使用方式，重点说明：
- 结构化数据的来源与表范围
- LlamaIndex 驱动的检索增强流程
- 预构建索引与缓存机制
- 安全与可控执行策略
- 与 FusionAgent 的集成方式

文档内容紧贴代码实现，主要参考：
- `agent/tools/nl2sql_tool.py`
- `agent/core/schema.py`
- `agent/runtime/fusion_agent.py`
- `agent/core/config.py`
- `scripts/build_nl2sql_indexes.py`

---

## 1. 定位与范围

当前 Text2SQL 仅面向 **16 张核心实体表**，事实源为 PostgreSQL。NL2SQL 只生成并执行 **只读 SQL**，并通过安全守卫强制限制查询范围与结果规模。

**默认可用表**由 `AgentConfig.allowed_tables` 指定：
`as_entity / asn_entity / country_entity / industry_entity / ip_bgp_entity / ip_inetnum_entity / ip_rdap_entity / ip_route_entity / ipv4_entity / ipv6_bgp_entity / ipv6_entity / ipv6_inetnum_entity / ipv6_rdap_entity / ipv6_route_entity / org_entity / website_entity`

**结构化表的统一 DDL**位于 `database/core_schema.sql`，导入时由 `scripts/load_all_csv.py` 自动应用，确保 NL2SQL 与数据一致。

---

## 2. 前置条件与连接配置

### 2.1 数据库结构一致性

建议先执行统一 DDL，再导入 CSV：

```bash
python scripts/ensure_core_schema.py --config conf/config.docker.yaml --root .
python scripts/load_all_csv.py --config conf/config.docker.yaml --root . --ensure-core
```

### 2.2 环境变量（conf/.env）

```dotenv
POSTGRES_URL=postgresql+psycopg2://user:pwd@host:5432/fusionprocessing
DASHSCOPE_API_KEY=sk-xxxx
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3-max-preview
DASHSCOPE_EMBEDDING_MODEL=text-embedding-v3

# NL2SQL 安全控制
NL2SQL_MAX_ROWS=200
NL2SQL_STATEMENT_TIMEOUT_MS=15000
NL2SQL_MAX_SQL_LENGTH=4000
NL2SQL_ALLOW_SUBQUERY=false
```

---

## 3. Schema 与上下文注入

`agent/core/schema.py` 中维护了两类关键结构：

1) `TABLE_SCHEMA`：每张表字段列表，用于构建 LlamaIndex 的表结构上下文。
2) `TABLE_CONTEXT_HINTS`：字段语义补充，避免国家字段误用（如 `country` vs `country_cn`）。

在 NL2SQL 生成阶段，会把 “字段列表 + 语义提示” 写入上下文，提升 SQL 生成准确率。

代码入口：`NL2SQLTool._build_table_context()`

---

## 4. NL2SQL 查询流程（核心逻辑）

NL2SQL 实现位于 `agent/tools/nl2sql_tool.py`，核心流程如下：

1) **加载 SQLDatabase**（限定可用表）
2) **构建表检索器**（Table Retriever）
3) **可选构建列检索器**（Column Retriever）
4) **使用 NLSQLRetriever 生成 SQL**（仅生成，不执行）
5) **SQL 安全守卫校验并强制 LIMIT**
6) **执行 SQL（带超时与结果截断）**
7) **返回结构化结果**

关键入口：`NL2SQLTool.query()`

---

## 5. 表检索（Query-Time Table Retrieval）

为了避免将全部表结构塞入 Prompt，系统使用向量检索筛选相关表：

- `SQLTableNodeMapping` 将 SQL 表结构映射为节点
- `ObjectIndex + VectorStoreIndex` 构建表结构向量索引
- 查询时根据问题只取 Top-K 表

对应代码：`NL2SQLTool._get_or_build_retrievers()`

示意（简化）：

```python
# 核心流程（示意）
table_node_mapping = SQLTableNodeMapping(db)
obj_index = ObjectIndex.from_objects(
    table_schema_objs,
    table_node_mapping,
    VectorStoreIndex,
    embed_model=embed_model,
)
retriever = obj_index.as_retriever(similarity_top_k=table_top_k)
```

---

## 6. 列检索（Query-Time Column Retrieval）

列检索用于解决枚举值/同义词带来的列值匹配问题。
项目中使用 **列级 distinct 值索引**，默认只对“类别型字段”做索引（避免成本过高）。

配置入口：
- `NL2SQLTool.COLUMN_INDEX_CONFIG`：默认列名单
- `column_index_max_values`：每列最多索引的 distinct 值数量
- `column_index_max_value_length`：单值最大长度

示意（简化）：

```python
values = select(column).distinct().limit(column_index_max_values)
# 为每个 distinct value 构建向量索引
```

是否启用列检索由主代理路由约束 `constraints.enable_column_retrieval` 决定，并通过 MCP 工具入参传递。

---

## 7. 索引缓存与预热

NL2SQL 的表/列索引会缓存到磁盘，避免每次启动重建。

配置入口：
- `AgentConfig.nl2sql_index_cache_dir`
- `NL2SQL_INDEX_CACHE_ENABLED`
- `NL2SQL_INDEX_CACHE_FORCE_REBUILD`

手动预构建：

```bash
python scripts/build_nl2sql_indexes.py
# 或仅构建表索引
python scripts/build_nl2sql_indexes.py --skip-columns
```

---

## 8. 安全与可控执行（关键改造）

为了避免 LLM 生成危险 SQL，系统新增 **SQLGuard**，并改变执行路径为“生成 SQL → 校验 → 执行”。

### 8.1 SQLGuard 规则

- 仅允许 `SELECT`/`WITH` 查询
- 禁止危险关键字：`insert/update/delete/drop/alter/...`
- 禁止危险函数：`pg_sleep/pg_terminate_backend/pg_cancel_backend`
- 仅允许 16 核心表（表白名单）
- 默认禁止子查询（`NL2SQL_ALLOW_SUBQUERY=false`）
- 强制 LIMIT（无 LIMIT 会自动追加；有 LIMIT 会被收敛）
- 超长 SQL 拒绝执行（`NL2SQL_MAX_SQL_LENGTH`）

### 8.2 执行控制

执行 SQL 时，统一执行入口 `DatabaseClient.run_sql()` 会设置：
- `statement_timeout`（默认 15000ms）
- `max_rows` 截断（默认 200 行）

返回结果结构化：

```json
{
  "columns": ["prefix", "bgp"],
  "rows": [["1.2.3.0/24", 12345]],
  "row_count": 1,
  "truncated": false,
  "limit_applied": true,
  "limit_value": 200,
  "limit_clamped": true
}
```

---

## 9. 与 FusionAgent 的集成

`FusionAgent` 在 `agent/runtime/fusion_agent.py` 中调度 NL2SQL：

- 通过 `route_tools` Function Calling 生成工具计划（`ToolRouterDecision`）
- 当计划包含 `tool=nl2sql` 时调用 `MCPToolClient.call_tool("nl2sql_query", ...)`
- MCP 服务端（`agent/mcp/server.py`）执行 `NL2SQLTool.query()`
- 执行结果回传主代理后写入 Evidence + 情景记忆

日志与追踪：
- 模块日志：`_log_module_io()`
- LangSmith：客户端 `mcp_tool:nl2sql_query` + 服务端 `mcp_server:nl2sql_query`

---

## 10. 使用示例

### 10.1 CLI 单次问答

```bash
python -m agent.cli.main --once "列出 ASN 12345 的 IPv4 前缀"
```

### 10.2 预热索引

```bash
python agent/cli/main.py --preload-index
python agent/cli/main.py --preload-index --preload-columns
```

---

## 11. 常见问题与排查

1) **提示缺少 API Key**
- 检查 `conf/.env` 是否设置 `DASHSCOPE_API_KEY`

2) **SQL 被拒绝执行**
- 检查是否触发 SQLGuard：子查询/危险关键字/非白名单表

3) **结果为空或被截断**
- 检查 `NL2SQL_MAX_ROWS` 与查询条件

4) **索引缓存无效**
- 检查 `NL2SQL_INDEX_CACHE_DIR` 是否可写

---

## 12. 设计取舍说明

- 选择“只生成 SQL + 手动执行”是为了安全与可控。
- 列检索只覆盖高价值字段，避免大表全列索引导致成本过高。
- LIMIT 强制执行，保障稳定性与响应时间。
- 默认禁止子查询，降低 SQL 解析复杂度和潜在注入风险。

如果需要更强的 SQL 解析能力（如 AST 级白名单、多表子查询），可以在 `SQLGuard` 上继续扩展。
