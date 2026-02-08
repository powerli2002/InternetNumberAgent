"""子代理相关工具函数。"""

from __future__ import annotations

import json
from typing import Any, Dict


def extract_json(text: str) -> Dict[str, Any]:
    """从模型输出中提取 JSON 对象。"""
    if not text:
        raise ValueError("模型输出为空，无法解析 JSON")
    raw = text.strip()
    # 去除常见代码块包裹
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.replace("json", "", 1).strip()
    # 截取第一个 { 到最后一个 }
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"无法定位 JSON 对象: {text}")
    payload = raw[start : end + 1]
    return json.loads(payload)


def truncate_text(text: str, limit: int) -> str:
    """截断文本，避免上下文过长。"""
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated {len(text)} chars>"
