# Agent Chat UI 接入

## 后端服务

先启动 MCP 与 API：

```bash
uvicorn agent.services.mcp.server:app --host 0.0.0.0 --port 2032
uvicorn agent.services.http.server:app --host 0.0.0.0 --port 2025
```

默认 API 地址：`http://localhost:2025`

## 前端启动

```bash
cd agent-chat-ui
pnpm install
pnpm dev --port 3012
```

推荐配置：

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:2025
NEXT_PUBLIC_ASSISTANT_ID=fusion-agent
```

## 关键说明
- `NEXT_PUBLIC_ASSISTANT_ID` 需要与后端 assistant id 保持一致。
- UI 只负责前端展示，实际问答链路仍由后端 LangGraph + FastMCP 驱动。
- 若使用容器部署，确保 UI 容器能访问 API 与 MCP 依赖地址。

## 常见问题
- 线程列表加载失败：先检查 API 是否正常提供线程相关接口。
- 消息流不显示：检查 `NEXT_PUBLIC_API_URL` 是否正确。
- 404：检查 API 服务是否启动、端口是否暴露。
