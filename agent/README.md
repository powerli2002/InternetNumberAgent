# Agent 目录结构说明

本目录按分层方式整理，目标是降低耦合并提升可维护性。

## 分层结构（推荐新代码落点）

- `agent/core/`
  - 纯核心能力：配置、模型、提示词、LLM 客户端、追踪、NL2SQL schema。
- `agent/runtime/`
  - 运行时编排：`FusionAgent` 主流程、主代理工具路由协议与 schema。
- `agent/interfaces/http/`
  - HTTP 接口层：FastAPI 服务与线程/消息存储。
- `agent/interfaces/mcp/`
  - MCP 服务入口（FastMCP HTTP）。
- `agent/interfaces/a2a/`
  - A2A 服务入口（HTTP+SSE）。
- `agent/cli/`
  - 命令行入口。
- `agent/mcp/`、`agent/protocols/a2a/`、`agent/workers/`
  - MCP 客户端/服务端、A2A 协议模型与客户端、Worker 执行器。
- `agent/context/`、`agent/memory/`、`agent/tools/`、`agent/subagents/`
  - 上下文工程、记忆系统、底层工具实现、子代理路由协议。

## 入口说明

- HTTP 服务入口：`agent/interfaces/http/server.py`
- MCP 服务入口：`agent/interfaces/mcp/server.py`
- A2A 服务入口：`agent/interfaces/a2a/server.py`
- 运行时主编排入口：`agent/runtime/fusion_agent.py`
- CLI 入口：`agent/cli/main.py`

旧入口文件（如 `agent/api_server.py`、`agent/agent_loop.py`、`agent/main.py`）不再保留。

## 开发约定

- 新增模块优先使用分层路径导入，例如 `from agent.core.config import AgentConfig`。
- 运行时状态文件（如 sqlite、缓存）应放在 `agent/memory_store/` 或专用数据目录，不与源码逻辑混放。
