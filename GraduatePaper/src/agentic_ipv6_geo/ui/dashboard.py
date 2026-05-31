from __future__ import annotations

import csv
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
from typing import Any

from agentic_ipv6_geo.cli import load_config
from agentic_ipv6_geo.common.catalog import display_experiment_name, display_tool_name
from agentic_ipv6_geo.common.geo import Point, haversine_km
from agentic_ipv6_geo.common.logger import JsonlLogger
from agentic_ipv6_geo.common.models import Target
from agentic_ipv6_geo.data.repository import DataRepository
from agentic_ipv6_geo.data.trustgeo_adapter import TrustGeoAdapter
from agentic_ipv6_geo.data.validator import DataValidator, write_validation_report
from agentic_ipv6_geo.evaluation import Evaluator
from agentic_ipv6_geo.scheduler import ContextualBanditScheduler, RuleAgentScheduler
from agentic_ipv6_geo.tools.registry import METHOD_SPECS, build_methods


def main() -> None:
    import argparse
    import pandas as pd
    import streamlit as st

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", default="configs/trustgeo.json")
    args, _unknown = parser.parse_known_args()

    st.set_page_config(page_title="Agentic IPv6 Geo", layout="wide")
    _inject_style(st)
    st.title("Agentic IPv6 地理位置推断系统")
    st.caption("面向毕业论文实验的 Agent 调度、主动三角定位与证据融合可视化控制台")

    with st.sidebar:
        st.header("运行配置")
        config_path = st.text_input("配置文件", value=args.config)
        output_dir = st.text_input("输出目录", value="outputs/trustgeo")
        trustgeo_root = st.text_input("TrustGeo 根目录", value="/home/lzj/TrustGeo")
        allow_live_ui = st.checkbox("允许 UI 发起真实主动探测", value=False)
        st.caption("按钮会在当前 GraduatePaper 目录内生成数据、日志、指标和预测结果。")
        if not allow_live_ui:
            st.caption("默认仅使用已有 trace，避免打开页面或训练 Bandit 时消耗 scamper/RIPE Atlas 预算。")

        if st.button("适配 TrustGeo 数据", width="stretch"):
            with st.spinner("正在读取 TrustGeo 数据并生成统一 CSV..."):
                cfg = load_config(config_path)
                summary = TrustGeoAdapter(trustgeo_root, cfg.get("data_dir", "data/trustgeo_processed")).run()
            st.success("TrustGeo 数据适配完成")
            _render_key_value_grid(st, _summary_items(summary))

        if st.button("校验数据", width="stretch"):
            cfg = load_config(config_path)
            repo = DataRepository(cfg.get("data_dir", "data/trustgeo_processed"))
            report = DataValidator(repo).validate()
            write_validation_report(Path(output_dir) / "metrics/data_validation.json", report)
            st.success("数据校验完成")
            _render_validation_cards(st, report)

    config = _safe_load_config(config_path)
    if not config:
        st.error("配置文件不可读取，请检查路径。")
        return

    repo = _load_repo(config.get("data_dir", "data/trustgeo_processed"))
    if not repo.targets:
        st.warning("当前数据目录没有目标样本。请先点击侧边栏中的“适配 TrustGeo 数据”。")
        return

    runtime = {"config": config, "repo": repo, "allow_live_ui": allow_live_ui}

    overview_tab, capability_tab, locate_tab, eval_tab, data_tab = st.tabs(["总览", "系统能力", "自动定位", "训练与评测", "数据与输出"])
    with overview_tab:
        _render_overview(st, repo, output_dir, runtime["config"])
    with capability_tab:
        _render_system_capabilities(st, pd, runtime, output_dir)
    with locate_tab:
        _render_locator(st, pd, runtime, config_path, json.dumps(config, sort_keys=True))
    with eval_tab:
        _render_evaluation(st, config, output_dir)
    with data_tab:
        _render_data_outputs(st, pd, repo, output_dir)


def _safe_load_config(config_path: str) -> dict[str, Any] | None:
    try:
        return load_config(config_path)
    except Exception:
        return None


def _load_repo(data_dir: str) -> DataRepository:
    return DataRepository(data_dir)


def _build_locator_runtime(config_path: str, config_fingerprint: str, allow_live_measurements: bool) -> dict[str, Any]:
    import streamlit as st

    @st.cache_resource(show_spinner="正在加载工具与训练调度策略...")
    def _cached(_config_path: str, _fingerprint: str, _allow_live_measurements: bool) -> dict[str, Any]:
        config = _dashboard_config(load_config(_config_path), _allow_live_measurements)
        bandit_config = _dashboard_config(load_config(_config_path), False)
        repo = DataRepository(config.get("data_dir", "data/trustgeo_processed"))
        train_targets, test_targets = repo.split_targets(
            test_ratio=float(config.get("split", {}).get("test_ratio", 0.35)),
            seed=int(config.get("split", {}).get("seed", 42)),
        )

        methods = build_methods(repo, config, train_targets)
        bandit_methods = build_methods(repo, bandit_config, train_targets)
        modugeo = methods["modugeo"]
        active = methods["active_triangulation"]
        rdns = methods["rdns"]
        whois = methods["whois"]
        fusion = methods["fusion"]
        logger = JsonlLogger(config.get("log_path"))

        rule = RuleAgentScheduler(modugeo, rdns, active, whois, methods.get("passive_ipdb"), fusion, config.get("scheduler"), logger)
        bandit = ContextualBanditScheduler(
            bandit_methods["modugeo"],
            bandit_methods["rdns"],
            bandit_methods["active_triangulation"],
            bandit_methods["whois"],
            bandit_methods["fusion"],
            bandit_config.get("bandit"),
            logger,
        )
        bandit.fit(train_targets[: int(config.get("ui", {}).get("bandit_train_limit", 96))])
        return {
            "config": config,
            "repo": repo,
            "train_targets": train_targets,
            "test_targets": test_targets,
            "tools": methods,
            "schedulers": {
                "规则调度": rule,
                "Bandit 调度": bandit,
            },
        }

    return _cached(config_path, config_fingerprint, allow_live_measurements)


