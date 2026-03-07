# LangSmith监控指南

本文档说明本项目的 LangSmith 监控设计、基本用法、常见故障原因与修复方案。

## 1. 目标

- 一次提问只生成一个 trace（One Question, One Trace）。
- trace 内允许多个 runs（LangGraph 自动节点、LLM 调用等）。
- 父子关系必须完整（`parent_run_id` 正确），避免平铺节点。
- 保留可排障信息：节点输入、输出、prompt、最终结果。

## 2. 关键概念

### 2.1 trace_id 与 parent_run_id 的区别

- `run.trace_id`：LangSmith 内部链路 ID，用于将一条链路下的所有 runs 归并。
- `parent_run_id`：父子结构字段，用于构建 waterfall 树状层级。
- `metadata.trace_id`：业务侧辅助标识，不参与 LangSmith 内部层级构建。

结论：只有 `metadata.trace_id` 一致但 `parent_run_id` 缺失时，UI 会平铺显示多个根节点。

### 2.2 一问一 Trace 的判定标准

- 同一次问答，所有关键 runs 的 `run.trace_id` 相同。
- 仅有一个根 run（`langgraph_agent`），其余 runs 都有正确 `parent_run_id`。

## 3. 当前实现（修复后）

### 3.1 总体策略

- 保留 LangGraph/LangSmith 自动追踪。
- 不再手工创建 `graph_node:*` runs（避免与自动节点重复）。
- MCP 客户端只透传 LangSmith 分布式追踪 headers，不再手工创建 `mcp_tool:*` / `mcp_list_tools` 子 runs。
- 每次请求创建一个 root run：`langgraph_agent`。
- 图编译时已挂 `PostgresSaver`，请求通过 `configurable.thread_id` 进入 LangGraph 原生 checkpoint 流程。
- `graph.invoke(..., config={"configurable": {"thread_id": ...}})` 在 `tracing_context(parent=root_run)` 内执行。
- MCP 服务端通过 `TracingMiddleware + ls_trace()` 记录工具 span，并自动挂到当前节点 run 下。
- root run 输出包含聚合字段：
  - `trace_version`
  - `node_records`
  - `final_state_output`
  - `main_flow_trace`

### 3.2 并发与子规划

- `execute_ready` 线程池提交任务前使用 `contextvars.copy_context()`。
- worker 通过 `ctx.run(...)` 执行步骤，继承父追踪上下文。
- `todo` 子规划在同一上下文内调用 LLM，不会新开根 trace。

### 3.3 关键节点上下文记录（新增）

- 主流程开始/结束：
  - root 输出 `main_flow_trace.init_state_snapshot`
  - root 输出 `main_flow_trace.final_state_snapshot`
- 工具执行输入（主流程视角）：
  - `execute_ready` 节点 `prompt_records.stage=tool_dispatch_inputs`
- 工具返回并回填主流程后：
  - `execute_ready` 节点 `prompt_records.stage=tool_dispatch_outputs`
  - 包含 `state_after_merge`（pending/completed/step_results/evidences/sources）
- 上下文压缩前后：
  - `build_context` 节点 `prompt_records.stage=context_before_compress`
  - `build_context` 节点 `prompt_records.stage=context_after_compress`
  - 同时写入 `context_build_stats`（chunk/token/compress 配置统计）
- 最终结果：
  - `generate_answer` 节点 `prompt_records` 记录请求上下文与答案预览
  - root 输出 `final_state_output` 与最终 `answer`

### 3.4 节点详情页可见性（新增）

- 每个自动节点 run（如 `plan`）直接写入标准化审计字段。
- 节点输入位于 run `inputs`：
  - `state_snapshot`
  - `business_input`
  - `prompt_records`
  - `context_payload`
- 节点输出位于 run `outputs`：
  - `status`
  - `duration_ms`
  - `output_summary`
  - `state_update`
  - `business_output`
  - `trace_extras`
- 因此无需只依赖 root 的 `node_records`，可直接在节点详情页查看完整节点审计。

### 3.5 LangGraph Studio 与 MCP 工具展示

**为什么图里看不到 MCP 工具（nl2sql / rag / graph / todo）？**

- LangGraph Studio 的**图视图**展示的是 `StateGraph` 的**节点**，即 `add_node(...)` 注册的节点：`plan`、`validate_plan`、`dispatch`、`execute_ready`、`collect_memory_notes`、`conflict_check`、`build_context`、`generate_answer`、`write_memory`。
- MCP 工具不是在图上单独建节点，而是在 **`execute_ready` 节点内部**按计划步骤调用的（`_run_nl2sql_step`、`_run_rag_step` 等），因此不会作为独立方框出现在图里。

