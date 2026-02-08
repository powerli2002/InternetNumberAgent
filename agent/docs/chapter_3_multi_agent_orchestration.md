# Chapter 3: Multi-Agent 编排与工具协议 (The Hands: Orchestration)

## [核心机制]

### 3.1 协议驱动架构升级

主代理已从"进程内工具直调"升级到"协议驱动编排"，实现工具层与代理层的解耦：

**旧架构（2025年12月前）**：
```python
# ❌ 紧耦合：主代理直接实例化工具
class FusionAgent:
    def __init__(self):
        self.nl2sql_tool = NL2SQLTool(...)
        self.rag_tool = RAGTool(...)
        self.neo4j_tool = Neo4jTool(...)
    
    def respond(self, query: str):
        # 直接调用
        result = self.nl2sql_tool.query(query)
```

**新架构（2026年2月）**：
```python
# ✅ 松耦合：通过协议客户端调用
class FusionAgent:
    def __init__(self):
        self.mcp_client = MCPToolClient(server_url)  # 工具层协议
        self.a2a_client = A2AClient(base_url)        # 代理间协议
    
    def respond(self, query: str):
        # 协议调用
        result = self.mcp_client.call_tool("nl2sql_query", {...})
```

**架构分层**：

```
┌─────────────────────────────────────┐
│      FusionAgent (主代理)            │  ← 路由与聚合
│  - route_plan (Function Calling)     │
│  - route_step_tool (Function Calling)│
│  - prepare_context (GSSC)            │
└─────────────────────────────────────┘
          ↓ MCP (HTTP)     ↓ A2A (HTTP+SSE)
┌──────────────────┐  ┌────────────────────┐
│  MCP Tool Server │  │  A2A Worker Server │
│  - nl2sql_query  │  │  - supervisor      │
│  - rag_search    │  │    ├─ sql_facts   │
│  - note_search   │  │    ├─ rag_docs    │
│  - todo_add      │  │    ├─ graph_rel   │
└──────────────────┘  │    └─ verifier    │
                      └────────────────────┘
```

### 3.2 MCP 协议（工具层）

**FastMCP 规范**：基于 HTTP 的 Model Context Protocol

**服务端实现**（`agent/interfaces/mcp/server.py`）：
```python
from fastmcp import FastMCP

mcp = FastMCP("FusionProcessing Tools")

@mcp.tool()
def nl2sql_query(
    question: str,
    tables: list[str],
    enable_column_retrieval: bool = False,
    trace_id: str = None
) -> dict:
    """
    自然语言到 SQL 的转换与执行
    
    Args:
        question: 用户问题
        tables: 允许查询的表名列表
        enable_column_retrieval: 是否启用列值检索
        trace_id: LangSmith 追踪 ID
    
    Returns:
        {
          "sql": "SELECT ...",
          "result": {
            "columns": [...],
            "rows": [...],
            "row_count": 10,
            "truncated": false
          }
        }
    """
    nl2sql_tool = NL2SQLTool(...)
    result = nl2sql_tool.query(question, tables, enable_column_retrieval)
    return {
        "sql": result.sql,
        "result": result.result
    }
```

**客户端调用**（`agent/mcp/client.py`）：
```python
class MCPToolClient:
    """
    MCP 工具客户端
    
    核心方法：call_tool(tool_name, parameters)
    """
    
    def call_tool(
        self,
        tool_name: str,
        parameters: dict,
        trace_id: str = None,
        root_run = None
    ) -> Any:
        """
        HTTP POST 调用 MCP 工具
        
        来自 agent/mcp/client.py
        
        流程：
        1. 构造 HTTP 请求体
        2. POST {server_url}/mcp/tool/{tool_name}
        3. 解析返回 JSON
        4. 写入 LangSmith 追踪
        """
        # LangSmith 追踪（可选）
        if self.tracer.enabled and root_run:
            with self.tracer.start_run(
                name=f"mcp_{tool_name}",
                run_type="tool",
                inputs=parameters,
                tags=["mcp", tool_name],
                parent=root_run
            ) as run:
                response = self._http_post(tool_name, parameters)
                run.add_outputs(response)
                return response
        else:
            return self._http_post(tool_name, parameters)
    
    def _http_post(self, tool_name: str, parameters: dict) -> Any:
        url = f"{self.server_url}/mcp/tool/{tool_name}"
        response = requests.post(
            url,
            json=parameters,
            timeout=self.timeout_seconds
        )
        response.raise_for_status()
        return response.json()
```

