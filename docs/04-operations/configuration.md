# 配置说明

## 配置入口

运行配置优先集中在 `conf/.env`，部署参数与服务路径优先在 `conf/` 目录维护。原则是：
- 命令尽量固定
- 配置通过环境变量切换
- 缺失配置直接报错，不做静默回退

当前 `conf/` 目录职责如下：
- `conf/.env`：运行时环境变量入口。
- `conf/config.base.yaml`：融合处理共享基线配置。
- `conf/config.yaml`：本机默认 YAML 配置，继承 `config.base.yaml`。
- `conf/config.docker.yaml`：容器/导入脚本默认 YAML 配置，继承 `config.base.yaml`。
- `conf/milvus.yaml`：Milvus Standalone 配置。
- `conf/opensandbox.toml`：OpenSandbox 静态配置。

## LLM 后端切换

### 云端模型
- `LLM_BACKEND=cloud`
- 主要变量：`DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`DASHSCOPE_MODEL`

### 本地模型
- `LLM_BACKEND=local`
- 主要变量：`LOCAL_LLM_API_KEY`、`LOCAL_LLM_BASE_URL`、`LOCAL_LLM_MODEL`

## 本地 vLLM 说明
- 启动命令：`python services/agent/model/start_vllm.py`
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

默认约定是所有本地状态都收敛到 `services/agent/store/`，不要把状态文件散落到各业务目录。

## 运行与调试相关配置
- `MCP_SERVER_URL`：MCP 服务地址
- `SANDBOX_API_URL`：Agent 通过 HTTP 调用产品后端内部沙箱接口的地址
- `SANDBOX_SERVICE_TOKEN`：Agent 调用产品后端内部沙箱接口的服务令牌
- `SANDBOX_TIMEOUT_SECONDS`：Python 沙箱 HTTP 调用超时
- `BACKEND_SECRET_KEY`：产品后端会话密钥
- `BACKEND_SANDBOX_SERVICE_TOKEN`：产品后端内部沙箱令牌
- `OPENSANDBOX_DOMAIN`：OpenSandbox Server 地址
- `OPENSANDBOX_API_KEY`：OpenSandbox API Key
- `OPENSANDBOX_TEMPLATE`：OpenSandbox 默认模板
- `OPENSANDBOX_PYTHON_VERSION`：Code Interpreter 内的 Python 版本
- `REQUEST_TIMEOUT_SECONDS`
- `AGENT_REQUEST_TIMEOUT_SECONDS`
- `MCP_TIMEOUT_SECONDS`
- `LANGSMITH_*`：链路追踪配置

## OpenSandbox 推荐默认值

按官方 Docker 示例与当前仓库默认配置，建议使用：

```bash
SANDBOX_API_URL=http://127.0.0.1:2026
SANDBOX_SERVICE_TOKEN=fusion-sandbox-dev-token
BACKEND_SANDBOX_SERVICE_TOKEN=fusion-sandbox-dev-token
OPENSANDBOX_DOMAIN=127.0.0.1:8080
OPENSANDBOX_TEMPLATE=sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.2

本地 Docker 部署下，`conf/opensandbox.toml` 中的 `[docker].network_mode` 必须与 OpenSandbox server 所在网络保持一致；当前仓库默认使用 `docker_default`，避免 server proxy 访问 sandbox internal endpoint 时跨网络失败。
OPENSANDBOX_TIMEOUT_SECONDS=600
OPENSANDBOX_PYTHON_VERSION=3.11
```

说明：
- `SANDBOX_SERVICE_TOKEN` 与 `BACKEND_SANDBOX_SERVICE_TOKEN` 必须一致，否则 Agent 调用产品后端内部沙箱接口会返回 `401`
- 当前仓库默认使用阿里云镜像源，避免首次从 Docker Hub 拉取 OpenSandbox 镜像过慢
- OpenSandbox Server 的静态配置文件固定放在 `conf/opensandbox.toml`
- OpenSandbox Server 运行实例统一由 `docker/docker-compose.yml` 管理
- 如果启用了 OpenSandbox Server 的 API Key，需要同时设置 `OPENSANDBOX_API_KEY`

## 推荐维护方式
- 新增配置前，先检查是否已有等价变量。
- 变更配置项时，同步更新 `deployment.md`、`observability.md` 和根 `README.md`。
- 不要把私有主机地址、密码或一次性环境笔记写入当前主文档区。
