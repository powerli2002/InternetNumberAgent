"""Python 沙箱工具。

职责分层：
1. 由 Agent 侧 LLM 根据 task/context 生成 Python 代码；
2. 通过 HTTP 调用产品后端内部沙箱接口执行代码；
3. 返回 stdout/stderr/产物摘要给 LangGraph 主流程。

本模块不依赖 backend 包，只依赖公开 HTTP 契约，保持模块边界单向。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

from agent.core.config import AgentConfig
from agent.core.llm import LLMClient, LLMMessage


PYTHON_CODEGEN_PROMPT = """你是 Python 执行助手。你的任务是根据用户 task 编写可直接执行的 Python 3.11 代码。

硬约束：
1) 只输出 Python 代码，不要输出 Markdown、解释或 ``` 代码块；
2) 如需生成图片、CSV、JSON、TXT、PDF 等文件，统一写入 /workspace/artifacts；
3) 如需打印结果，使用 print；
4) 代码必须自包含，可直接作为 main.py 执行；
5) 严禁伪造、补齐、模拟、臆造任何未在 task/context 中提供的数据；禁止使用 sample/mock/fake/demo 数据；
6) 若依赖步骤结果为空或缺失，必须直接 raise RuntimeError，禁止“为了演示”继续画图；
7) 除 Python 标准库外，只能 import packages 中明确声明的第三方库；packages 为空时禁止引用第三方库；
8) 结构化输入元数据会写入 /workspace/input/input.json；若依赖上游查询结果，优先读取该文件中的 datasets 清单，再从对应 CSV/JSON 文件读取真实数据，而不是从自然语言描述中猜测；
9) 如果 task 提到图表且 packages 为空，必须使用标准库直接生成 SVG 图表并写入 /workspace/artifacts；
10) 如果 task 提到图表且 packages 中包含可用绘图库，优先生成 PNG；
11) 禁止访问系统敏感路径，只能使用 /workspace 目录。
12) 图表标题与输出文件名都应优先使用原始统计目标或数据集目标，保持简洁准确；禁止把“读取上一步结果”“保存为 PNG”这类流程性描述直接作为标题或文件名。
"""

CHART_TASK_KEYWORDS = ("画图", "柱状图", "折线图", "饼图", "散点图", "可视化", "plot", "chart", "graph")
FORBIDDEN_DATA_FABRICATION_PATTERNS = (
    "sample_data",
    "mock_data",
    "fake_data",
    "demo_data",
    "示例数据",
    "模拟数据",
    "假设有一些数据",
    "为了演示",
    "for demonstration",
)
FORBIDDEN_UNDECLARED_PLOTTING_IMPORTS = (
    "import matplotlib",
    "from matplotlib",
    "import pandas",
    "from pandas",
    "import numpy",
    "from numpy",
    "import seaborn",
    "from seaborn",
    "import plotly",
    "from plotly",
    "import PIL",
    "from PIL",
)


class PythonSandboxTool:
    """通过产品后端沙箱接口执行 Python。"""

    def __init__(self, config: AgentConfig, llm_client: LLMClient) -> None:
        self.config = config
        self.llm = llm_client

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """剥离模型偶发输出的 Markdown 代码围栏。"""
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-zA-Z0-9_+-]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        return raw.strip()

    @staticmethod
    def _is_chart_task(task: str) -> bool:
        """判断当前任务是否属于绘图任务。"""
        text = str(task or "").lower()
        return any(keyword.lower() in text for keyword in CHART_TASK_KEYWORDS)

    def _validate_generated_code(
        self,
        *,
        task: str,
        packages: Optional[List[str]],
        code: str,
    ) -> None:
        """对模型生成的代码做硬约束校验，防止伪造数据和不可执行依赖。"""
        lowered = str(code or "").lower()
        for pattern in FORBIDDEN_DATA_FABRICATION_PATTERNS:
            if pattern.lower() in lowered:
                raise RuntimeError("Python 代码生成失败：禁止使用伪造或演示数据。")

        if not self._is_chart_task(task):
            return

        if "/workspace/artifacts/" not in code:
            raise RuntimeError("Python 代码生成失败：绘图任务必须将产物写入 /workspace/artifacts。")

        normalized_packages = {
            str(item).strip().lower() for item in (packages or []) if str(item).strip()
        }
        if normalized_packages:
            return

        for pattern in FORBIDDEN_UNDECLARED_PLOTTING_IMPORTS:
            if pattern.lower() in lowered:
                raise RuntimeError(
                    "Python 代码生成失败：当前未声明绘图库，绘图任务必须使用标准库生成 SVG。"
                )

        if ".svg" not in lowered:
            raise RuntimeError(
                "Python 代码生成失败：当前未声明绘图库，绘图任务必须输出 SVG 产物。"
            )

    def _extract_chart_dataset(self, input_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从结构化输入元数据中判断是否存在可绘图的数据集。"""
        datasets = input_data.get("datasets") if isinstance(input_data, dict) else []
        if not isinstance(datasets, list):
            return []
        best_rows: List[Dict[str, Any]] = []
        for dataset in datasets:
            if not isinstance(dataset, dict):
                continue
            columns = dataset.get("columns")
            preview_rows = dataset.get("preview_rows")
            if (
                not dataset.get("chart_candidate")
                or not isinstance(columns, list)
                or len(columns) < 2
                or not isinstance(preview_rows, list)
            ):
                continue
            normalized_rows: List[Dict[str, Any]] = []
            for row in preview_rows:
                if not isinstance(row, list) or len(row) < 2:
                    continue
                value = row[1]
                if not isinstance(value, (int, float)):
                    continue
                normalized_rows.append(
                    {
                        "label": str(row[0]),
                        "value": float(value),
                    }
                )
            if len(normalized_rows) > len(best_rows):
                best_rows = normalized_rows
        return best_rows

    def _build_stdlib_svg_chart_code(
        self, task: str, input_data: Optional[Dict[str, Any]]
    ) -> str:
        """为无第三方依赖的绘图任务生成标准库 SVG 代码。"""
        payload_data = input_data if isinstance(input_data, dict) else {}
        if not self._extract_chart_dataset(payload_data):
            raise RuntimeError("Python 代码生成失败：绘图依赖的数据为空，无法生成图表。")
        return f"""from pathlib import Path
import csv
import json
import re

# 使用结构化输入文件和 CSV 数据集生成 SVG 柱状图。
input_payload = json.loads(Path("/workspace/input/input.json").read_text(encoding="utf-8"))
task_text = {str(task or "").strip() or "图表"!r}
subtitle = "数据来源：依赖步骤查询结果"
datasets = input_payload.get("datasets") or []
chart_dataset = None
for dataset in datasets:
    if not isinstance(dataset, dict):
        continue
    columns = dataset.get("columns") or []
    if dataset.get("chart_candidate") and isinstance(columns, list) and len(columns) >= 2:
        chart_dataset = dataset
        break
if chart_dataset is None:
    raise RuntimeError("未找到可用于绘图的数据集。")

csv_path = chart_dataset.get("file_path")
columns = chart_dataset.get("columns") or []
if not csv_path or len(columns) < 2:
    raise RuntimeError("绘图数据集缺少文件路径或列定义。")

title_source = str(chart_dataset.get("source_objective") or "").strip() or task_text
for token in ("（分组结果用于绘图）", "生成柱状图展示统计结果", "读取上一步的统计结果，", "保存为 PNG 文件", "保存为 SVG 文件"):
    title_source = title_source.replace(token, "")
title_source = title_source.replace("，", ",")
title_source = re.sub(
    r"(,|\\s)*(请)?(画|绘制|生成)(一个)?(柱状图|折线图|饼图|散点图|图表|可视化)(展示)?(统计结果)?",
    "",
    title_source,
    flags=re.IGNORECASE,
)
title_source = re.sub(r"\\bas\\b", "AS", title_source, flags=re.IGNORECASE)
title_source = re.sub(r"\\bipv4\\b", "IPv4", title_source, flags=re.IGNORECASE)
title_source = re.sub(r"\\bipv6\\b", "IPv6", title_source, flags=re.IGNORECASE)
title_source = re.sub(r"\\s+", " ", title_source).strip(" ，,。")
title = title_source or "统计图表"

label_column = str(columns[0])
value_column = str(columns[1])
data = []
with Path(str(csv_path)).open("r", encoding="utf-8", newline="") as csv_file:
    reader = csv.DictReader(csv_file)
    for row in reader:
        raw_value = row.get(value_column)
        if raw_value in (None, ""):
            continue
        try:
            value = float(raw_value)
        except ValueError:
            continue
        data.append({{"label": str(row.get(label_column, "")), "value": value}})
if not data:
    raise RuntimeError("绘图所需数据为空，无法生成图表。")
data = sorted(data, key=lambda item: item["value"], reverse=True)[:20]

chart_height = 420
chart_width = 1280
margin_left = 72
margin_right = 32
margin_top = 72
margin_bottom = 108
plot_width = chart_width - margin_left - margin_right
plot_height = chart_height - margin_top - margin_bottom
bar_gap = 12
bar_width = max(18, int((plot_width - bar_gap * (len(data) - 1)) / max(len(data), 1)))
max_value = max(float(item["value"]) for item in data)
if max_value <= 0:
    raise RuntimeError("绘图数据全部为 0，无法生成有效柱状图。")

def _escape_xml(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{{chart_width}}" height="{{chart_height}}" viewBox="0 0 {{chart_width}} {{chart_height}}">',
    '<rect width="100%" height="100%" fill="#fffdf8" />',
    f'<text x="{{margin_left}}" y="34" font-size="26" font-weight="700" fill="#1f2933">{{_escape_xml(title)}}</text>',
]
if subtitle:
    parts.append(
        f'<text x="{{margin_left}}" y="58" font-size="13" fill="#6b7683">{{_escape_xml(subtitle)}}</text>'
    )

for tick in range(5):
    value = max_value * tick / 4
    y = margin_top + plot_height - plot_height * tick / 4
    parts.append(
        f'<line x1="{{margin_left}}" y1="{{y:.1f}}" x2="{{chart_width - margin_right}}" y2="{{y:.1f}}" stroke="#d7dde4" stroke-dasharray="4 6" />'
    )
    parts.append(
        f'<text x="{{margin_left - 10}}" y="{{y + 4:.1f}}" text-anchor="end" font-size="12" fill="#6b7683">{{int(value)}}</text>'
    )

for index, item in enumerate(data):
    label = _escape_xml(str(item["label"]))
    value = float(item["value"])
    x = margin_left + index * (bar_width + bar_gap)
    bar_height = plot_height * value / max_value
    y = margin_top + plot_height - bar_height
    parts.append(
        f'<rect x="{{x:.1f}}" y="{{y:.1f}}" width="{{bar_width}}" height="{{bar_height:.1f}}" rx="8" fill="#0f766e" />'
    )
    parts.append(
        f'<text x="{{x + bar_width / 2:.1f}}" y="{{y - 8:.1f}}" text-anchor="middle" font-size="11" fill="#1f2933">{{int(value) if value.is_integer() else round(value, 2)}}</text>'
    )
    parts.append(
        f'<text x="{{x + bar_width / 2:.1f}}" y="{{margin_top + plot_height + 18:.1f}}" text-anchor="end" transform="rotate(-35 {{x + bar_width / 2:.1f}} {{margin_top + plot_height + 18:.1f}})" font-size="11" fill="#334155">{{label}}</text>'
    )

parts.append(
    f'<line x1="{{margin_left}}" y1="{{margin_top + plot_height}}" x2="{{chart_width - margin_right}}" y2="{{margin_top + plot_height}}" stroke="#6b7683" stroke-width="1.2" />'
)
parts.append(
    f'<line x1="{{margin_left}}" y1="{{margin_top}}" x2="{{margin_left}}" y2="{{margin_top + plot_height}}" stroke="#6b7683" stroke-width="1.2" />'
)
parts.append("</svg>")

output_path = Path("/workspace/artifacts/chart.svg")
output_path.write_text("".join(parts), encoding="utf-8")
print(f"图表已保存为 {{output_path}}")
"""

    def generate_code(
        self,
        task: str,
        *,
        context: str = "",
        input_data: Optional[Dict[str, Any]] = None,
        input_files: Optional[List[Dict[str, Any]]] = None,
        packages: Optional[List[str]] = None,
    ) -> str:
        """使用当前主模型生成 Python 代码。"""
        package_list = [str(item).strip() for item in (packages or []) if str(item).strip()]
        if self._is_chart_task(task) and not package_list:
            return self._build_stdlib_svg_chart_code(task, input_data)
        payload = {
            "task": str(task or "").strip(),
            "context": str(context or "").strip(),
            "input_data": input_data if isinstance(input_data, dict) else {},
            "input_files": input_files if isinstance(input_files, list) else [],
            "packages": package_list,
            "input_path": "/workspace/input/input.json",
        }
        messages = [
            LLMMessage(role="system", content=PYTHON_CODEGEN_PROMPT),
            LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ]
        code = self.llm.chat(messages, temperature=0.0)
        cleaned = self._strip_code_fence(code)
        if not cleaned:
            raise RuntimeError("Python 代码生成失败：模型返回为空。")
        self._validate_generated_code(
            task=task,
            packages=package_list,
            code=cleaned,
        )
        return cleaned

    def execute(
        self,
        task: str,
        *,
        context: str = "",
        input_data: Optional[Dict[str, Any]] = None,
        input_files: Optional[List[Dict[str, Any]]] = None,
        packages: Optional[List[str]] = None,
        timeout_seconds: Optional[int] = None,
        trace_id: str = "",
        thread_id: str = "",
        run_id: str = "",
    ) -> Dict[str, Any]:
        """生成代码并调用后端内部沙箱接口执行。"""
        code = self.generate_code(
            task,
            context=context,
            input_data=input_data,
            input_files=input_files,
            packages=packages,
        )
        api_url = self.config.sandbox_api_url.rstrip("/")
        if not api_url:
            raise RuntimeError("缺少 SANDBOX_API_URL，无法调用产品后端沙箱服务。")
        payload = {
            "task": str(task or "").strip(),
            "context": str(context or "").strip(),
            "input_data": input_data if isinstance(input_data, dict) else {},
            "input_files": input_files if isinstance(input_files, list) else [],
            "packages": [str(item).strip() for item in (packages or []) if str(item).strip()],
            "timeout_seconds": int(timeout_seconds or self.config.sandbox_timeout_seconds),
            "trace_id": str(trace_id or ""),
            "thread_id": str(thread_id or ""),
            "run_id": str(run_id or ""),
            "code": code,
        }
        headers: Dict[str, str] = {}
        if self.config.sandbox_service_token:
            headers["X-Service-Token"] = self.config.sandbox_service_token
        response = httpx.post(
            f"{api_url}/internal/sandbox/python",
            json=payload,
            headers=headers or None,
            timeout=max(5, int(timeout_seconds or self.config.sandbox_timeout_seconds)),
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError("产品后端沙箱接口返回了无效响应。")
        result["code"] = code
        return result