### 3.3 A2A 协议（代理间）

**Agent-to-Agent 协议**：基于 HTTP+SSE 的任务执行协议

**任务载荷结构**（`agent/protocols/a2a/models.py`）：
```python
@dataclass
class A2ATaskPayload:
    """
    A2A 任务载荷（标准化）
    
    发送方：主代理 FusionAgent
    接收方：A2A Worker（执行 supervisor 或子代理）
    """
    task_id: str                 # 唯一任务 ID
    agent: str                   # 目标代理名称（supervisor/sql_facts/...）
    objective: str               # 任务目标描述
    constraints: dict            # 约束条件（tables/tools_allowed/max_rows）
    context: dict                # 上下文信息（question/history_tail/...）
    expected_output: str         # 期望输出格式
    budget: dict                 # 资源预算（max_tokens/max_time_ms）
    trace_id: str                # LangSmith 追踪 ID
```

**服务端实现**（`agent/interfaces/a2a/server.py`）：
```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.post("/a2a/task")
async def execute_task(payload: A2ATaskPayload):
    """
    执行 A2A 任务（支持 SSE 流式）
    
    流程：
    1. 验证 payload 格式
    2. 路由到对应子代理执行器
    3. 流式返回中间状态（SSE）
    4. 最终返回结果封装（A2AResultEnvelope）
    """
    executor = A2AExecutor(config)
    
    # 流式执行（SSE）
    async def generate_events():
        async for event in executor.execute_stream(payload):
            # SSE 格式：data: {json}\n\n
            yield f"data: {json.dumps(event)}\n\n"
    
    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream"
    )
```

**客户端调用**（`agent/protocols/a2a/client.py`）：
```python
class A2AClient:
    """
    A2A 协议客户端
    
    核心方法：execute_task(payload)
    """
    
    def execute_task(
        self,
        payload: A2ATaskPayload,
        root_run = None
    ) -> A2AResultEnvelope:
        """
        发起 A2A 任务执行
        
        来自 agent/protocols/a2a/client.py
        
        流程：
        1. POST /a2a/task with JSON payload
        2. 接收 SSE 流（可选）
        3. 解析最终结果
        4. 写入 LangSmith 追踪
        """
        url = f"{self.base_url}/a2a/task"
        
        # LangSmith 追踪
        if self.tracer.enabled and root_run:
            with self.tracer.start_run(
                name=f"a2a_{payload.agent}",
                run_type="chain",
                inputs={"task_id": payload.task_id, "objective": payload.objective},
                tags=["a2a", payload.agent],
                parent=root_run
            ) as run:
                result = self._execute_http(url, payload)
                run.add_outputs(result.to_dict())
                return result
        else:
            return self._execute_http(url, payload)
    
    def _execute_http(self, url: str, payload: A2ATaskPayload) -> A2AResultEnvelope:
        response = requests.post(
            url,
            json=payload.to_dict(),
            timeout=self.timeout_seconds,
            stream=True  # 支持 SSE
        )
        # 解析 SSE 流（略）
        # 返回最终结果
        return A2AResultEnvelope.from_dict(response.json())
```

### 3.4 主代理编排流程

**核心链路**（`agent/runtime/fusion_agent.py`）：

```python
def _prepare_context(self, user_message: str, history, root_run, trace_id: str):
    """
    主编排流程：先规划（plan-only）→ 单步选工具（step-action）→ 执行

    步骤：
    1. _plan_steps() 生成 ToolRouterDecision（每步只有 objective/constraints）
    2. 对每个 PlanStep 调用 _route_step_tool() 生成 ToolActionStep（tool + arguments）
    3. 按 ToolActionStep 执行 MCP/A2A：
       - tool=nl2sql → MCP.call_tool("nl2sql_query", ...)
       - tool=rag → MCP.call_tool("rag_search", ...)
       - tool=todo → A2A.execute_task(supervisor, ...)
    4. 收集 evidences + memories + notes
    5. 调用 ContextBuilder.build() 组装最终上下文（GSSC）
    """
    plan_decision = self._plan_steps(user_message, history, trace_id, root_run)
    for idx, step in enumerate(plan_decision.plan[:plan_decision.max_turns]):
        action = self._route_step_tool(
            step=step,
            user_message=user_message,
            question_type=question_type,
            trace_id=trace_id,
            root_run=root_run,
            step_index=idx,
        )
        # 下面按 action.tool 执行 MCP/A2A
```

