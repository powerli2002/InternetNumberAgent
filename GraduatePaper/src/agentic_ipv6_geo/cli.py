from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from agentic_ipv6_geo.common.config import load_runtime_config, runtime_warnings
from agentic_ipv6_geo.common.logger import JsonlLogger
from agentic_ipv6_geo.common.models import Location, Target
from agentic_ipv6_geo.data.repository import DataRepository, write_jsonl
from agentic_ipv6_geo.data.p0_builder import P0Builder
from agentic_ipv6_geo.data.trustgeo_adapter import TrustGeoAdapter
from agentic_ipv6_geo.data.validator import DataValidator, write_validation_report
from agentic_ipv6_geo.evaluation import Evaluator
from agentic_ipv6_geo.providers import ZDnsBulkRDnsCollector
from agentic_ipv6_geo.scheduler import RuleAgentScheduler
from agentic_ipv6_geo.tools.registry import build_methods


def load_config(path: str | Path) -> dict:
    return load_runtime_config(path)


def _print_runtime_warnings(config: dict) -> None:
    for warning in runtime_warnings(config):
        print(f"配置警告：{warning}", file=sys.stderr)


def evaluate_main() -> None:
    parser = argparse.ArgumentParser(description="运行 IPv6 地理位置推断评测实验")
    parser.add_argument("--config", default="configs/default.json")
    parser.add_argument("--output-dir", default="outputs")
    args = parser.parse_args()

    config = load_config(args.config)
    _print_runtime_warnings(config)
    repo = DataRepository(config.get("data_dir", "data/processed"))
    metrics = Evaluator(repo, config, args.output_dir).run()
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def run_main() -> None:
    parser = argparse.ArgumentParser(description="批量调度 IPv6 地理位置推断工具")
    parser.add_argument("--config", default="configs/default.json")
    parser.add_argument("--targets", default="data/processed/targets.csv")
    parser.add_argument("--output", default="outputs/predictions/batch_predictions.jsonl")
    args = parser.parse_args()

    config = load_config(args.config)
    _print_runtime_warnings(config)
    repo = DataRepository(config.get("data_dir", "data/processed"))
    train_targets = repo.targets
    methods = build_methods(repo, config, train_targets)
    scheduler = RuleAgentScheduler(
        methods["modugeo"],
        methods["rdns"],
        methods["active_triangulation"],
        methods["whois"],
        methods.get("passive_ipdb"),
        methods["fusion"],
        config.get("scheduler"),
        JsonlLogger(config.get("log_path")),
    )

    rows = []
    for target in _load_targets_for_prediction(args.targets):
        result = scheduler.run(target)
        rows.append({"target_ip": target.ip, "result": result.to_dict()})
    write_jsonl(args.output, rows)
    print(f"已写入 {args.output}")


