import unittest
import tempfile
from pathlib import Path

from agentic_ipv6_geo.data.repository import DataRepository
from agentic_ipv6_geo.fusion import FusionTool
from agentic_ipv6_geo.mcp_server import IPv6GeoMcpRuntime
from agentic_ipv6_geo.providers import ZDnsBulkRDnsCollector
from agentic_ipv6_geo.tools import ActiveTriangulationTool, CBGGeoTool, ModuGeoTool, RDnsGeoTool
from agentic_ipv6_geo.tools.registry import METHOD_SPECS, build_methods


class ToolTests(unittest.TestCase):
    def test_modugeo_and_rdns_return_structured_results(self):
        repo = DataRepository("data/processed")
        train, test = repo.split_targets(test_ratio=0.25, seed=1)
        target = test[0]
        modugeo = ModuGeoTool(repo)
        modugeo.fit(train)
        rdns = RDnsGeoTool(repo)

        modugeo_result = modugeo.run(target)
        rdns_result = rdns.run(target)

        self.assertIn(modugeo_result.status, {"ok", "unavailable"})
        self.assertEqual(rdns_result.status, "ok")
        self.assertEqual(rdns_result.granularity, "city")

    def test_cbg_requires_at_least_three_constraints(self):
        repo = DataRepository("data/processed")
        target = next(item for item in repo.targets if item.ip == "240e:100:1000:2::2")
        cbg = CBGGeoTool(repo, {"min_constraints": 4})
        cbg.fit(repo.targets)

        result = cbg.run(target)

        self.assertEqual(result.status, "unavailable")
        self.assertIn("少于 4 个", result.failure_reason)

    def test_active_triangulation_uses_cbgtool_contract(self):
        repo = DataRepository("data/processed")
        target = next(item for item in repo.targets if item.ip == "240e:100:1000:1::1")
        tool = ActiveTriangulationTool(repo, {"min_constraints": 3, "cbgtool_root": "ipgeotools/cbgtool"})

        result = tool.run(target)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.evidence["source"], "GraduatePaper/ipgeotools/cbgtool/scripts/utils/helpers.py")
        self.assertTrue(result.location.has_coordinate)

    def test_method_registry_builds_default_methods(self):
        repo = DataRepository("data/processed")
        methods = build_methods(repo, {"active_triangulation": {"cbgtool_root": "ipgeotools/cbgtool"}}, repo.targets)

        self.assertIn("active_triangulation", methods)
        self.assertEqual(len({spec.name for spec in METHOD_SPECS}), len(METHOD_SPECS))

    def test_fusion_conflict_penalty_keeps_coordinate_output(self):
        repo = DataRepository("data/processed")
        train, test = repo.split_targets(test_ratio=0.25, seed=2)
        target = test[0]
        modugeo = ModuGeoTool(repo)
        modugeo.fit(train)
        results = [modugeo.run(target), RDnsGeoTool(repo).run(target)]

        fused = FusionTool().run(results)

        self.assertEqual(fused.status, "ok")
        self.assertTrue(fused.location.has_coordinate)

    def test_mcp_runtime_runs_tools_without_transport(self):
        runtime = IPv6GeoMcpRuntime("configs/default.json")
        target_ip = "240e:100:1000:1::1"

        health = runtime.health()
        active = runtime.run_geo_tool(target_ip, "active_triangulation")
        scheduled = runtime.geolocate_ip(target_ip, include_candidates=True)
        scamper = runtime.collect_scamper_constraints(target_ip, allow_live=False)

        self.assertEqual(health["status"], "ok")
        self.assertEqual(active["result"]["status"], "ok")
        self.assertIn(scheduled["result"]["status"], {"ok", "unavailable"})
        self.assertIn(scamper["status"], {"ok", "unavailable"})

    def test_zdns_bulk_collector_normalizes_status_and_writes_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_zdns = root / "fake_zdns.py"
            fake_zdns.write_text(
                """#!/usr/bin/env python3
import json
import sys
from pathlib import Path

input_file = Path(sys.argv[sys.argv.index("--input-file") + 1])
for ip in input_file.read_text().splitlines():
    if ip.endswith("1"):
        payload = {
            "name": ip,
            "results": {"PTR": {"status": "NOERROR", "duration": 0.01, "data": {"resolver": "fake:53", "protocol": "udp", "answers": [{"type": "PTR", "answer": "bj.example."}]}}},
        }
    elif ip.endswith("2"):
        payload = {"name": ip, "results": {"PTR": {"status": "NXDOMAIN", "duration": 0.02, "data": {}, "error": "not found"}}}
    else:
        payload = {"name": ip, "results": {"PTR": {"status": "NOERROR", "duration": 0.03, "data": {"answers": []}}}}
    print(json.dumps(payload))
""",
                encoding="utf-8",
            )
            fake_zdns.chmod(0o755)

            collector = ZDnsBulkRDnsCollector(zdns_bin=str(fake_zdns))
            summary = collector.collect(
                ["240e::1", "240e::2", "240e::3"],
                root / "full.jsonl",
                root / "rdns.csv",
                root / "summary.json",
                show_progress=False,
            )
            parse_error = collector.parse_json_line("{bad json")

            self.assertEqual(summary["total_queried"], 3)
            self.assertEqual(summary["ok_count"], 1)
            self.assertEqual(summary["status_counts"]["nxdomain"], 1)
            self.assertEqual(summary["status_counts"]["no_answer"], 1)
            self.assertEqual(parse_error.status, "parse_error")
            self.assertIn("bj.example", (root / "rdns.csv").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
