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

    def test_bridge_failure_with_stale_verifier_sidecar_is_not_verifier_backed(self) -> None:
        batch_id = "test_rule_executor_backfill_sidecar"
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
                "normalization_mode": "preserve-executor-boundaries",
            }))
            (target / "target.json").write_text(json.dumps({"target": "derive h"}))
            (target / "target_metrics.json").write_text(json.dumps({
                "target_index": 0,
                "accepted": False,
            }))
            (iter_dir / "status.txt").write_text("normalization_boundary_fail")
            (iter_dir / "problem.json").write_text(json.dumps({"id": "p", "nodes": [], "edges": []}))
            (iter_dir / "problem.verifier.json").write_text(json.dumps({
                "timestamp": "2026-06-16T00:00:00+00:00",
                "verifier_version": "fixture",
                "n_nodes": 99,
                "n_edges": 99,
                "node_truth": {"TRUE": 0, "FALSE": 0, "ERROR": 0, "NA": 0},
                "edge_summary": {"PASS": 99, "FAIL": 0, "UNCOVERED": 0, "WEAK_PASS": 0, "ERROR": 0},
                "edge_results": [],
            }))
            (iter_dir / "normalization_bridge_error.json").write_text(json.dumps({
                "failure_class": "normalization_boundary_fail",
                "error": "protected edge collapsed",
            }))
            (iter_dir / "problem.normalization_bridge.json").write_text(json.dumps({
                "bridge_version": "normalization_bridge.v1",
                "normalization_mode": "preserve-executor-boundaries",
                "status": "normalization_boundary_fail",
                "metrics": {"protected_edges": 1, "preserved_edges": 0},
            }))

            n = backfill_batch(batch)

        try:
            self.assertEqual(n, 1)
            rec = json.loads(out_path.read_text().splitlines()[0])
            self.assertEqual(rec["normalization_mode"], "preserve-executor-boundaries")
            self.assertEqual(rec["treatment_failure"]["status"], "normalization_boundary_fail")
            self.assertEqual(rec["normalization_bridge"]["status"], "normalization_boundary_fail")
            self.assertIsNone(rec["verifier_version"])
            self.assertEqual(rec["n_nodes"], 0)
            self.assertEqual(rec["edge_summary"]["PASS"], 0)
        finally:
            out_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
