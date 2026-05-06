import unittest

from agentic_ipv6_geo.cli import load_config
from agentic_ipv6_geo.data.repository import DataRepository
from agentic_ipv6_geo.evaluation import Evaluator


class EvaluatorTests(unittest.TestCase):
    def test_evaluator_runs_all_mvp_experiments(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = load_config("configs/default.json")
            config["log_path"] = str(tmp_path / "run.jsonl")
            repo = DataRepository(config["data_dir"])

            metrics = Evaluator(repo, config, tmp_path).run()

            self.assertIn("single_modugeo", metrics)
            self.assertIn("single_active_triangulation", metrics)
            self.assertIn("fusion_all", metrics)
            self.assertIn("scheduler_rule", metrics)
            self.assertIn("scheduler_bandit", metrics)
            self.assertGreater(metrics["scheduler_rule"]["Coverage"], 0)


if __name__ == "__main__":
    unittest.main()
