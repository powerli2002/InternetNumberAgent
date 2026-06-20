import json
import tempfile
import unittest
from pathlib import Path

from agentic_ipv6_geo.cli import load_config
from agentic_ipv6_geo.data.p0_builder import P0Builder, prefix_isolated_split, task_id_for
from agentic_ipv6_geo.data.repository import DataRepository
from agentic_ipv6_geo.environment import AgentAction, GeoAgentEnv, PrivateTruth, ToolObservation, load_p0_environment, scan_for_private_truth
from agentic_ipv6_geo.environment.schemas import CandidateLocation


class P0EnvironmentTests(unittest.TestCase):
    def test_leakage_scanner_finds_private_fields(self):
        findings = scan_for_private_truth({"state": {"truth_city": "北京"}})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].key, "truth_city")
        self.assertEqual(scan_for_private_truth({"state": {"registered_city": "北京"}}), [])

    def test_prefix_split_is_isolated(self):
        repo = DataRepository("data/processed")
        assignments = prefix_isolated_split(repo.targets, seed=7, prefix_length=48)
        prefix_splits = {}
        for target in repo.targets:
            prefix = target.ip.split(":")[:3]
            key = ":".join(prefix)
            prefix_splits.setdefault(key, set()).add(assignments[target.ip])
        self.assertTrue(all(len(splits) == 1 for splits in prefix_splits.values()))

    def test_replay_environment_is_deterministic_and_rejects_invalid_action(self):
        from agentic_ipv6_geo.common.models import Location

        task_id = "geo-test"
        candidate = CandidateLocation(task_id + ":modugeo", "modugeo", Location(lat=39.9, lon=116.3), "coordinate", 0.7)
        observation = ToolObservation(
            tool_id="modugeo",
            status="ok",
            applicability="applicable",
            failure_type=None,
            failure_reason=None,
            candidate=candidate,
        )
        tasks = {task_id: {"task_id": task_id, "target": {"prefix_48": "240e:1::/48"}, "available_tools": ["modugeo"]}}
        replay = {task_id: {"modugeo": observation}}
        truth = {task_id: PrivateTruth(task_id, Location(lat=39.91, lon=116.31))}
        env = GeoAgentEnv(tasks, replay, truth, max_steps=2)

        first = env.reset(task_id)
        _obs, first_reward, done = env.step(AgentAction("finalize", {"candidate_id": candidate.candidate_id}))
        second = env.reset(task_id)
        _obs, second_reward, done_second = env.step(AgentAction("finalize", {"candidate_id": candidate.candidate_id}))
        self.assertEqual(first, second)
        self.assertEqual(first_reward, second_reward)
        self.assertTrue(done and done_second)
        trajectory = env.trajectory()
        self.assertTrue(trajectory["done"])
        self.assertEqual(len(trajectory["history"]), 1)
        self.assertFalse(scan_for_private_truth(trajectory))

        env.reset(task_id)
        _obs, reward, done = env.step({"action": "not_allowed", "arguments": {}})
        self.assertFalse(done)
        self.assertIsNone(reward)

    def test_p0_builder_writes_private_and_visible_data_separately(self):
        repo = DataRepository("data/processed")
        config = load_config("configs/default.json")
        with tempfile.TemporaryDirectory() as tmp:
            summary = P0Builder(repo, config, tmp).run()
            root = Path(tmp)
            tasks = [json.loads(line) for line in (root / "dataset/tasks.jsonl").read_text(encoding="utf-8").splitlines()]
            truth = [json.loads(line) for line in (root / "dataset/private_truth.jsonl").read_text(encoding="utf-8").splitlines()]
            sft = [json.loads(line) for line in (root / "dataset/sft_seed.jsonl").read_text(encoding="utf-8").splitlines()]
            replay = [json.loads(line) for line in (root / "dataset/tool_replay.jsonl").read_text(encoding="utf-8").splitlines()]

            self.assertTrue(summary["p0_build_complete"])
            self.assertEqual(len(tasks), len(repo.targets))
            self.assertEqual(len(truth), len(repo.targets))
            self.assertEqual(len(replay), len(repo.targets) * 5)
            self.assertFalse(scan_for_private_truth(tasks))
            self.assertFalse(scan_for_private_truth([row["messages"] for row in sft]))
            self.assertIn("truth", truth[0])
            self.assertNotIn("split", tasks[0])
            first_sft_prompt = json.loads(sft[0]["messages"][1]["content"])
            self.assertTrue(first_sft_prompt["visible_candidates"])
            self.assertEqual(task_id_for(repo.targets[0].ip)[:4], "geo-")
            self.assertTrue((root / "audit/oracle_audit.json").exists())
            self.assertTrue((root / "build_manifest.json").exists())

            env = load_p0_environment(root)
            task_id = tasks[0]["task_id"]
            first = env.reset(task_id)
            second = env.reset(task_id)
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
