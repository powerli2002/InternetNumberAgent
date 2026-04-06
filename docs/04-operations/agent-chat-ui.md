# 前端接入

## 当前主前端

当前正式前端为根目录 `webapp/`。

先启动用户界面链路：

```bash
./deploy/start_ui_chain.sh
```

推荐配置：

```dotenv
NEXT_PUBLIC_BACKEND_URL=http://localhost:2026
```

## 关键说明
- 正式前端直接连接 `backend/`，不再直接连接 `agent/services/http/`。
- `backend/` 负责认证、线程、过程事件、artifact 与 OpenSandbox。
- `agent/` 只保留智能体运行时与 MCP 工具。
- 图片 artifact 在前端通过同源代理路由 `/api/artifacts/{artifact_id}/content` 预览，避免跨端口 Cookie 与图片加载问题。
- 回答正文支持 `artifact://artifact_id` 形式的 Markdown 图片引用；渲染后会直接在消息中显示对应图表，并支持点击放大。

## 兼容壳

仓库中仍保留 `agent-chat-ui/` 作为兼容和调试壳，但不再是当前产品入口。

## 常见问题
- 登录失败：检查 `backend.main:app` 是否启动、Cookie 是否被浏览器拦截。
- 过程面板无事件：检查 `./deploy/start_ui_chain.sh` 是否成功拉起 MCP 与产品后端。
- Python 沙箱不可用：检查 OpenSandbox Server、`OPENSANDBOX_*` 与 `SANDBOX_*` 配置。
