#!/usr/bin/env bash
set -euo pipefail

IMAGES=(
  "sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.2|opensandbox/code-interpreter:v1.0.2"
  "sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/execd:v1.0.7|opensandbox/execd:v1.0.7"
  "sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/egress:v1.0.3|opensandbox/egress:v1.0.3"
)

for item in "${IMAGES[@]}"; do
  src="${item%%|*}"
  dst="${item##*|}"
  docker pull "$src"
  docker tag "$src" "$dst"
done
