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

## RAG 策略（已升级）

当前 RAG 管道已统一为：

1. **统一转换**：`agent/tools/rag_ingest_pipeline.py` 使用 `MarkItDown` 将文档统一转为 Markdown。  
2. **智能分块**：按 Markdown 标题层级 + 段落/代码块边界切分，并保留重叠窗口。  
3. **离线向量化**：默认使用本地 `bge`（`BAAI/bge-m3`），不依赖在线 embedding API。  
4. **召回策略**：检索阶段默认启用 **MQE + RRF**（多查询扩展 + 融合排序），提升复杂问法召回稳定性。  
5. **增量去重**：写入 Milvus 前按 `source + text` 哈希去重（批内 + 存量）。

### 关键文件

- 入库脚本：`agent/knowledge_ingest.py`
- 入库流水线：`agent/tools/rag_ingest_pipeline.py`
- 检索与向量库：`agent/tools/rag_tool.py`
- MCP 对外工具：`agent/services/mcp/server.py`

### 关键环境变量

- `RAG_EMBEDDING_BACKEND`：`local_bge`（默认）或 `dashscope`
- `RAG_EMBEDDING_MODEL`：默认 `BAAI/bge-m3`（可改为本地模型目录）
- `RAG_EMBEDDING_DEVICE`：`cpu` / `cuda` / `mps`
- `RAG_EMBEDDING_BATCH_SIZE`：默认 `16`
- `RAG_EMBEDDING_NORMALIZE`：默认 `true`
- `NL2SQL_EMBEDDING_BACKEND`：`local_bge`（默认）或 `dashscope`
- `NL2SQL_EMBEDDING_MODEL`：默认 `BAAI/bge-m3`（可改为本地模型目录）
- `NL2SQL_EMBEDDING_DEVICE`：`cpu` / `cuda` / `mps`
- `NL2SQL_EMBEDDING_BATCH_SIZE`：默认 `16`
- `NL2SQL_EMBEDDING_NORMALIZE`：默认 `true`
- `RAG_ENABLE_MQE`：默认 `true`
- `RAG_MQE_MAX_QUERIES`：默认 `4`
- `RAG_CANDIDATE_MULTIPLIER`：默认 `4`
- `RAG_RRF_K`：默认 `60`

### 入库示例

```bash
python agent/knowledge_ingest.py --root . --path agent/knowledge --reset
```