def _dashboard_config(config: dict[str, Any], allow_live_measurements: bool) -> dict[str, Any]:
    cfg = copy.deepcopy(config)
    if allow_live_measurements:
        return cfg
    active_cfg = cfg.setdefault("active_probe", {})
    active_cfg["allow_live_measurements"] = False
    active_cfg["provider_order"] = ["existing_trace"]
    return cfg


def _render_overview(st, repo: DataRepository, output_dir: str, config: dict[str, Any]) -> None:
    import pandas as pd

    report = DataValidator(repo).validate()
    cols = st.columns(7)
    labels = [
        ("目标", "target_count"),
        ("Trace Hop", "trace_hop_count"),
        ("探针", "probe_count"),
        ("Metadata", "metadata_count"),
        ("rDNS", "rdns_count"),
        ("Landmark", "landmark_count"),
        ("ModuGeo 预测", "modugeo_prediction_count"),
    ]
    for col, (label, key) in zip(cols, labels):
        col.metric(label, report[key])

    st.subheader("整体数据覆盖")
    left, right = st.columns([1.15, 1])
    with left:
        count_rows = [
            {"类别": "目标", "数量": report["target_count"]},
            {"类别": "Trace Hop", "数量": report["trace_hop_count"]},
            {"类别": "探针", "数量": report["probe_count"]},
            {"类别": "Metadata", "数量": report["metadata_count"]},
            {"类别": "rDNS", "数量": report["rdns_count"]},
            {"类别": "Landmark", "数量": report["landmark_count"]},
            {"类别": "ModuGeo 预测", "数量": report["modugeo_prediction_count"]},
        ]
        _altair_horizontal_bar(st, pd.DataFrame(count_rows), x="数量", y="类别", title="统一输入数据规模", color="#2563eb")
    with right:
        coverage_rows = [
            {"覆盖项": "Trace 覆盖", "覆盖率": _ratio(report["target_count"] - report["missing_trace_target_count"], report["target_count"])},
            {"覆盖项": "ModuGeo 预测", "覆盖率": _ratio(report["target_count"] - report["missing_modugeo_prediction_count"], report["target_count"])},
            {"覆盖项": "rDNS 覆盖", "覆盖率": _ratio(report["target_count"] - report["missing_rdns_target_count"], report["target_count"])},
            {"覆盖项": "有效目标", "覆盖率": 1.0 if report["is_valid_for_evaluation"] else 0.0},
        ]
        _altair_horizontal_bar(st, pd.DataFrame(coverage_rows), x="覆盖率", y="覆盖项", title="关键输入覆盖率", color="#16a34a", x_format="%")

    st.subheader("数据健康状态")
    _render_validation_cards(st, report)
    _render_pipeline_summary(st, config)
    _render_trustgeo_adapter_note(st)
    _render_method_catalog(st)

    summary_path = Path(output_dir) / "metrics/summary.json"
    if summary_path.exists():
        st.subheader("最近一次评测摘要")
        with summary_path.open("r", encoding="utf-8") as fh:
            metrics = json.load(fh)
        metric_rows = _metrics_rows(metrics)
        st.dataframe(metric_rows, width="stretch", hide_index=True)
        chart_left, chart_right = st.columns(2)
        with chart_left:
            st.caption("误差对比：Mean 越低越好")
            _altair_horizontal_bar(
                st,
                pd.DataFrame(metric_rows),
                x="Mean",
                y="实验",
                title="平均误差排名（越低越好）",
                color="#7c3aed",
            )
        with chart_right:
            st.caption("成本对比：工具调用与探针成本")
            cost_rows = []
            for row in metric_rows:
                cost_rows.append({"实验": row["实验"], "成本类型": "工具调用", "值": row["AvgToolCalls"] or 0})
                cost_rows.append({"实验": row["实验"], "成本类型": "探针成本", "值": row["AvgProbeCost"] or 0})
            _altair_grouped_bar(st, pd.DataFrame(cost_rows), x="值", y="实验", color="成本类型", title="工具调用与探针成本")


def _render_locator(st, pd, runtime: dict[str, Any], config_path: str, config_fingerprint: str) -> None:
    repo: DataRepository = runtime["repo"]
    target_by_ip = {target.ip: target for target in repo.targets}

    st.subheader("单样本自动定位")
    left, right = st.columns([2, 1])
    with left:
        default_ip = repo.targets[0].ip
        selected_ip = st.selectbox("选择目标 IPv6", options=list(target_by_ip), index=0)
        custom_ip = st.text_input("或输入 IPv6", value=selected_ip or default_ip)
    with right:
        scheduler_name = st.radio("自动选择策略", ["规则调度", "Bandit 调度"], horizontal=False)
        show_manual_tools = st.checkbox("同时展示所有单工具输出", value=True)
        st.caption("Bandit 训练在 UI 中固定使用已有 trace，不会发起真实主动探测。")

    target = target_by_ip.get(custom_ip.strip())
    if not target:
        st.warning("该 IP 不在当前目标表中。界面当前用于实验样本调试，请选择已加载目标。")
        return

    if st.button("开始自动定位", type="primary", width="stretch"):
        locator_runtime = _build_locator_runtime(config_path, config_fingerprint, bool(runtime.get("allow_live_ui")))
        tools = locator_runtime["tools"]
        schedulers = locator_runtime["schedulers"]
        scheduler = schedulers[scheduler_name]
        result = scheduler.run(target)
        st.session_state["last_locate"] = {
            "target": target,
            "scheduler_name": scheduler_name,
            "result": result.to_dict(),
            "manual": _run_manual_tools(target, tools) if show_manual_tools else [],
        }

    payload = st.session_state.get("last_locate")
    if not payload:
        st.info("点击按钮后，系统会自动选择定位算法并输出置信度、坐标和证据链。")
        return

    result = payload["result"]
    _render_result_summary(st, pd, payload["target"], result, payload["scheduler_name"])
    if payload["manual"]:
        st.subheader("单工具输出对比")
        st.dataframe(_result_rows(payload["manual"]), width="stretch", hide_index=True)
        _render_tool_evidence_sections(st, payload["manual"])