**在哪里能看到 MCP 工具调用？**

- 在 **LangSmith 的 Run 树 / Trace 视图**中：展开 **`execute_ready`** 节点，其下会出现 MCP 服务端工具 span（如 `nl2sql_query`、`rag_search`、`neo4j_llamaindex_query` 等），即每次工具调用的输入输出与耗时。
- 这些工具 span 由 MCP Server 侧的 `TracingMiddleware + ls_trace()` 生成；客户端只负责透传分布式追踪头。

**若希望在图里看到“工具级”节点：** 需要改架构，把每种工具做成独立图节点（如 `add_node("nl2sql", ...)`）并由 dispatch 条件边路由到对应节点；当前实现是“单节点内多工具分发”，图视图只到 `execute_ready` 这一层。

## 4. 基本用法

### 4.1 环境变量

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_WORKSPACE_ID=...
LANGSMITH_PROJECT=internet-number-qa
LANGSMITH_DEFAULT_TAGS=fusion,langgraph,mcp
```

### 4.2 服务启动

```bash
# MCP
uvicorn agent.services.mcp.server:app --host 0.0.0.0 --port 2032

# API
uvicorn agent.services.http.server:app --host 0.0.0.0 --port 2025
```

### 4.3 发起一次问答并验证

1. 发起一次问答请求。
2. 在 LangSmith Dashboard 打开对应项目。
3. 验证：
   - trace 数量：1
   - root run：`langgraph_agent`
   - 子 run：自动节点/LLM runs 与 MCP 服务端工具 spans，均有父子关系
   - root outputs：存在 `node_records`、`final_state_output`、`main_flow_trace`

## 5. 命令行排障

使用脚本聚合链路并检测是否存在“单请求多 trace”：

```bash
python -m agent.scripts.trace_by_metadata_id \
  --project "${LANGSMITH_PROJECT}" \
  --trace-id "<run.trace_id 或 metadata.trace_id>" \
  --since-hours 24 \
  --show-io
```

关键输出说明：

- `match_mode=run.trace_id`：优先按内部 trace 匹配。
- `root_count`：匹配结果中的根节点数量。
- `trace_count`：匹配结果中的内部 trace 数量。
- `告警：...多个 LangSmith trace_id`：表示链路发生拆分。

## 6. 问题根因与修复方案

### 6.1 问题一：waterfall 中出现重复计划节点

现象：
- 同时出现 `plan` 与 `graph_node:plan`，开始时间接近。

根因：
- 自动节点追踪与手工节点追踪叠加。

修复：
- 移除手工 `graph_node:*` run，保留自动节点追踪。
- `node_records` 仅作为 root 输出聚合信息。

### 6.2 问题二：节点记录不足

现象：
- 仅有 summary，缺少最终输出或 prompt。

根因：
- 节点输出结构不统一，未强制写入审计字段。

修复：
- `_trace_node` 统一写入节点 run `inputs/outputs`，包含 `state_snapshot`、`business_input`、`prompt_records`、`context_payload`、`state_update`、`business_output`。
- plan/conflict/build_context/generate 节点补充 prompt、上下文与模型返回记录。

### 6.3 问题三：一次提问出现多个 trace

现象：
- 同一业务请求在 LangSmith 中拆成多个 trace。

根因：
- 并发线程未继承父上下文，子调用丢失 `parent_run_id`。
- MCP 请求未透传 LangSmith 分布式追踪头，导致服务端工具 span 脱离当前 trace。

修复：
- 线程池统一使用 `copy_context + ctx.run`。
- root 层包裹 `tracing_context(parent=root_run)`。
- MCP 客户端统一使用 `get_current_run_tree().to_headers()` 透传请求头。

## 7. 验收清单

- 一次问答仅 1 个 trace。
- 自动节点/LLM run 全部挂在同一 root 下。
- 不再出现 `graph_node:*` 节点重复。
- root outputs 包含：
  - `trace_version`
  - `node_records`
  - `final_state_output`
  - `main_flow_trace`
- 聚合脚本输出 `trace_count=1`，无多 trace 告警。
- 自动节点 run 详情页可直接看到 `inputs/outputs` 完整审计字段。

## 8. 维护建议

- 优先使用 `run.trace_id` 做链路分析，`metadata.trace_id` 仅做业务辅助筛选。
- 任何新增并发执行点都必须显式继承 `contextvars`。
- 若新增跨进程或跨服务工具调用，必须同步透传 LangSmith 分布式追踪头。
