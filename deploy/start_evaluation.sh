#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -x "$ROOT_DIR/.venv/bin/python" ]; then
  printf '缺少可执行解释器: %s\n' "$ROOT_DIR/.venv/bin/python" >&2
  printf '请先在仓库根目录创建并安装 .venv。\n' >&2
  exit 1
fi

if [ "$#" -eq 0 ]; then
  exec .venv/bin/python -m agent.evaluate.pipelines.run_pipeline --count 30 --workdir agent/evaluate/data --push-langsmith --langsmith-mode writeback
fi

exec .venv/bin/python -m agent.evaluate.pipelines.run_pipeline "$@"