## [代码映射]

### 2.1 工具路由决策

当前版本采用**两阶段 Function Calling**：

```python
def _plan_steps(self, user_message: str, history, trace_id: str, root_run):
    """
    阶段一：只输出计划（plan-only），不绑定工具
    """
    messages = [
        LLMMessage(role="system", content=TOOL_ROUTER_PROMPT),
        LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
    ]
    _, result_payload = self.llm.tool_call(
        messages,
        tools=[tool_router_schema()],      # name=route_plan
        tool_choice="required",
    )
    return ToolRouterDecision.from_dict(result_payload)


def _route_step_tool(self, step: ToolPlanStep, ..., step_index: int):
    """
    阶段二：针对单个 PlanStep 选择工具并给参数
    """
    messages = [
        LLMMessage(role="system", content=STEP_ACTOR_PROMPT),
        LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
    ]
    _, result_payload = self.llm.tool_call(
        messages,
        tools=[step_router_schema(allowed_tool_names())],  # name=route_step_tool
        tool_choice="required",
    )
    return ToolActionStep.from_dict(result_payload)
```

**阶段一 Schema（plan-only）**（`agent/runtime/tool_router_schemas.py`）：
```python
def tool_router_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "route_plan",
            "description": "只输出计划步骤，不直接选择工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "objective": {
                                    "type": "string",
                                    "description": "该步骤要解决的具体目标"
                                },
                                "constraints": {
                                    "type": "object",
                                    "description": "约束条件（如 tables/top_k）"
                                }
                            },
                            "required": ["objective"]
                        }
                    },
                    "reason": {"type": "string"},
                    "max_turns": {"type": "integer"}
                },
                "required": ["plan", "reason"]
            }
        }
    }
```

**阶段二 Schema（step-action）**（`agent/runtime/tool_router_schemas.py`）：
```python
def step_router_schema(tools_allowed=None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "route_step_tool",
            "description": "针对单个步骤选择工具并给出参数",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "enum": ["nl2sql", "rag", "todo", "none"]},
                    "objective": {"type": "string"},
                    "arguments": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "query": {"type": "string"},
                            "tables": {"type": "array", "items": {"type": "string"}},
                            "top_k": {"type": "integer"},
                            "enable_column_retrieval": {"type": "boolean"}
                        },
                        "additionalProperties": True
                    }
                },
                "required": ["tool"]
            }
        }
    }
```

### 2.2 A2A 子任务执行

**Todo 规划 → A2A 执行**（`agent/runtime/fusion_agent.py:362-399`）：

```python
def _run_todo_via_a2a(
    self,
    todo_items: List[TodoItem],
    user_message: str,
    trace_id: str,
    root_run
) -> List[A2AResultEnvelope]:
    """
    将 Todo 子任务发送给 A2A supervisor 执行
    
    来自 agent/runtime/fusion_agent.py:362-399
    
    流程：
    1. 遍历 todo_items
    2. 为每个 todo 构造 A2ATaskPayload
    3. 调用 a2a_client.execute_task()
    4. 收集执行结果
    """
    results: List[A2AResultEnvelope] = []
    for item in todo_items:
        payload = A2ATaskPayload(
            agent="supervisor",
            objective=f"{item.title}\n{item.intent}".strip(),
            constraints={
                "tables": self.config.allowed_tables,
                "tools_allowed": ["sql_facts", "rag_docs", "graph_relations", "verifier"]
            },
            context={
                "task_id": item.id,
                "intent": item.intent,
                "question": user_message
            },
            expected_output="结构化结果 + 证据摘要",
            budget={
                "max_tokens": self.config.subagent_max_tokens,
                "max_time_ms": self.config.subagent_max_time_ms
            },
            trace_id=trace_id
        )
        result = self.a2a_client.execute_task(payload, root_run=root_run)
        results.append(result)
    return results
```