def _run_manual_tools(target: Target, tools: dict[str, Any]) -> list[dict[str, Any]]:
    results = [
        tools["modugeo"].run(target),
        tools["rdns"].run(target),
        tools["active_triangulation"].run(target),
        tools["passive_ipdb"].run(target),
        tools["whois"].run(target),
    ]
    fused = tools["fusion"].run(results)
    results.append(fused)
    return [item.to_dict() for item in results]


def _render_system_capabilities(st, pd, runtime: dict[str, Any], output_dir: str) -> None:
    config = runtime["config"]
    repo: DataRepository = runtime["repo"]
    st.subheader("系统能力总览")
    st.write("这一页用于判断当前系统是否已经具备“可展示、可调试、可被 Agent/MCP 调用”的条件。")

    status_rows = _capability_rows(config, repo, output_dir)
    ok_count = sum(1 for row in status_rows if row["状态"] == "可用")
    warn_count = sum(1 for row in status_rows if row["状态"] == "受限")
    unavailable_count = sum(1 for row in status_rows if row["状态"] == "不可用")
    _render_key_value_grid(
        st,
        [
            ("能力项", len(status_rows)),
            ("可用", ok_count),
            ("受限", warn_count),
            ("不可用", unavailable_count),
            ("MCP 入口", "ipv6geo-mcp"),
            ("输出目录", output_dir),
        ],
    )

    st.markdown("### 工具与依赖状态")
    st.dataframe(status_rows, width="stretch", hide_index=True)
    _altair_status_bar(st, pd.DataFrame(status_rows))

    st.markdown("### Agent 调度链路")
    _render_agent_flow(st)

    st.markdown("### MCP 可调用工具")
    mcp_tools = [
        {"MCP 工具": "health", "用途": "检查服务、配置、数据样本和 warning"},
        {"MCP 工具": "list_geo_tools", "用途": "列出 ModuGeo/rDNS/主动三角/被动 IPDB/WHOIS-BGP"},
        {"MCP 工具": "run_geo_tool", "用途": "对单个 IP 运行指定工具或 fusion/scheduler_rule"},
        {"MCP 工具": "geolocate_ip", "用途": "使用规则 Agent 调度器完成单 IP 定位"},
        {"MCP 工具": "debug_geo_tools", "用途": "一次性运行全部工具并返回证据与失败原因"},
        {"MCP 工具": "collect_scamper_constraints", "用途": "读取或触发 scampertrace，返回 CBG RTT 约束"},
    ]
    st.dataframe(mcp_tools, width="stretch", hide_index=True)

    st.markdown("### 外部阻塞项")
    blockers = [row for row in status_rows if row["状态"] != "可用"]
    if blockers:
        for item in blockers:
            st.warning(f"{item['能力']}：{item['说明']}。建议：{item['建议']}")
    else:
        st.success("所有关键能力均可用。")


def _render_result_summary(st, pd, target: Target, result: dict[str, Any], scheduler_name: str) -> None:
    location = result.get("location") or {}
    truth_lat = target.location.lat
    truth_lon = target.location.lon
    pred_lat = location.get("lat")
    pred_lon = location.get("lon")
    error = None
    if truth_lat is not None and truth_lon is not None and pred_lat is not None and pred_lon is not None:
        error = haversine_km(Point(truth_lat, truth_lon), Point(pred_lat, pred_lon))

    cols = st.columns(5)
    cols[0].metric("调度策略", scheduler_name)
    cols[1].metric("状态", result.get("status"))
    cols[2].metric("置信度", f"{float(result.get('confidence', 0.0)):.3f}")
    cols[3].metric("误差 km", "" if error is None else f"{error:.3f}")
    cols[4].metric("探针成本", result.get("cost", {}).get("probe_count", 0))

    st.subheader("定位结果")
    _render_location_result(
        st,
        target_ip=target.ip,
        truth=target.location,
        prediction=location,
        granularity=result.get("granularity"),
        failure_reason=result.get("failure_reason"),
    )

    map_rows = []
    if truth_lat is not None and truth_lon is not None:
        map_rows.append({"lat": truth_lat, "lon": truth_lon, "kind": "truth"})
    if pred_lat is not None and pred_lon is not None:
        map_rows.append({"lat": pred_lat, "lon": pred_lon, "kind": "prediction"})
    if map_rows:
        st.map(pd.DataFrame(map_rows), latitude="lat", longitude="lon")

    scheduler_evidence = (result.get("evidence") or {}).get("scheduler") or {}
    decisions = scheduler_evidence.get("decisions")
    if decisions:
        st.subheader("自动选择过程")
        _render_trace_flow(st, decisions)
    elif scheduler_evidence:
        st.subheader("自动选择过程")
        _render_bandit_decision(st, scheduler_evidence)

    used_tools = (result.get("evidence") or {}).get("used_tools")
    if used_tools:
        st.info("最终融合使用工具：" + "、".join(display_tool_name(item) for item in used_tools))

    with st.expander("最终结果证据摘要"):
        _render_result_evidence(st, result)


