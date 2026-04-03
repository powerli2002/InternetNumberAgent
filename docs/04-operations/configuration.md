# 配置说明

## 配置入口

运行配置优先集中在 `conf/.env`，部署参数与服务路径优先在 `conf/` 目录维护。原则是：
- 命令尽量固定
- 配置通过环境变量切换
- 缺失配置直接报错，不做静默回退

## LLM 后端切换

### 云端模型
- `LLM_BACKEND=cloud`
- 主要变量：`DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`DASHSCOPE_MODEL`

### 本地模型
- `LLM_BACKEND=local`
- 主要变量：`LOCAL_LLM_API_KEY`、`LOCAL_LLM_BASE_URL`、`LOCAL_LLM_MODEL`

## 本地 vLLM 说明
- 启动命令：`python agent/model/start_vllm.py`
- 若有旧进程占用 `2222`，可先清理：

```bash
kill $(lsof -ti tcp:2222)
pkill -f "VLLM::EngineCore"
```

- 建议把 `LOCAL_LLM_BASE_URL` 配置为宿主机可访问地址，而不是固定写 `127.0.0.1`，避免容器内服务无法访问本机 vLLM。
- 启动脚本会优先读取 `conf/.env` 中的本地模型配置；命令行参数只用于显式覆盖。

## 生成相关参数
- `LLM_TEMPERATURE`：普通回答生成温度
- `LLM_TOOL_TEMPERATURE`：工具调用与规划温度
- `LLM_CONTEXT_COMPRESS_TEMPERATURE`：上下文压缩温度
- `LOCAL_VLLM_MAX_MODEL_LEN`：总窗口与本机 vLLM 上下文长度

## RAG 与 NL2SQL 向量化配置

### RAG
- `RAG_EMBEDDING_BACKEND`
- `RAG_EMBEDDING_MODEL`
- `RAG_EMBEDDING_DEVICE`
- `RAG_EMBEDDING_BATCH_SIZE`
- `RAG_EMBEDDING_NORMALIZE`
- `VECTOR_COLLECTION`
- `RAG_ENABLE_MQE`

### NL2SQL
- `NL2SQL_EMBEDDING_BACKEND`
- `NL2SQL_EMBEDDING_MODEL`
- `NL2SQL_EMBEDDING_DEVICE`
- `NL2SQL_EMBEDDING_BATCH_SIZE`
- `NL2SQL_EMBEDDING_NORMALIZE`
- `NL2SQL_INDEX_CACHE_DIR`
- `NL2SQL_VECTOR_COLLECTION`
- `ALLOWED_TABLES`

## 存储目录配置
- `AGENT_STORE_DIR`：统一运行时存储根目录
- `MEMORY_STORE_DIR`：记忆本地目录
- `NOTES_DIR`：笔记目录
- `NL2SQL_INDEX_CACHE_DIR`：NL2SQL 索引缓存目录

默认约定是所有本地状态都收敛到 `agent/store/`，不要把状态文件散落到各业务目录。

## 运行与调试相关配置
- `MCP_SERVER_URL`：MCP 服务地址
- `REQUEST_TIMEOUT_SECONDS`
- `AGENT_REQUEST_TIMEOUT_SECONDS`
- `MCP_TIMEOUT_SECONDS`
- `LANGSMITH_*`：链路追踪配置

## 推荐维护方式
- 新增配置前，先检查是否已有等价变量。
- 变更配置项时，同步更新 `deployment.md`、`observability.md` 和根 `README.md`。
- 不要把私有主机地址、密码或一次性环境笔记写入当前主文档区。