**A2A Worker 内部路由**（`agent/workers/executor.py`）：
```python
class A2AExecutor:
    """
    A2A Worker 执行器
    
    职责：
    - 接收 A2ATaskPayload
    - 路由到具体子代理（sql_facts/rag_docs/graph_relations/verifier）
    - 返回 A2AResultEnvelope
    """
    
    def execute(self, payload: A2ATaskPayload) -> A2AResultEnvelope:
        """
        同步执行（简化版，实际支持流式）
        
        路由逻辑：
        - agent="supervisor" → 内部再次路由到 sql_facts/rag_docs/...
        - agent="sql_facts" → 直接执行 NL2SQL
        - agent="rag_docs" → 直接执行 RAG
        - agent="graph_relations" → 直接执行 Neo4j 查询
        - agent="verifier" → 对比多源数据，输出置信度
        """
        if payload.agent == "supervisor":
            # 二次路由
            return self._execute_supervisor(payload)
        elif payload.agent == "sql_facts":
            return self._execute_sql_facts(payload)
        elif payload.agent == "rag_docs":
            return self._execute_rag_docs(payload)
        elif payload.agent == "graph_relations":
            return self._execute_graph_relations(payload)
        elif payload.agent == "verifier":
            return self._execute_verifier(payload)
        else:
            raise ValueError(f"Unknown agent: {payload.agent}")
    
    def _execute_sql_facts(self, payload: A2ATaskPayload) -> A2AResultEnvelope:
        """
        SQL 事实查询子代理
        
        步骤：
        1. 调用 NL2SQLTool
        2. 封装结果为 A2AResultEnvelope
        """
        nl2sql_tool = NL2SQLTool(...)
        result = nl2sql_tool.query(
            payload.objective,
            tables=payload.constraints.get("tables")
        )
        return A2AResultEnvelope(
            task_id=payload.task_id,
            agent="sql_facts",
            status="ok",
            result={
                "sql": result.sql,
                "data": result.result
            },
            evidence=[
                EvidenceItem(
                    title="SQL查询结果",
                    content=f"SQL: {result.sql}\nRows: {result.result['row_count']}",
                    source="sql_facts",
                    score=1.0
                )
            ],
            errors=[]
        )
```

## [实战 I/O 示例]

### 示例 1：两阶段路由（Function Calling 输出）

**用户输入**：`先查 AS4134 的主要前缀，再给出相关文档解释与结论`

**阶段一（route_plan）输出**：
```json
{
  "plan": [
    {
      "objective": "查询 AS4134 的主要前缀与数量",
      "constraints": {
        "tables": ["ip_bgp_entity", "as_entity"],
        "enable_column_retrieval": true
      },
      "expected_output": "结构化前缀列表",
      "budget": {
        "max_tokens": 1200,
        "max_time_ms": 15000
      }
    },
    {
      "objective": "检索 AS 与前缀归属解释文档",
      "constraints": {
        "top_k": 5
      },
      "expected_output": "文档证据摘要",
      "budget": {
        "max_tokens": 800
      }
    }
  ],
  "reason": "先给结构化事实（NL2SQL），再补充解释证据（RAG）",
  "max_turns": 2
}
```

**阶段二（route_step_tool）输出（第 1 步）**：
```json
{
  "tool": "nl2sql",
  "objective": "查询 AS4134 的主要前缀与数量",
  "arguments": {
    "question": "查询 AS4134 的主要前缀与数量",
    "tables": ["ip_bgp_entity", "as_entity"],
    "enable_column_retrieval": true
  }
}
```

**阶段二（route_step_tool）输出（第 2 步）**：
```json
{
  "tool": "rag",
  "objective": "检索 AS 与前缀归属解释文档",
  "arguments": {
    "query": "检索 AS 与前缀归属解释文档",
    "top_k": 5
  }
}
```

