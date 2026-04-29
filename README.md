# 互联网号码资源问答系统（fusionprocessing）

本仓库是“互联网号码资源问答系统”的融合处理、智能体与产品化实现，负责把 RIR/WHOIS/RDAP、BGP、DNS/网站等多源数据清洗为结构化事实，并通过 `FusionAgent` 与产品服务提供带证据的问答能力。

当前实现以 **PostgreSQL 16 张核心表** 为事实源，配套 **Milvus 文档向量索引** 与 **Neo4j 图谱/关系查询**。在线链路采用 **LangGraph + FastMCP**，不再使用历史 A2A/子代理方案。

## 快速入口
- 文档总入口：`docs/README.md`
- 系统功能总览：`docs/01-overview/system-overview.md`
- 当前架构：`docs/02-architecture/overall-architecture.md`
- 数据模型：`docs/03-data/core-schema.md`
- 部署与运行：`docs/04-operations/deployment.md`
- 配置说明：`docs/04-operations/configuration.md`
- 评测流水线：`docs/04-operations/evaluation.md`
- AI 协作规则：`docs/05-ai/repo-guide.md`

## 目录
- `fusiondata/`：离线融合处理流水线。
- `agent/runtime/`：FusionAgent、LangGraph 编排、上下文构建。
- `agent/services/http/`：Agent 调试/兼容 HTTP API。
- `agent/services/mcp/`：FastMCP 服务与客户端。
- `agent/tools/`：NL2SQL、RAG、Neo4j、Note、Todo 等工具。
- `backend/`：认证、线程、过程事件、artifact、OpenSandbox 接入。
- `deploy/`：本地启动脚本入口，统一管理 MCP、后端、前端、LangGraph 调试与评测命令。
- `webapp/`：正式产品前端。
- `agent/scripts/`：导入、建索引、评测与排障脚本。
- `conf/`：配置与 `.env`。
- `docs/`：当前权威文档与历史归档。

## 常用命令

执行 `deploy/` 下脚本前，请先满足两个前置条件：
- 仓库根目录已创建并安装 `.venv/`。
- 前端相关脚本所在环境已安装 `pnpm`。

当前 `deploy/` 只保留三条启动链路：
- `./deploy/start_dev_chain.sh`：启动开发链路（MCP + LangGraph 调试）。
- `./deploy/start_ui_chain.sh`：启动用户界面链路（MCP + Backend + Agent API + WebApp）。
- `./deploy/start_evaluation.sh`：启动默认评测链路。

### 数据与服务

```bash
# 导入 16 张核心表
python -m agent.scripts.load_all_csv --config conf/config.docker.yaml --root . --ensure-core

# 启动用户界面链路
./deploy/start_ui_chain.sh

# 启动 OpenSandbox
./backend/scripts/start_opensandbox.sh

# 构建文档向量索引
python agent/knowledge_ingest.py --root . --path agent/knowledge --reset

# 构建 Neo4j 图谱
python -m agent.scripts.neo4j_graph_loader --batch-size 1000
```

### 本地调试

```bash
# 启动 CLI
python agent/cli/main.py

# 启动开发链路
./deploy/start_dev_chain.sh

# OpenSandbox 最小联调
.venv/bin/python backend/scripts/opensandbox_smoke_test.py
```

OpenSandbox 由 `docker/docker-compose.yml` 管理，服务端配置固定放在 `conf/opensandbox.toml`。

### 本地 LLM

```bash
# 清理旧的 vLLM 进程
kill $(lsof -ti tcp:2222)
pkill -f "VLLM::EngineCore"

# 启动本地 vLLM
python agent/model/start_vllm.py
```

### 评测

```bash
# 评测入口会自动读取 conf/.env；若未激活虚拟环境，直接使用 .venv/bin/python

# 一键运行评测并写回 LangSmith
./deploy/start_evaluation.sh

# 分步生成题目
.venv/bin/python -m agent.evaluate.pipelines.generate_queries --count 30 --out agent/evaluate/data/queries.jsonl

# 构建评分 rubric
.venv/bin/python -m agent.evaluate.pipelines.build_graders --out agent/evaluate/data/rubrics.json

# 生成 answers
.venv/bin/python -m agent.evaluate.pipelines.fill_answers --in agent/evaluate/data/queries.jsonl --out agent/evaluate/data/answers.jsonl

# 执行评分
.venv/bin/python -m agent.evaluate.pipelines.score_pipeline --in agent/evaluate/data/answers.jsonl --rubrics agent/evaluate/data/rubrics.json --out agent/evaluate/data/scored.jsonl --summary-out agent/evaluate/data/score_summary.json --manual-review-out agent/evaluate/data/manual_review.csv --push-langsmith --langsmith-mode writeback
```

