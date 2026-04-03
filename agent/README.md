# Agent 模块说明

`agent/` 目录承载在线问答链路，包括 LangGraph 编排、HTTP API、FastMCP 工具服务、记忆与评测能力。

## 主要目录
- `runtime/`：FusionAgent、LangGraph 编排、上下文构建
- `services/http/`：HTTP API
- `services/mcp/`：FastMCP 服务端与客户端
- `tools/`：NL2SQL、RAG、Neo4j、Note、Todo
- `evaluate/`：自动评测流水线
- `store/`：运行时本地存储

## 文档入口
- 运行与启动命令：`../README.md`
- 当前架构：`../docs/02-architecture/overall-architecture.md`
- 部署与运行：`../docs/04-operations/deployment.md`
- 评测流水线：`../docs/04-operations/evaluation.md`

命令入口统一维护在根 `README.md`，本文件只保留目录说明。
