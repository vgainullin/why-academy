from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

from backfill_logs import backfill_batch  # noqa: E402


class BackfillRuleExecutorTests(unittest.TestCase):
    def test_pregraph_coverage_gap_is_backfilled(self) -> None:
        batch_id = "test_rule_executor_backfill"
        out_path = DERIVATIONS / "logs" / "epoch_999" / f"batch_{batch_id}.jsonl"
        out_path.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp) / batch_id
            target = batch / "targets" / "target_000"
            iter_dir = target / "iter_00"
            iter_dir.mkdir(parents=True)
            (batch / "checkpoint.json").write_text(json.dumps({
                "batch_id": batch_id,
                "epoch": 999,
                "prompt_version": "test_prompt",
                "validator_version": "test_validator",
                "config_version": "test_config",
                "inner_engine": "fixture",
                "inner_model": "fixture",
                "inner_mode": "rule_executor",
                "experiment_id": "rule_executor_ab_test",
                "treatment_id": "rule_executor",
            }))
            (target / "target.json").write_text(json.dumps({"target": "solve x + 2 = 5 for x"}))
            (target / "target_metrics.json").write_text(json.dumps({
                "target_index": 0,
                "accepted": False,
            }))
            (iter_dir / "status.txt").write_text("rule_executor_coverage_gap")
            (iter_dir / "rule_executor_error.json").write_text(json.dumps({
                "failure_class": "rule_executor_coverage_gap",
                "error": "unsupported executor rule 'solve_entire_problem'",
            }))

            n = backfill_batch(batch)

        try:
            self.assertEqual(n, 1)
            lines = out_path.read_text().splitlines()
            self.assertEqual(len(lines), 1)
            rec = json.loads(lines[0])
            self.assertEqual(rec["inner_mode"], "rule_executor")
            self.assertEqual(rec["treatment_failure"]["status"], "rule_executor_coverage_gap")
            self.assertEqual(rec["n_nodes"], 0)
        finally:
            out_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
