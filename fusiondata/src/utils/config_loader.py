from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml_config(
    config_path: str | Path, seen: set[Path] | None = None
) -> dict[str, Any]:
    path = Path(config_path).resolve()
    visited = set() if seen is None else seen
    if path in visited:
        raise RuntimeError(f"检测到循环配置继承: {path}")
    visited.add(path)

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"YAML 顶层必须是对象: {path}")

    parent = data.pop("extends", None)
    if not parent:
        return data

    parent_path = (path.parent / str(parent)).resolve()
    base = load_yaml_config(parent_path, visited)
    merged = dict(base)
    merged.update(data)
    return merged
