from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def fused_substitution_problem() -> dict:
    return {
        "id": "fused_substitution",
        "root_node": "n0",
        "goal_node": "n1",
        "nodes": [
            {
                "id": "n0",
                "sympy_srepr": (
                    "Eq(Add(Mul(Integer(2), Symbol('R')), "
                    "Mul(Rational(1, 2), Pow(Symbol('g'), Integer(-1)), Pow(v, Integer(2))), "
                    "evaluate=False), Symbol('h'), evaluate=False)"
                ),
            },
            {"id": "n1", "sympy_srepr": "Eq(Mul(Rational(5, 2), Symbol('R')), Symbol('h'))"},
        ],
        "edges": [
            {
                "from": "n0",
                "to": "n1",
                "rule": "substitute_value",
                "rule_args": {"symbol": "v**2", "replacement": "Symbol('g')*Symbol('R')"},
            }
        ],
    }


class CoalesceTreatmentMetricsTests(unittest.TestCase):
    def run_coalesce(self, batch: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "derivations/coalesce.py", str(batch)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_treatment_batch_writes_metrics_but_blocks_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp) / "treatment_batch"
            target0 = batch / "targets" / "target_000"
            iter0 = target0 / "iter_00"
            iter0.mkdir(parents=True)
            target1 = batch / "targets" / "target_001"
            iter1 = target1 / "iter_00"
            iter1.mkdir(parents=True)

            (batch / "checkpoint.json").write_text(json.dumps({
                "batch_id": "treatment_batch",
                "epoch": 1,
                "prompt_version": "test",
                "validator_version": "test",
                "inner_mode": "rule_executor",
                "experiment_id": "rule_executor_ab_test",
                "treatment_id": "rule_executor",
            }))
            (target0 / "target.json").write_text(json.dumps({"target": "solve x + 2 = 5 for x"}))
            (target0 / "target_metrics.json").write_text(json.dumps({
                "target_index": 0,
                "accepted": False,
                "n_iterations": 1,
                "failure_reason": "rule_executor_coverage_gap_iter_0",
            }))
            (iter0 / "status.txt").write_text("rule_executor_coverage_gap")
            (iter0 / "rule_executor_error.json").write_text(json.dumps({
                "failure_class": "rule_executor_coverage_gap",
                "error": "unsupported executor rule",
            }))
            (iter0 / "problem.normalization_bridge.json").write_text(json.dumps({
                "bridge_version": "normalization_bridge.v1",
                "normalization_mode": "preserve-executor-boundaries",
                "status": "normalization_boundary_fail",
                "metrics": {
                    "protected_edges": 2,
                    "preserved_edges": 1,
                    "collapsed_protected_edges": 1,
                    "blocked_merges": 1,
                    "allowed_noop_drops": 0,
                    "raw_pass_normalized_substitution_fail": 1,
                },
            }))
            (iter0 / "variant.md").write_text("")

            (target1 / "target.json").write_text(json.dumps({"target": "derive h"}))
            (target1 / "target_metrics.json").write_text(json.dumps({
                "target_index": 1,
                "accepted": True,
                "accepted_at_iter": 0,
                "first_try_pass": True,
                "n_iterations": 1,
            }))
            (iter1 / "status.txt").write_text("PASS")
            (iter1 / "problem.json").write_text(json.dumps(fused_substitution_problem()))
            (iter1 / "problem.substitution_check.json").write_text(json.dumps({
                "status": "PASS",
                "n_inspected": 1,
                "failures": [],
                "parse_errors": [],
            }))
            (iter1 / "variant.md").write_text("")

            result = self.run_coalesce(batch)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            metrics = json.loads((batch / "batch_metrics.json").read_text())
            self.assertTrue(metrics["is_treatment_batch"])
            self.assertTrue(metrics["promotion_disabled"])
            self.assertEqual(metrics["treatment_failure_counts"]["rule_executor_coverage_gap"], 1)
            self.assertEqual(metrics["substitution_structural"]["n_accepted_failed_edges"], 1)
            self.assertEqual(metrics["normalization_bridge"]["status_counts"]["normalization_boundary_fail"], 1)
            self.assertEqual(metrics["normalization_bridge"]["collapsed_protected_edges"], 1)
            proposal = (batch / "promote_proposal.md").read_text()
            self.assertIn("Promotion disabled for this batch", proposal)


if __name__ == "__main__":
    unittest.main()