def prepare_trustgeo_main() -> None:
    parser = argparse.ArgumentParser(description="将 /home/lzj/TrustGeo 数据适配为统一实验输入")
    parser.add_argument("--trustgeo-root", default="/home/lzj/TrustGeo")
    parser.add_argument("--output-dir", default="data/trustgeo_processed")
    parser.add_argument("--max-targets", type=int, default=None)
    args = parser.parse_args()
    summary = TrustGeoAdapter(args.trustgeo_root, args.output_dir, args.max_targets).run()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def validate_main() -> None:
    parser = argparse.ArgumentParser(description="校验统一实验输入数据")
    parser.add_argument("--config", default="configs/default.json")
    parser.add_argument("--output", default="outputs/metrics/data_validation.json")
    args = parser.parse_args()
    config = load_config(args.config)
    _print_runtime_warnings(config)
    report = DataValidator(DataRepository(config.get("data_dir", "data/processed"))).validate()
    write_validation_report(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def collect_rdns_main() -> None:
    parser = argparse.ArgumentParser(description="使用 zdns 批量采集 IPv6 PTR/rDNS 结果")
    parser.add_argument("--input", default="/home/lzj/TrustGeo/data/ipgeo_collected_data_20260114.csv", help="输入 CSV 或纯 IP 列表")
    parser.add_argument("--ip-version", type=int, choices=[4, 6], default=6)
    parser.add_argument("--limit", type=int, default=None, help="仅查询前 N 个去重后的公开 IP")
    parser.add_argument("--zdns-bin", default="outputs/rdns_test/zdns", help="zdns 可执行文件路径或 PATH 中的命令名")
    parser.add_argument("--resolver", default="1.1.1.1", help="递归解析器，iterative 模式会忽略")
    parser.add_argument("--mode", choices=["recursive", "iterative"], default="recursive")
    parser.add_argument("--network-timeout", type=int, default=2)
    parser.add_argument("--iteration-timeout", type=int, default=4)
    parser.add_argument("--output-jsonl", default="outputs/rdns/zdns_ptr_results.jsonl")
    parser.add_argument("--output-rdns-csv", default="data/trustgeo_processed/rdns.csv")
    parser.add_argument("--summary", default="outputs/rdns/zdns_ptr_summary.json")
    parser.add_argument("--append", action="store_true", help="追加写入输出文件")
    parser.add_argument("--resume", action="store_true", help="跳过 output-jsonl 中已经存在的 IP")
    parser.add_argument("--no-progress", action="store_true", help="关闭进度条")
    args = parser.parse_args()

    ips = ZDnsBulkRDnsCollector.extract_ips_from_file(args.input, ip_version=args.ip_version, limit=args.limit)
    collector = ZDnsBulkRDnsCollector(
        zdns_bin=args.zdns_bin,
        resolver=args.resolver,
        mode=args.mode,
        network_timeout=args.network_timeout,
        iteration_timeout=args.iteration_timeout,
    )
    summary = collector.collect(
        ips,
        args.output_jsonl,
        args.output_rdns_csv,
        args.summary,
        show_progress=not args.no_progress,
        append=args.append,
        resume=args.resume,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_p0_main() -> None:
    parser = argparse.ArgumentParser(description="构建无泄漏、可回放的 GeoAgent P0 训练环境")
    parser.add_argument("--config", default="configs/trustgeo.json")
    parser.add_argument("--output-dir", default="outputs/p0")
    args = parser.parse_args()

    config = load_config(args.config)
    repo = DataRepository(config.get("data_dir", "data/trustgeo_processed"))
    summary = P0Builder(repo, config, args.output_dir).run()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def dashboard_main() -> None:
    parser = argparse.ArgumentParser(description="启动 Streamlit 可视化界面")
    parser.add_argument("--config", default="configs/trustgeo.json")
    parser.add_argument("--server-port", default="8501")
    parser.add_argument("--server-address", default="127.0.0.1")
    args = parser.parse_args()

    try:
        from streamlit.web import cli as stcli
    except Exception as exc:
        raise SystemExit("未安装 Streamlit。请先运行：UV_CACHE_DIR=.uv-cache uv sync --extra ui") from exc

    dashboard_path = Path(__file__).resolve().parent / "ui/dashboard.py"
    sys.argv = [
        "streamlit",
        "run",
        str(dashboard_path),
        "--server.port",
        str(args.server_port),
        "--server.address",
        str(args.server_address),
        "--",
        "--config",
        args.config,
    ]
    stcli.main()


def _load_targets_for_prediction(path: str | Path) -> list[Target]:
    rows = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append(
                Target(
                    ip=row["ip"].strip(),
                    location=Location(
                        lat=float(row["lat"]) if row.get("lat") else None,
                        lon=float(row["lon"]) if row.get("lon") else None,
                        region=row.get("region") or None,
                        city=row.get("city") or None,
                    ),
                    asn=row.get("asn") or None,
                    operator=row.get("operator") or None,
                    observed_at=row.get("observed_at") or None,
                )
            )
    return rows


if __name__ == "__main__":
    evaluate_main()