**执行流程（MCP）**：
```python
# [1] NL2SQL 工具调用（MCP）
nl2sql_result = mcp_client.call_tool("nl2sql_query", {
    "question": "查询 AS4134 的主要前缀与数量",
    "tables": ["ip_bgp_entity", "as_entity"],
    "enable_column_retrieval": true
})

# 返回：
{
  "sql": "SELECT prefix, prefix_len FROM ip_bgp_entity WHERE bgp = 4134 LIMIT 200",
  "result": {
    "columns": ["prefix", "prefix_len"],
    "rows": [
      ["1.0.1.0/24", 24],
      ["1.0.2.0/24", 24],
      ...
    ],
    "row_count": 182,
    "truncated": false
  }
}

# [2] RAG 工具调用（MCP）
rag_result = mcp_client.call_tool("rag_search", {
    "query": "检索 AS 与前缀归属解释文档",
    "top_k": 5
})
```

### 示例 2：TodoItem → A2A 载荷完整链路

**场景**：复杂问题需要拆分执行

**用户输入**：`分析 AS4134 的前缀分布、上游关系和历史变化趋势`

**步骤 1：主代理规划 Todo**（`agent/runtime/fusion_agent.py:615-652`）

```python
def _plan_todos(self, text: str) -> List[TodoItem]:
    """
    使用 LLM 生成待办列表
    
    提示词：TODO_PLANNER_PROMPT
    输出：JSON 数组
    """
    prompt = [
        LLMMessage(role="system", content=TODO_PLANNER_PROMPT),
        LLMMessage(role="user", content=text)
    ]
    response = self.llm.chat(prompt)
    data = json.loads(response)
    return [
        TodoItem(
            id=str(uuid.uuid4())[:8],
            title=item["title"],
            intent=item["intent"],
            status="pending"
        )
        for item in data
    ]
```

**LLM 返回的 Todo 计划**：
```json
[
  {
    "id": "b47b5d8a",
    "title": "查询前缀分布统计",
    "intent": "统计 AS4134 的 IPv4 和 IPv6 前缀数量与国家分布",
    "status": "pending"
  },
  {
    "id": "cf2f7f10",
    "title": "查询上游关系",
    "intent": "通过图谱查询 AS4134 的上游 AS 列表",
    "status": "pending"
  },
  {
    "id": "d8a2e1c3",
    "title": "分析历史趋势",
    "intent": "对比不同日期快照的前缀数量变化",
    "status": "pending"
  }
]
```

**步骤 2：转换为 A2A 载荷**

```python
# 第一个 Todo 的 A2A 载荷
payload_1 = A2ATaskPayload(
    task_id="b47b5d8a",
    agent="supervisor",
    objective="查询前缀分布统计\n统计 AS4134 的 IPv4 和 IPv6 前缀数量与国家分布",
    constraints={
        "tables": ["ip_bgp_entity", "ipv6_bgp_entity", "as_entity"],
        "tools_allowed": ["sql_facts", "rag_docs", "graph_relations", "verifier"]
    },
    context={
        "task_id": "b47b5d8a",
        "intent": "统计 AS4134 的 IPv4 和 IPv6 前缀数量与国家分布",
        "question": "分析 AS4134 的前缀分布、上游关系和历史变化趋势"
    },
    expected_output="结构化统计结果 + 证据摘要",
    budget={
        "max_tokens": 1200,
        "max_time_ms": 15000
    },
    trace_id="trace-abc123"
)
```

**步骤 3：A2A Worker 执行**

```python
# Worker 内部路由到 sql_facts 子代理
executor = A2AExecutor(config)
result = executor.execute(payload_1)

# 返回 A2AResultEnvelope
{
  "task_id": "b47b5d8a",
  "agent": "sql_facts",
  "status": "ok",
  "result": {
    "summary": "AS4134 拥有 182 个 IPv4 前缀，主要分布在 CN（中国）",
    "data": {
      "sql": "SELECT country, COUNT(*) AS prefix_count FROM ip_bgp_entity WHERE bgp = 4134 GROUP BY country ORDER BY prefix_count DESC LIMIT 200",
      "rows": [
        {"country": "CN", "prefix_count": 182},
        {"country": "US", "prefix_count": 12}
      ]
    }
  },
  "evidence": [
    {
      "title": "SQL查询结果",
      "content": "SQL: SELECT country, COUNT(*) ...\nRows: 2",
      "source": "sql_facts",
      "score": 1.0,
      "metadata": {"tables": ["ip_bgp_entity"]}
    }
  ],
  "errors": []
}
```

