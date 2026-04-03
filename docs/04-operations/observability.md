# 观测与调试

## LangSmith 目标
- 一次提问只生成一个主 trace。
- 节点、LLM、MCP 工具调用都能在同一条链路下追踪。
- 保留输入、输出、上下文和关键状态，便于排障。

## 当前实现要点
- LangGraph 自动节点追踪保留。
- MCP 客户端透传追踪头，服务端记录工具 span。
- 根链路承载整轮问答，节点 run 承载计划、执行、上下文和回答细节。
- 并发执行步骤通过上下文复制保持 trace 连贯。

## 常用环境变量

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_WORKSPACE_ID=...
LANGSMITH_PROJECT=internet-number-qa
LANGSMITH_DEFAULT_TAGS=fusion,langgraph,mcp
```

## 查看重点
- 根 run：整轮问答是否只有一个主 trace。
- `plan`、`execute_ready`、`build_context`、`generate_answer`：主节点输入输出。
- MCP 工具 span：`nl2sql_query`、`rag_search`、`neo4j_llamaindex_query` 等调用详情。
- 最终回答：是否带有来源和证据摘要。

## 日志
- 后端日志默认写入 `logs/YYYY-MM/DD/`。
- 重点关注请求体、工具调用耗时、异常堆栈、上下文压缩前后差异。

## 常见观测问题
- 图视图看不到 MCP 工具：因为当前工具调用在 `execute_ready` 节点内部执行，不会在 LangGraph 图中单独成节点。
- trace 平铺成多个根节点：通常是父子上下文没有正确继承。
- 回答无证据：优先检查 `step_results`、`evidences` 与 `build_context` 输入是否为空。

## 调试顺序
1. 先看 API 是否收到请求并创建主 trace。
2. 再看 `plan` 是否生成有效步骤。
3. 再看 MCP 工具 span 是否成功返回。
4. 最后看 `build_context` 和 `generate_answer` 是否丢失证据。
