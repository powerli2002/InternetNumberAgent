# Agent Chat UI 接入指南

本指南说明如何将 LangChain 的 Agent Chat UI 接入当前“互联网号码资源问答系统”。系统已提供 LangGraph 兼容 API（`agent/interfaces/http/server.py`），前端只需指向该 API 即可。

## 1. 启动后端服务（MCP + A2A + API）

方式一：本机运行

```bash
uvicorn agent.interfaces.mcp.server:app --host 0.0.0.0 --port 2032
uvicorn agent.interfaces.a2a.server:app --host 0.0.0.0 --port 2031
uvicorn agent.interfaces.http.server:app --host 0.0.0.0 --port 2025
```

方式二：Docker Compose

```bash
docker compose -f docker/docker-compose.yml up -d agent-mcp agent-a2a agent-api
```

> API 默认监听 `http://localhost:2025`，并提供 LangGraph 风格的 `/threads`、`/threads/search`、`/threads/{id}/runs/stream` 等端点。  
> 其中 API 依赖 `MCP_SERVER_URL`（默认 `http://localhost:2032/mcp`）和 `A2A_SERVER_URL`（默认 `http://localhost:2031/a2a`）。

## 2. 克隆并运行 Agent Chat UI

也可以使用官方脚手架创建新项目（可选）：

```bash
npx create-agent-chat-app
```

如需直接接入本系统，建议继续采用 git clone 的方式，便于配置自定义后端地址。


```bash
git clone https://github.com/langchain-ai/agent-chat-ui.git
cd agent-chat-ui
pnpm install
```

创建 `.env.local`：

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:2025
NEXT_PUBLIC_ASSISTANT_ID=fusion-agent
```

启动 UI（如 3000 被占用可改为 3010）：

```bash
pnpm exec next dev -H 0.0.0.0 -p 3010
```

浏览器访问：`http://localhost:3010`

也可以直接用 Docker Compose 启动 UI：

```bash
docker compose -f docker/docker-compose.yml up -d agent-ui
```

> 说明：Docker Compose 默认将容器的 3010 映射到宿主 3011，如需自定义请修改 `docker/docker-compose.yml`。

## 3. 关键说明

- `NEXT_PUBLIC_ASSISTANT_ID` 必须与后端返回的 assistant id 一致（当前默认 `fusion-agent`）。
- 若采用 Docker 部署 UI，请确保 UI 容器能够访问到后端 `agent-api` 的地址。
- 线程与消息会持久化到 PostgreSQL 的 `agent_threads` 与 `agent_messages` 表中，确保可追溯与可检索。

## 4. 常见问题

1) **UI 无法加载线程列表**：检查 API `POST /threads/search` 是否可访问。
2) **消息不显示**：确认 `NEXT_PUBLIC_API_URL` 是否指向 `http://localhost:2025`。
3) **接口 404**：检查后端是否启动，并确认端口已暴露。

---

如需扩展 UI 功能（主题、工具栏、线程过滤等），可在 `agent-chat-ui` 的 `src/` 中进行二次开发。
