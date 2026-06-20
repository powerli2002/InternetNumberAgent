import json
import unittest

from agentic_ipv6_geo.cli import load_config
from agentic_ipv6_geo.data.repository import DataRepository
from agentic_ipv6_geo.environment import scan_for_private_truth
from agentic_ipv6_geo.evaluation import Evaluator


class EvaluatorTests(unittest.TestCase):
    def test_evaluator_runs_all_mvp_experiments(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = load_config("configs/default.json")
            config["log_path"] = str(tmp_path / "run.jsonl")
            config["rl"]["trajectory_dir"] = str(tmp_path / "rl/trajectories")
            config["rl"]["sft_dataset_path"] = str(tmp_path / "rl/sft/tool_selection_sft.jsonl")
            config["rl"]["reward_summary_path"] = str(tmp_path / "rl/reward_summary.json")
            config["rl"]["offline_reward_comparison_path"] = str(tmp_path / "rl/offline_reward_comparison.json")
            config["rl"]["policy_path"] = str(tmp_path / "rl/policy.json")
            repo = DataRepository(config["data_dir"])

            metrics = Evaluator(repo, config, tmp_path).run()

            self.assertIn("single_modugeo", metrics)
            self.assertIn("single_active_triangulation", metrics)
            self.assertIn("fusion_all", metrics)
            self.assertIn("scheduler_rule", metrics)
            self.assertIn("scheduler_bandit", metrics)
            self.assertGreater(metrics["scheduler_rule"]["Coverage"], 0)
            sft_rows = [
                json.loads(line)
                for line in (tmp_path / "rl/sft/tool_selection_sft.jsonl").read_text(encoding="utf-8").splitlines()
                if line
            ]
            self.assertFalse(scan_for_private_truth([row["messages"] for row in sft_rows]))


if __name__ == "__main__":
    unittest.main()
