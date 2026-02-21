# Agent 目录结构说明

本目录按分层方式整理，目标是降低耦合并提升可维护性。

## 分层结构（推荐新代码落点）

- `agent/core/`
  - 纯核心能力：配置、模型、提示词、LLM 客户端、追踪、NL2SQL schema。
- `agent/runtime/`
  - 运行时编排：`FusionAgent` 主流程、主代理工具路由协议、上下文构建器。
- `agent/services/http/`
  - HTTP 接口层：FastAPI 服务与线程/消息存储。
- `agent/services/mcp/`
  - MCP 服务与客户端（FastMCP HTTP）。
- `agent/services/a2a/`
  - A2A 协议模型、客户端、Worker 执行器与服务（HTTP+SSE）。
- `agent/cli/`
  - 命令行入口。
- `agent/memory/`、`agent/tools/`、`agent/subagents/`
  - 记忆系统、底层工具实现、子代理路由协议。
- `agent/store/`
  - 统一运行时存储目录（`memory/`、`index/`、`notes/`）。

## 入口说明

- HTTP 服务入口：`agent/services/http/server.py`
- MCP 服务入口：`agent/services/mcp/server.py`
- A2A 服务入口：`agent/services/a2a/server.py`
- 运行时主编排入口：`agent/runtime/fusion_agent.py`
- CLI 入口：`agent/cli/main.py`

旧入口文件（如 `agent/api_server.py`、`agent/agent_loop.py`、`agent/main.py`）不再保留。

## 开发约定

- 新增模块优先使用分层路径导入，例如 `from agent.core.config import AgentConfig`。
- 运行时状态文件（如 sqlite、缓存）统一放在 `agent/store/`，避免散落目录。