### 示例 3：MCP vs A2A 调用对比

**场景对比**：

| 维度 | MCP 工具调用 | A2A 子代理调用 |
|------|------------|---------------|
| **协议** | HTTP POST | HTTP POST + SSE |
| **用途** | 单一工具执行 | 复杂任务编排 |
| **输入** | 工具参数 | 任务载荷（标准化） |
| **输出** | 工具结果（JSON） | 结果封装 + 证据 + 错误 |
| **追踪** | LangSmith 单次调用 | LangSmith 子链路 |
| **典型工具** | nl2sql_query, rag_search | supervisor, sql_facts, verifier |

**MCP 示例代码**：
```python
# 简单直接的工具调用
result = mcp_client.call_tool("nl2sql_query", {
    "question": "查询 AS4134 的前缀数",
    "tables": ["ip_bgp_entity"]
})
# 直接使用 result["sql"] 和 result["result"]
```

**A2A 示例代码**：
```python
# 复杂任务需要二次路由
payload = A2ATaskPayload(
    agent="supervisor",
    objective="综合分析 AS4134",
    constraints={"tools_allowed": ["sql_facts", "rag_docs", "graph_relations"]},
    ...
)
result = a2a_client.execute_task(payload)
# 需要解析 A2AResultEnvelope，提取 result.result、result.evidence
```

## [面试攻防]

### 问题 1：为什么 Function Calling + Protocol，不用传统 ReAct Loop？

**回答要点 1**：**Function Calling 输出结构化 JSON，减少自由文本解析失败**

```text
ReAct Loop 问题示例：
LLM 输出: "我需要调用 SQL 工具查询 AS4134 的前缀"
解析器: 正则匹配 "调用 (\w+) 工具" → 提取 "SQL"
❌ 失败：工具名是 "nl2sql"，不是 "SQL"

Function Calling 优势：
阶段一输出: {"plan": [{"objective": "..."}], "reason": "..."}
阶段二输出: {"tool": "nl2sql", "arguments": {...}}
解析器: json.loads() → 直接获取工具名
✅ 成功：结构化输出，无歧义
```

**回答要点 2**：**MCP/A2A 协议将"决策"和"执行"隔离，便于治理与扩展**

```text
传统架构（紧耦合）：
FusionAgent → 直接实例化 NL2SQLTool → 执行
❌ 问题：
- 工具升级需要重启主代理
- 无法独立扩展工具服务
- 难以实施访问控制

协议架构（松耦合）：
FusionAgent → MCP Client → (HTTP) → MCP Server → NL2SQLTool
✅ 优势：
- 工具服务独立部署、独立扩展
- 可以在 MCP Server 层统一实施鉴权、限流
- 便于 A/B 测试不同工具实现
```

**回答要点 3**：**ReAct 常见问题是隐式状态和链路不可控；协议化后可做 SLA、重试、审计**

```python
# ReAct Loop 问题：状态隐式
while True:
    thought = llm.generate("What should I do?")
    if "FINAL ANSWER" in thought:
        break
    action = parse_action(thought)  # 不可控
    observation = execute_action(action)

# 协议化优势：状态显式
plan = llm.function_call(tool_router_schema())  # 阶段一：计划
for step in plan["plan"]:
    action = llm.function_call(step_router_schema())  # 阶段二：单步动作
    try:
        result = mcp_client.call_tool(action["tool"], action.get("arguments", {}))
        evidences.append(result)
    except Timeout:
        # 显式处理超时，重试或降级
        evidences.append(fallback_result)
```

### 问题 2：MCP 和 A2A 的边界在哪里？什么时候用 MCP，什么时候用 A2A？

**判断标准**：

| 特征 | MCP 工具 | A2A 子代理 |
|------|---------|-----------|
| **决策复杂度** | 无需决策，直接执行 | 需要二次路由或多步推理 |
| **输入格式** | 工具参数（简单） | 任务载荷（复杂） |
| **典型场景** | SQL 查询、文档检索、笔记管理 | 任务拆解、多工具编排、验证 |
| **返回格式** | 工具结果 | 结果 + 证据 + 置信度 |