def _render_evaluation(st, config: dict[str, Any], output_dir: str) -> None:
    st.subheader("训练与评测")
    st.write("这里会重新拟合工具、主动三角定位与 Bandit 调度策略，并输出完整评测文件。")
    if st.button("运行完整评测", type="primary"):
        with st.spinner("正在运行评测，请稍候..."):
            repo = DataRepository(config.get("data_dir", "data/trustgeo_processed"))
            metrics = Evaluator(repo, config, output_dir).run()
        st.success("评测完成")
        st.dataframe(_metrics_rows(metrics), width="stretch", hide_index=True)

    summary_path = Path(output_dir) / "metrics/summary.json"
    if summary_path.exists():
        with summary_path.open("r", encoding="utf-8") as fh:
            metrics = json.load(fh)
        st.subheader("评测指标")
        metric_rows = _metrics_rows(metrics)
        st.dataframe(metric_rows, width="stretch", hide_index=True)
        import pandas as pd

        _altair_error_summary(st, pd.DataFrame(metric_rows))

    frontier_path = Path(output_dir) / "figures/cost_accuracy_frontier.csv"
    if frontier_path.exists():
        st.subheader("成本-精度前沿")
        frontier_rows = _read_csv_rows(frontier_path)
        for row in frontier_rows:
            row["实验"] = row.get("experiment_name") or display_experiment_name(row.get("experiment"))
        st.dataframe(
            [
                {
                    "实验": row.get("实验"),
                    "Mean km": row.get("mean_error_km"),
                    "Median km": row.get("median_error_km"),
                    "平均工具调用": row.get("avg_tool_calls"),
                    "平均探针成本": row.get("avg_probe_cost"),
                    "覆盖率": row.get("coverage"),
                }
                for row in frontier_rows
            ],
            width="stretch",
            hide_index=True,
        )
        _altair_cost_scatter(st, pd.DataFrame(frontier_rows))


def _render_data_outputs(st, pd, repo: DataRepository, output_dir: str) -> None:
    st.subheader("样本预览")
    st.dataframe(
        [
            {
                "ip": target.ip,
                "lat": target.location.lat,
                "lon": target.location.lon,
                "region": target.location.region,
                "city": target.location.city,
                "asn": target.asn,
                "operator": target.operator,
            }
            for target in repo.targets[:200]
        ],
        width="stretch",
        hide_index=True,
    )

    st.subheader("输出文件")
    files = sorted(str(path) for path in Path(output_dir).glob("**/*") if path.is_file())
    st.dataframe([{"path": path} for path in files], width="stretch", hide_index=True)

    report_path = Path(output_dir) / "实验报告.md"
    if report_path.exists():
        st.subheader("实验报告")
        st.markdown(report_path.read_text(encoding="utf-8"))


