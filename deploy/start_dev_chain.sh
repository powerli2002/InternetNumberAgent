#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs/deploy"

if [ ! -x "$ROOT_DIR/.venv/bin/python" ]; then
  printf '缺少可执行解释器: %s\n' "$ROOT_DIR/.venv/bin/python" >&2
  printf '请先在仓库根目录创建并安装 .venv。\n' >&2
  exit 1
fi

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

start_python_process() {
  local name="$1"
  local pattern="$2"
  shift 2

  if pgrep -f "$pattern" >/dev/null 2>&1; then
    printf '%s 已在运行，跳过。\n' "$name"
    return
  fi

  nohup "$ROOT_DIR/.venv/bin/python" "$@" >"$LOG_DIR/$name.log" 2>&1 &
  printf '%s 已启动 pid=%s log=%s\n' "$name" "$!" "$LOG_DIR/$name.log"
}

start_python_process mcp 'agent.services.mcp.server:app' -m uvicorn agent.services.mcp.server:app --host 0.0.0.0 --port 2032
start_python_process langgraph_dev 'agent.scripts.langgraph_dev --config langgraph.json --port 8123 --no-reload' -m agent.scripts.langgraph_dev --config langgraph.json --port 8123 --no-reload "$@"