**示例对比**：

```python
# 场景 1：单一 SQL 查询 → 用 MCP
mcp_client.call_tool("nl2sql_query", {"question": "查 AS4134 的前缀数"})

# 场景 2：需要对比多源数据 → 用 A2A (verifier 子代理)
a2a_client.execute_task(A2ATaskPayload(
    agent="verifier",
    objective="对比 AS4134 的注册归属与 BGP 观测归属",
    constraints={"tables": ["ip_bgp_entity", "ip_route_entity"]}
))
# verifier 内部会：
# 1. 查询注册数据
# 2. 查询 BGP 数据
# 3. 对比差异
# 4. 返回置信度评分
```

### 问题 3：如果 A2A Worker 宕机，主代理如何降级？

**降级策略**：

```python
def _run_todo_via_a2a_with_fallback(self, todo_items, user_message, trace_id, root_run):
    """
    A2A 调用 + 降级策略
    
    流程：
    1. 尝试 A2A 调用
    2. 超时或连接失败 → 降级为 MCP 直接调用
    3. 返回降级标记
    """
    results = []
    for item in todo_items:
        try:
            # 尝试 A2A
            payload = A2ATaskPayload(agent="supervisor", objective=item.title, ...)
            result = self.a2a_client.execute_task(payload, timeout=10)
            results.append(result)
        except (Timeout, ConnectionError) as e:
            logger.warning("A2A call failed, fallback to MCP: %s", e)
            # 降级：直接用 MCP 执行 nl2sql + rag
            nl2sql_result = self.mcp_client.call_tool("nl2sql_query", {...})
            rag_result = self.mcp_client.call_tool("rag_search", {...})
            # 封装为 A2AResultEnvelope 兼容格式
            fallback_result = A2AResultEnvelope(
                task_id=item.id,
                agent="fallback",
                status="ok",
                result={"nl2sql": nl2sql_result, "rag": rag_result},
                evidence=[...],
                errors=[f"A2A service unavailable: {e}"]
            )
            results.append(fallback_result)
    return results
```

### 问题 4：LangSmith 追踪在协议调用中如何传递？

**追踪传递链路**：

```
FusionAgent (root_run)
  ↓ trace_id
MCP Client (child_run: mcp_nl2sql)
  ↓ HTTP Header: X-Trace-Id
MCP Server (继续传递)
  ↓ trace_id
NL2SQLTool (记录到 LangSmith)
```

**代码实现**（`agent/mcp/client.py`）：

```python
class MCPToolClient:
    def call_tool(self, tool_name: str, parameters: dict, trace_id: str, root_run):
        """
        MCP 调用时写入 LangSmith 追踪
        
        流程：
        1. 创建子 run（parent=root_run）
        2. HTTP 请求携带 trace_id
        3. 记录输入输出到 LangSmith
        """
        if self.tracer.enabled and root_run:
            with self.tracer.start_run(
                name=f"mcp_{tool_name}",
                run_type="tool",
                inputs=parameters,
                tags=["mcp", tool_name],
                metadata={"trace_id": trace_id},
                parent=root_run  # 关键：关联到父 run
            ) as run:
                response = self._http_post(tool_name, parameters, trace_id)
                run.add_outputs(response)
                return response
        else:
            return self._http_post(tool_name, parameters, trace_id)
    
    def _http_post(self, tool_name: str, parameters: dict, trace_id: str):
        url = f"{self.server_url}/mcp/tool/{tool_name}"
        headers = {"X-Trace-Id": trace_id}  # 传递 trace_id
        response = requests.post(url, json=parameters, headers=headers, timeout=self.timeout_seconds)
        return response.json()
```

---

**技术深度总结**：
- 协议驱动架构实现工具层与代理层解耦，提升扩展性与治理能力
- Function Calling 提供结构化输出，避免 ReAct Loop 的文本解析失败
- MCP 适用于单一工具执行，A2A 适用于复杂任务编排
- 降级策略确保 A2A 服务不可用时主代理仍可工作
- LangSmith 追踪通过 parent run 关联实现全链路可观测