def _metrics_rows(metrics: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for name, values in metrics.items():
        rows.append(
            {
                "实验": display_experiment_name(name),
                "Median": values.get("Median"),
                "Mean": values.get("Mean"),
                "P90": values.get("P90"),
                "Coverage": values.get("Coverage"),
                "AvgToolCalls": values.get("AvgToolCalls"),
                "AvgProbeCost": values.get("AvgProbeCost"),
            }
        )
    return rows


def _capability_rows(config: dict[str, Any], repo: DataRepository, output_dir: str) -> list[dict[str, str]]:
    project_root = _project_root()
    active_cfg = config.get("active_probe", {})
    scamper_cfg = config.get("scamper", {})
    passive_cfg = config.get("passive_ipdb", {})
    atlas_service = config.get("external_services", {}).get("ripe_atlas", {})

    rows = [
        _capability_row("数据集", bool(repo.targets), f"已加载 {len(repo.targets)} 个目标", "先运行 TrustGeo 数据适配"),
        _capability_row("ModuGeo", bool(repo.modugeo_predictions) or bool(repo.targets), "核心预测或前缀基线可用", "补充 modugeo_predictions.csv 可提升展示效果"),
        _capability_row("rDNS", bool(repo.rdns), f"rDNS 记录 {len(repo.rdns)} 条", "补充 rdns.csv 或启用主动 rDNS 采集"),
        _capability_row("CBG 模拟", _resolve_existing(project_root, "ipgeotools/cbgtool/scripts/utils/helpers.py").exists(), "cbgtool helpers 已纳入本项目", "检查 ipgeotools/cbgtool 是否存在"),
        _capability_row("ScamperTrace 源码", _resolve_existing(project_root, scamper_cfg.get("scampertrace_root", "")).exists(), "scampertrace 项目已纳入 ipgeotools", "检查 scampertrace_root 配置"),
        _capability_row("系统 scamper", shutil.which(str(scamper_cfg.get("scamper_path", "scamper"))) is not None, f"命令：{scamper_cfg.get('scamper_path', 'scamper')}", "安装 scamper 并确认 sudo/权限"),
        _capability_row("RIPE Atlas", _has_atlas_auth(atlas_service), "凭据已配置" if _has_atlas_auth(atlas_service) else "缺少可用认证", "修复 RIPE Atlas API key 或 auth header"),
        _capability_row("Passive IPDB: GeoCN", _resolve_existing(project_root, _source_value(passive_cfg, "GeoCN", "path")).exists(), "GeoCN.mmdb 已就绪", "下载 GeoCN.mmdb 到配置路径"),
        _capability_row("Passive IPDB: ip-database", shutil.which("php") is not None and _resolve_existing(project_root, _source_value(passive_cfg, "ip-database", "ipv6_path")).exists(), "PHP 与 IPv6 库均可用", "安装 PHP 并补 ipv6wry.db"),
        _capability_row("MCP runtime", True, "无需 fastmcp transport 即可在进程内调用", "无"),
        _capability_row("MCP transport", importlib.util.find_spec("fastmcp") is not None, "fastmcp 已安装", "运行 uv sync --extra mcp"),
        _capability_row("RL 第一阶段", bool(config.get("rl", {}).get("sft_dataset_path")), "已配置 SFT 数据集与离线 reward 输出", "运行完整 Evaluator 生成输出"),
        _capability_row("评测输出", (Path(output_dir) / "metrics/summary.json").exists(), "存在最近一次 summary.json", "点击训练与评测页运行完整评测"),
    ]
    if active_cfg.get("allow_live_measurements"):
        rows.append(_capability_row("主动探测预算", True, f"最多 {active_cfg.get('max_targets_per_run')} targets/batch, {active_cfg.get('max_probes_per_target')} probes/target", "无"))
    else:
        rows.append(_capability_row("主动探测预算", False, "live measurement 关闭", "在配置中设置 allow_live_measurements=true"))
    return rows


def _capability_row(name: str, ok: bool, description: str, suggestion: str) -> dict[str, str]:
    if ok:
        status = "可用"
    elif suggestion == "无":
        status = "受限"
    else:
        status = "不可用"
    return {"能力": name, "状态": status, "说明": description, "建议": suggestion}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_existing(project_root: Path, value: Any) -> Path:
    if not value:
        return project_root / "__missing__"
    path = Path(str(value))
    return path if path.is_absolute() else project_root / path


def _source_value(config: dict[str, Any], source_name: str, key: str) -> str:
    for source in config.get("sources", []):
        if source.get("name") == source_name:
            return str(source.get(key) or "")
    return ""


def _has_atlas_auth(atlas_service: dict[str, Any]) -> bool:
    if atlas_service.get("api_key") or atlas_service.get("auth_header"):
        return True
    api_env = atlas_service.get("api_key_env")
    header_env = atlas_service.get("auth_header_env")
    return bool((api_env and os.environ.get(str(api_env))) or (header_env and os.environ.get(str(header_env))))


def _result_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for result in results:
        location = result.get("location") or {}
        rows.append(
            {
                "工具": display_tool_name(result.get("tool")),
                "状态": result.get("status"),
                "纬度": location.get("lat"),
                "经度": location.get("lon"),
                "省份": location.get("region"),
                "城市": location.get("city"),
                "粒度": result.get("granularity"),
                "置信度": result.get("confidence"),
                "探针数": (result.get("cost") or {}).get("probe_count"),
                "失败原因": result.get("failure_reason"),
            }
        )
    return rows


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _inject_style(st) -> None:
    st.markdown(
        """
        <style>
        .trace-row {
            display: grid;
            grid-template-columns: 180px 86px 1fr 120px;
            gap: 10px;
            align-items: stretch;
            margin: 8px 0;
        }
        .trace-node {
            border: 1px solid #dde3ea;
            border-left: 5px solid #8b95a1;
            border-radius: 8px;
            padding: 12px 14px;
            background: #ffffff;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
        }
        .trace-node.call { border-left-color: #2563eb; }
        .trace-node.skip { border-left-color: #94a3b8; background: #f8fafc; }
        .trace-node.ok { border-left-color: #16a34a; }
        .trace-node.conditional { border-left-color: #f59e0b; background: #fffbeb; }
        .trace-node.unavailable { border-left-color: #dc2626; }
        .trace-title { font-weight: 700; color: #0f172a; margin-bottom: 4px; }
        .trace-meta { color: #475569; font-size: 13px; line-height: 1.45; }
        .pill {
            display: inline-flex;
            justify-content: center;
            border-radius: 999px;
            padding: 5px 10px;
            font-size: 12px;
            font-weight: 700;
            border: 1px solid #dbe3ef;
            background: #f8fafc;
            color: #334155;
        }
        .pill.call { background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }
        .pill.skip { background: #f1f5f9; color: #64748b; border-color: #cbd5e1; }
        .pill.ok { background: #ecfdf5; color: #047857; border-color: #bbf7d0; }
        .pill.conditional { background: #fffbeb; color: #b45309; border-color: #fde68a; }
        .pill.unavailable { background: #fef2f2; color: #b91c1c; border-color: #fecaca; }
        .kv-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 10px;
            margin: 8px 0 18px 0;
        }
        .kv-card {
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 12px;
            background: #ffffff;
        }
        .kv-label { color: #64748b; font-size: 12px; margin-bottom: 4px; }
        .kv-value { color: #0f172a; font-size: 18px; font-weight: 700; overflow-wrap: anywhere; }
        .soft-card {
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 14px;
            background: #f8fafc;
            margin: 8px 0;
        }
        .mono-small {
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 12px;
            color: #334155;
            overflow-wrap: anywhere;
        }
        .method-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 12px;
            margin: 8px 0 18px 0;
        }
        .method-card {
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 14px;
            background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
            min-height: 138px;
        }
        @media (max-width: 760px) {
            .trace-row {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _ratio(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _summary_items(summary: dict[str, Any]) -> list[tuple[str, Any]]:
    return [
        ("TrustGeo 根目录", summary.get("trustgeo_root")),
        ("输出目录", summary.get("output_dir")),
        ("目标数", summary.get("targets")),
        ("Trace Hop", summary.get("traces")),
        ("探针数", summary.get("probes")),
        ("Landmark", summary.get("landmarks")),
        ("ModuGeo 预测", summary.get("modugeo_predictions")),
        ("说明", summary.get("note")),
    ]


def _render_key_value_grid(st, items: list[tuple[str, Any]]) -> None:
    cards = []
    for label, value in items:
        cards.append(
            f"""
            <div class="kv-card">
              <div class="kv-label">{_html(label)}</div>
              <div class="kv-value">{_html(_display(value))}</div>
            </div>
            """
        )
    st.markdown(f"<div class='kv-grid'>{''.join(cards)}</div>", unsafe_allow_html=True)


def _render_validation_cards(st, report: dict[str, Any]) -> None:
    status = "可用于评测" if report.get("is_valid_for_evaluation") else "需要修复"
    items = [
        ("评测状态", status),
        ("重复目标", report.get("duplicate_target_count")),
        ("非法经纬度", report.get("invalid_target_count")),
        ("缺 Trace 目标", report.get("missing_trace_target_count")),
        ("缺 ModuGeo 预测", report.get("missing_modugeo_prediction_count")),
        ("缺 rDNS 目标", report.get("missing_rdns_target_count")),
    ]
    _render_key_value_grid(st, items)
    if report.get("missing_rdns_target_count"):
        st.warning("当前数据集中没有 rDNS 覆盖，rDNS 工具会真实显示为不可用。")
    if report.get("invalid_target_examples"):
        st.caption("非法目标示例：" + "，".join(report["invalid_target_examples"]))


def _render_trustgeo_adapter_note(st) -> None:
    st.markdown(
        """
        <div class="soft-card">
          <div class="trace-title">TrustGeo 数据适配代表什么</div>
          <div class="trace-meta">
          它不是重新采集数据，也不会修改 /home/lzj/TrustGeo 原始文件；
          它只是把 TrustGeo 已有的 pfxgeo_v11 预测、traceroute、pfx2as、AS WHOIS GPS 与城市坐标，
          转换成本系统统一的 targets / traces / probes / metadata / landmarks / modugeo_predictions 输入表。
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_pipeline_summary(st, config: dict[str, Any]) -> None:
    active_cfg = config.get("active_probe", {})
    atlas_cfg = config.get("ripe_atlas", {})
    rl_cfg = config.get("rl", {})
    st.subheader("当前系统链路")
    cards = [
        (
            "数据层",
            "targets / traces / probes / metadata / rDNS / landmarks / ModuGeo predictions",
            "统一 CSV 输入，缺失不伪造。",
        ),
        (
            "工具层",
            "ModuGeo + rDNS + CBG/scamper/RIPE Atlas + Passive IPDB + WHOIS/BGP",
            f"主动探测：{'允许' if active_cfg.get('allow_live_measurements') else '关闭'}；每批目标上限 {active_cfg.get('max_targets_per_run')}。",
        ),
        (
            "Agent 层",
            "规则调度 / Contextual Bandit / Qwen baseline / Offline Reward Policy",
            "调度器只选工具，不直接输出坐标。",
        ),
        (
            "评测与 RL",
            "单工具、融合、调度策略、SFT 数据、离线 reward 对比",
            "训练顺序：" + " -> ".join(rl_cfg.get("training_order", [])),
        ),
        (
            "MCP 调用",
            "ipv6geo-mcp 暴露 health/list/run/geolocate/debug/scamper 工具",
            "安装 fastmcp extra 后可由 Agent 通过 MCP 调用。",
        ),
        (
            "RIPE Atlas 策略",
            "中国探针、最多 3 probes/target、最多 2 retries、最多 20 targets/batch",
            f"探针选择：{atlas_cfg.get('probe_selection')}",
        ),
    ]
    html = []
    for title, body, footnote in cards:
        html.append(
            f"""
            <div class="method-card">
              <div class="trace-title">{_html(title)}</div>
              <div class="trace-meta">{_html(body)}</div>
              <div class="trace-meta">{_html(footnote)}</div>
            </div>
            """
        )
    st.markdown(f"<div class='method-grid'>{''.join(html)}</div>", unsafe_allow_html=True)


def _render_method_catalog(st) -> None:
    st.subheader("方法目录")
    cards = []
    for spec in METHOD_SPECS:
        enabled = "默认启用" if spec.default_enabled else "备选"
        cards.append(
            f"""
            <div class="method-card">
              <div class="trace-title">{_html(spec.name)}</div>
              <div class="trace-meta">{_html(spec.category)} · 成本{_html(spec.cost_level)} · {_html(enabled)}</div>
              <div class="trace-meta">{_html(spec.description)}</div>
              <div class="trace-meta">证据类型：{_html(spec.evidence_type)}</div>
            </div>
            """
        )
    st.markdown(f"<div class='method-grid'>{''.join(cards)}</div>", unsafe_allow_html=True)


def _render_location_result(
    st,
    target_ip: str,
    truth,
    prediction: dict[str, Any],
    granularity: str | None,
    failure_reason: str | None,
) -> None:
    pred_text = _format_location(prediction)
    truth_text = _format_location({"lat": truth.lat, "lon": truth.lon, "region": truth.region, "city": truth.city})
    _render_key_value_grid(
        st,
        [
            ("目标 IPv6", target_ip),
            ("真实位置", truth_text),
            ("预测位置", pred_text),
            ("粒度", granularity or "无"),
            ("失败原因", failure_reason or "无"),
        ],
    )


def _render_trace_flow(st, decisions: list[dict[str, Any]]) -> None:
    rows = []
    for index, item in enumerate(decisions, start=1):
        action = str(item.get("action") or "").lower()
        status = str(item.get("status") or "").lower()
        action_class = "call" if action == "call" else "skip"
        if status == "ok":
            status_class = "ok"
        elif status == "unavailable":
            status_class = "unavailable"
        elif status == "conditional":
            status_class = "conditional"
        else:
            status_class = action_class
        rows.append(
            f"""
            <div class="trace-row">
              <div class="trace-node {action_class}">
                <div class="trace-title">{index}. {_html(item.get("step"))}</div>
                <div class="trace-meta">节点执行</div>
              </div>
              <div class="trace-node {action_class}">
                <span class="pill {action_class}">{_html(_action_label(action))}</span>
              </div>
              <div class="trace-node {action_class}">
                <div class="trace-title">选择原因</div>
                <div class="trace-meta">{_html(item.get("reason"))}</div>
              </div>
              <div class="trace-node {status_class}">
                <span class="pill {status_class}">{_html(_status_label(status))}</span>
              </div>
            </div>
            """
        )
    st.markdown("".join(rows), unsafe_allow_html=True)


def _render_agent_flow(st) -> None:
    flow = [
        {"step": "1. ModuGeo", "action": "call", "reason": "核心定位器固定先调用，提供前缀与 last-hop 条件预测", "status": "ok"},
        {"step": "2. WHOIS/BGP", "action": "call", "reason": "补充 ASN、组织、注册地和 BGP 前缀上下文", "status": "ok"},
        {"step": "3. rDNS", "action": "call", "reason": "有 hostname 时解析城市缩写、拼音或机场码", "status": "conditional"},
        {"step": "4. Passive IPDB", "action": "call", "reason": "低成本候选位置，缺数据库时返回 unavailable", "status": "conditional"},
        {"step": "5. 主动三角定位", "action": "call", "reason": "ModuGeo 置信度低时使用 CBG/scamper/RIPE Atlas RTT 约束", "status": "conditional"},
        {"step": "6. Fusion", "action": "call", "reason": "置信度加权融合，并显式记录工具冲突距离", "status": "ok"},
    ]
    _render_trace_flow(st, flow)


def _altair_horizontal_bar(st, df, x: str, y: str, title: str, color: str, x_format: str | None = None) -> None:
    import altair as alt
    import pandas as pd

    chart_df = df.copy()
    chart_df[x] = pd.to_numeric(chart_df[x], errors="coerce").fillna(0)
    axis = alt.Axis(format=x_format) if x_format else alt.Axis()
    chart = (
        alt.Chart(chart_df, title=title)
        .mark_bar(cornerRadiusEnd=4, color=color)
        .encode(
            x=alt.X(f"{x}:Q", axis=axis, title=None),
            y=alt.Y(f"{y}:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220)),
            tooltip=[alt.Tooltip(f"{y}:N"), alt.Tooltip(f"{x}:Q", format=".4f")],
        )
        .properties(height=max(260, 34 * len(chart_df)))
    )
    st.altair_chart(chart, width="stretch")


def _altair_grouped_bar(st, df, x: str, y: str, color: str, title: str) -> None:
    import altair as alt
    import pandas as pd

    chart_df = df.copy()
    chart_df[x] = pd.to_numeric(chart_df[x], errors="coerce").fillna(0)
    chart = (
        alt.Chart(chart_df, title=title)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X(f"{x}:Q", title=None),
            y=alt.Y(f"{y}:N", sort="-x", title=None, axis=alt.Axis(labelLimit=240)),
            color=alt.Color(f"{color}:N", title=None),
            tooltip=[alt.Tooltip(f"{y}:N"), alt.Tooltip(f"{color}:N"), alt.Tooltip(f"{x}:Q", format=".3f")],
        )
        .properties(height=max(280, 28 * len(chart_df)))
    )
    st.altair_chart(chart, width="stretch")


def _altair_status_bar(st, df) -> None:
    import altair as alt
    import pandas as pd

    if df.empty:
        return
    counts = df.groupby("状态", as_index=False).size().rename(columns={"size": "数量"})
    chart = (
        alt.Chart(counts, title="能力状态分布")
        .mark_bar(cornerRadiusEnd=4)
        .encode(
            x=alt.X("数量:Q", title=None),
            y=alt.Y("状态:N", sort=["可用", "受限", "不可用"], title=None),
            color=alt.Color(
                "状态:N",
                scale=alt.Scale(domain=["可用", "受限", "不可用"], range=["#16a34a", "#f59e0b", "#dc2626"]),
                title=None,
            ),
            tooltip=["状态:N", "数量:Q"],
        )
        .properties(height=180)
    )
    st.altair_chart(chart, width="stretch")


def _altair_error_summary(st, df) -> None:
    import altair as alt
    import pandas as pd

    long_df = df.melt(id_vars=["实验"], value_vars=["Median", "Mean", "P90"], var_name="指标", value_name="误差km")
    long_df["误差km"] = pd.to_numeric(long_df["误差km"], errors="coerce")
    chart = (
        alt.Chart(long_df.dropna(), title="误差指标对比")
        .mark_line(point=True)
        .encode(
            x=alt.X("误差km:Q", title="误差 km"),
            y=alt.Y("实验:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
            color=alt.Color("指标:N", title=None),
            tooltip=["实验:N", "指标:N", alt.Tooltip("误差km:Q", format=".3f")],
        )
        .properties(height=max(300, 32 * len(df)))
    )
    st.altair_chart(chart, width="stretch")


def _altair_cost_scatter(st, df) -> None:
    import altair as alt
    import pandas as pd

    chart_df = df.copy()
    for col in ("mean_error_km", "avg_probe_cost", "coverage"):
        chart_df[col] = pd.to_numeric(chart_df[col], errors="coerce")
    if "实验" not in chart_df:
        chart_df["实验"] = chart_df["experiment"].map(display_experiment_name)
    chart = (
        alt.Chart(chart_df, title="成本-精度前沿")
        .mark_circle(size=140, opacity=0.82)
        .encode(
            x=alt.X("avg_probe_cost:Q", title="平均探针成本"),
            y=alt.Y("mean_error_km:Q", title="Mean Error km"),
            color=alt.Color("coverage:Q", title="Coverage", scale=alt.Scale(scheme="viridis")),
            tooltip=[
                "实验:N",
                alt.Tooltip("mean_error_km:Q", format=".3f"),
                alt.Tooltip("avg_probe_cost:Q", format=".3f"),
                alt.Tooltip("coverage:Q", format=".3f"),
            ],
        )
        .properties(height=340)
    )
    st.altair_chart(chart, width="stretch")


def _render_bandit_decision(st, evidence: dict[str, Any]) -> None:
    context = evidence.get("context") or []
    _render_key_value_grid(
        st,
        [
            ("调度器", "Contextual Bandit"),
            ("选择动作", evidence.get("selected_action")),
            ("默认动作", evidence.get("global_action")),
            ("已学习上下文数", evidence.get("known_context_count")),
            ("当前上下文", " / ".join(str(item) for item in context)),
        ],
    )


def _render_tool_evidence_sections(st, results: list[dict[str, Any]]) -> None:
    st.subheader("工具证据摘要")
    for result in results:
        tool_name = display_tool_name(result.get("tool"))
        with st.expander(f"{tool_name}：{result.get('status')}，置信度 {_display_conf(result.get('confidence'))}"):
            _render_result_evidence(st, result)


def _render_result_evidence(st, result: dict[str, Any]) -> None:
    evidence = result.get("evidence") or {}
    cost = result.get("cost") or {}
    location = result.get("location") or {}
    _render_key_value_grid(
        st,
        [
            ("工具", display_tool_name(result.get("tool"))),
            ("状态", result.get("status")),
            ("置信度", _display_conf(result.get("confidence"))),
            ("坐标", _format_location(location)),
            ("工具调用数", cost.get("tool_calls")),
            ("探针数", cost.get("probe_count")),
        ],
    )
    if result.get("failure_reason"):
        st.error(result["failure_reason"])
    if evidence.get("signals"):
        st.markdown("**关键证据信号**")
        for signal in evidence["signals"]:
            st.markdown(f"- {signal}")
    if evidence.get("constraints"):
        st.markdown("**主动三角定位约束摘要**")
        st.dataframe(evidence["constraints"][:20], width="stretch", hide_index=True)
    if evidence.get("conflicts"):
        st.markdown("**工具冲突距离**")
        st.dataframe(evidence["conflicts"], width="stretch", hide_index=True)
    if evidence.get("context"):
        st.markdown("**上下文证据**")
        rows = []
        for item in evidence["context"]:
            item_evidence = item.get("evidence") or {}
            rows.append(
                {
                    "prefix": item_evidence.get("prefix"),
                    "asn": item_evidence.get("asn"),
                    "org": item_evidence.get("org"),
                    "registered_region": item_evidence.get("registered_region"),
                    "registered_city": item_evidence.get("registered_city"),
                }
            )
        st.dataframe(rows, width="stretch", hide_index=True)
    if evidence.get("scheduler"):
        scheduler = evidence["scheduler"]
        if scheduler.get("decisions"):
            _render_trace_flow(st, scheduler["decisions"])
        else:
            _render_bandit_decision(st, scheduler)
    _render_remaining_evidence(st, evidence)


def _render_remaining_evidence(st, evidence: dict[str, Any]) -> None:
    known = {"signals", "constraints", "conflicts", "context", "scheduler"}
    rows = []
    for key, value in evidence.items():
        if key in known:
            continue
        rows.append({"字段": key, "内容": _compact_value(value)})
    if rows:
        st.markdown("**其他证据字段**")
        st.dataframe(rows, width="stretch", hide_index=True)


def _format_location(location: dict[str, Any]) -> str:
    parts = []
    if location.get("region"):
        parts.append(str(location["region"]))
    if location.get("city"):
        parts.append(str(location["city"]))
    lat = location.get("lat")
    lon = location.get("lon")
    if lat is not None and lon is not None:
        parts.append(f"({float(lat):.6f}, {float(lon):.6f})")
    return " / ".join(parts) if parts else "无坐标"


def _action_label(action: str) -> str:
    return {"call": "调用", "skip": "跳过"}.get(action, action or "未知")


def _status_label(status: str) -> str:
    return {"ok": "可用", "unavailable": "不可用", "conditional": "条件调用"}.get(status, status or "未知")


def _display(value: Any) -> str:
    if value is None:
        return "无"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _display_conf(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except Exception:
        return "无"


def _compact_value(value: Any) -> str:
    if isinstance(value, (str, int, float)) or value is None:
        return _display(value)
    if isinstance(value, list):
        return f"{len(value)} 项：" + "；".join(_display(item) for item in value[:3])
    if isinstance(value, dict):
        return "；".join(f"{key}={_display(val)}" for key, val in list(value.items())[:6])
    return str(value)


def _html(value: Any) -> str:
    import html

    return html.escape(_display(value))


if __name__ == "__main__":
    main()
