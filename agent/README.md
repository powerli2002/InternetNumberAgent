# Agent 目录结构说明

本目录按分层方式整理，目标是降低耦合并提升可维护性。

## 快速启动

启动 mcp服务
python -m uvicorn agent.services.mcp.server:app --host 0.0.0.0 --port 2032

启动 cli
python agent/cli/main.py

说明：CLI 默认不设置外层超时；工具执行期间会输出开始/结束日志与耗时。

.venv/bin/python -m agent.scripts.langgraph_dev --config langgraph.json --port 8123 --no-reload

说明：当前导出的 LangGraph 主图状态以 `messages` 作为唯一对话状态。项目主 HTTP 服务仍使用 `PostgresSaver` 持久化线程状态；但 `langgraph dev` / Studio 入口会改用 LangGraph API 自带 persistence，因此 `agent/langgraph_app.py` 不再导出带自定义 checkpointer 的图，避免本地调试启动时报错。可在 LangGraph Studio 中直接用 Chat 模式调试。`/threads/{id}/runs/stream` 已切到 LangGraph 原生 `custom + updates` 流式模式，不再先完整生成答案再切块。


启动 本地llm qwen3.5-4B
kill $(lsof -ti tcp:2222)
pkill -f "VLLM::EngineCore" 
cd /home/lzj/fusionprocessing/agent/model
nohup python start_vllm.py


## LLM 后端切换（cloud/local）

- `LLM_BACKEND=cloud`：使用 `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`DASHSCOPE_MODEL`。
- `LLM_BACKEND=local`：使用 `LOCAL_LLM_API_KEY`、`LOCAL_LLM_BASE_URL`、`LOCAL_LLM_MODEL`。
- 配置缺失会直接报错，不做静默回退。
- 建议把所有运行参数统一维护在 `conf/.env`（`AgentConfig` 启动时自动加载）。
- 温度参数同样统一由 `conf/.env` 管理：`LLM_TEMPERATURE`、`LLM_TOOL_TEMPERATURE`、`LLM_CONTEXT_COMPRESS_TEMPERATURE`。

本机 vLLM 启动示例：

```bash
python agent/model/start_vllm.py
```

补充说明：

- 启动脚本会默认读取 `conf/.env` 中的 `LOCAL_LLM_MODEL`、`LOCAL_LLM_API_KEY`、`LOCAL_LLM_BASE_URL`、`LOCAL_VLLM_MAX_MODEL_LEN`；命令行参数优先级更高。
- 启动脚本默认不显式传递 `trust_remote_code`，避免对已内置架构模型打印“参数无效”告警。
- 当 `tensor_parallel_size > 2` 时，脚本会自动添加 `--disable-custom-all-reduce`，减少当前 4 卡 PCIe 环境下的重复告警。
- 对 `Qwen/Qwen3.5-4B`，脚本还会默认追加 `--attention-backend TRITON_ATTN`、`--mm-encoder-attn-backend TRITON_ATTN`、`--language-model-only`、`--skip-mm-profiling`，并通过 `--default-chat-template-kwargs '{"enable_thinking": false}'` 关闭默认 thinking，优先走纯文本快速响应路径。
- `Qwen/Qwen3.5-4B` 首次冷启动需先下载大体积权重；下载完成前，OpenAI 兼容接口不会开始监听 `2222` 端口。


## 分层结构（推荐新代码落点）

- `agent/core/`
  - 纯核心能力：配置、模型、提示词、LLM 客户端、追踪、NL2SQL schema。
- `agent/runtime/`
  - 运行时编排：`FusionAgent`（LangGraph 主图）、上下文构建器。
- `agent/services/http/`
  - HTTP 接口层：FastAPI 服务与线程/消息存储。
- `agent/services/mcp/`
  - MCP 服务与客户端（FastMCP HTTP）。
- `agent/cli/`
  - 命令行入口。
- `agent/memory/`、`agent/tools/`
  - 记忆系统与底层工具实现。
- `agent/store/`
  - 统一运行时存储目录（`memory/`、`index/`、`notes/`）。

## 入口说明

- HTTP 服务入口：`agent/services/http/server.py`
- MCP 服务入口：`agent/services/mcp/server.py`
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
3. **离线向量化**：默认使用本地 `bge`（`BAAI/bge-m3`），底层统一采用 `HuggingFaceEmbedding`，不依赖在线 embedding API。  
4. **召回策略**：检索阶段默认启用 **MQE + RRF**（多查询扩展 + 融合排序），提升复杂问法召回稳定性。  
5. **增量去重**：写入 Milvus 前按 `source + text` 哈希去重（批内 + 存量）。

### 关键文件

- 入库脚本：`agent/knowledge_ingest.py`
- 入库流水线：`agent/tools/rag_ingest_pipeline.py`
- 检索与向量库：`agent/tools/rag_tool.py`
- MCP 对外工具：`agent/services/mcp/server.py`

### 关键环境变量

- `LOCAL_VLLM_MAX_MODEL_LEN`：同时控制应用侧上下文窗口与本机 vLLM 的 `max_model_len`（默认 `4096`）
- `LLM_TEMPERATURE`：普通文本生成温度（默认 `0.2`）
- `LLM_TOOL_TEMPERATURE`：工具/规划型 LLM 温度（默认 `0.0`）
- `LLM_CONTEXT_COMPRESS_TEMPERATURE`：上下文压缩温度（默认 `0.0`）
- `WORKING_MEMORY_SIZE` / `EPISODIC_MEMORY_SIZE` / `SEMANTIC_MEMORY_SIZE`：三层记忆容量
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
- `VECTOR_COLLECTION`：RAG 向量集合（默认 `fusion_docs`）
- `GRAPH_MAX_ROWS` / `GRAPH_MAX_CYPHER_LENGTH`：图查询约束
- `ALLOWED_TABLES`：NL2SQL 白名单（逗号分隔）

### 入库示例

```bash
python agent/knowledge_ingest.py --root . --path agent/knowledge --reset
```
