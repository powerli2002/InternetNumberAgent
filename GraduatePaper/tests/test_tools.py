import unittest

from agentic_ipv6_geo.data.repository import DataRepository
from agentic_ipv6_geo.fusion import FusionTool
from agentic_ipv6_geo.mcp_server import IPv6GeoMcpRuntime
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


if __name__ == "__main__":
    unittest.main()
