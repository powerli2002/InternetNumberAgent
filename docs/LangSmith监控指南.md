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
- 不再手工创建 `graph_node:*` 与 `mcp_tool:*` runs。
- 每次请求创建一个 root run：`langgraph_agent`。
- `graph.invoke(...)` 在 `tracing_context(parent=root_run)` 内执行。
- root run 输出包含聚合字段：
  - `trace_version`
  - `node_records`
  - `final_state_output`

### 3.2 并发与子规划

- `execute_ready` 线程池提交任务前使用 `contextvars.copy_context()`。
- worker 通过 `ctx.run(...)` 执行步骤，继承父追踪上下文。
- `todo` 子规划在同一上下文内调用 LLM，不会新开根 trace。

### 3.3 采样策略

- 采样按请求一次决策（root run 决定）。
- child run 不再独立随机采样，避免“无 root 有 child”的孤儿链路。

## 4. 基本用法

### 4.1 环境变量

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_WORKSPACE_ID=...
LANGSMITH_PROJECT=internet-number-qa
LANGSMITH_SAMPLE_RATE=1.0
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
   - 子 run：自动节点/LLM runs，均有父子关系
   - root outputs：存在 `node_records` 与 `final_state_output`

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
- `_trace_node` 统一写入 `input_snapshot`、`output_summary`、`final_output`、`prompt_records`。
- plan/conflict/generate 节点补充 prompt 与模型返回记录。

### 6.3 问题三：一次提问出现多个 trace

现象：
- 同一业务请求在 LangSmith 中拆成多个 trace。

根因：
- 并发线程未继承父上下文，子调用丢失 `parent_run_id`。
- 子 run 独立采样导致孤儿链路。

修复：
- 线程池统一使用 `copy_context + ctx.run`。
- root 层包裹 `tracing_context(parent=root_run)`。
- 采样改为请求级一次决策，child 不独立采样。

## 7. 验收清单

- 一次问答仅 1 个 trace。
- 自动节点/LLM run 全部挂在同一 root 下。
- 不再出现 `graph_node:*` 节点重复。
- root outputs 包含：
  - `trace_version`
  - `node_records`
  - `final_state_output`
- 聚合脚本输出 `trace_count=1`，无多 trace 告警。

## 8. 维护建议

- 优先使用 `run.trace_id` 做链路分析，`metadata.trace_id` 仅做业务辅助筛选。
- 任何新增并发执行点都必须显式继承 `contextvars`。
- 如需恢复手工工具 run，建议做配置开关，默认保持关闭，避免再次产生重复追踪。