### 绘图模型评测

```bash
cd /home/lzj/fusionprocessing/TrainModel/VisCoder/eval/PandasPlotBench && \
PLOT_BENCH_CODEBERT_DEVICE=cuda:2 \
/home/lzj/fusionprocessing/.venv/bin/python run_eval_and_upload_langsmith.py \
  --full \
  --cuda=1 \
  --mode=generate \
  --dataset-name=qwen3.5-plot-baseline \
  --experiment-name=qwen3.5-plot-baseline \
  --config=configs/config_normal_baseline.yaml \
  --model=openai/QuantTrio/Qwen3.5-4B-AWQ

# 自动选择最新 LoRA checkpoint，合并后在 cuda:2 部署，并在 cuda:3 执行评测
cd /home/lzj/fusionprocessing/TrainModel/VisCoder/eval/PandasPlotBench && \
bash run_latest_checkpoint_eval.sh --full

# 自动选择最新 LoRA checkpoint，先 merge，再使用 llmcompressor 导出 AWQ 模型
bash /home/lzj/fusionprocessing/TrainModel/VisCoder/train/export_latest_checkpoint_awq.sh

# 如需覆盖上下文/显存/输出 token，可显式指定；2080 Ti 11GB 单卡默认建议 2048 context + 0.85 utilization + 1024 output tokens
cd /home/lzj/fusionprocessing/TrainModel/VisCoder/eval/PandasPlotBench && \
MAX_MODEL_LEN=2048 GPU_MEMORY_UTILIZATION=0.85 PLOT_BENCH_MAX_TOKENS=1024 bash run_latest_checkpoint_eval.sh --full

# --skip-eval 只评测+上传
PLOT_BENCH_CODEBERT_DEVICE=cuda:2 \
/home/lzj/fusionprocessing/.venv/bin/python run_eval_and_upload_langsmith.py \
  --full \
  --skip-eval \
  --cuda=2 \
  --mode=generate \
  --dataset-name=qwen3.5-plot-baseline \
  --experiment-name=qwen3.5-plot-baseline \
  --config=configs/config_normal_baseline.yaml \
  --model=openai/QuantTrio/Qwen3.5-4B-AWQ
```

### 绘图模型 LoRA 训练

```bash
CUDA_VISIBLE_DEVICES=1 /home/lzj/fusionprocessing/TrainModel/VisCoder/.venv-lora-uv/bin/python \
  /home/lzj/fusionprocessing/TrainModel/VisCoder/train/qwen35_lora_sft.py \
  --sample_size 200000 \
  --run_name qwen35-lora-100 \
  --wandb_mode offline


# 离线
CUDA_VISIBLE_DEVICES=1 /home/lzj/fusionprocessing/TrainModel/VisCoder/.venv-lora-uv/bin/python \
  /home/lzj/fusionprocessing/TrainModel/VisCoder/train/qwen35_lora_sft.py \
  --sample_size 200000 \
  --run_name qwen35-lora-100 \
  --wandb_mode offline


```

断点续训：

```bash
LATEST_CKPT=$(ls -dt /home/lzj/fusionprocessing/TrainModel/VisCoder/train/output/qwen35_lora_run/checkpoint-* | head -n 1)
CUDA_VISIBLE_DEVICES=1 /home/lzj/fusionprocessing/TrainModel/VisCoder/.venv-lora-uv/bin/python \
  /home/lzj/fusionprocessing/TrainModel/VisCoder/train/qwen35_lora_sft.py \
  --resume_from_checkpoint "$LATEST_CKPT" \
  --run_name qwen35-lora-resume \
  --wandb_mode offline
```



## 核心原则
- PostgreSQL 是事实源，Milvus 与 Neo4j 可从结构化数据重建。
- 默认只维护 16 张核心实体表，不引入额外审计表或原始镜像表。
- 回答要带证据，优先给出 SQL 结果、文档片段或图谱关系。
- 文档保持单一权威入口，历史文档统一放到 `docs/90-archive/`。

## 兼容入口
- `AGENTS.md`：AI/Harness 入口规范。
- `summary.md`：兼容性入口，当前数据模型以 `docs/03-data/core-schema.md` 为准。
