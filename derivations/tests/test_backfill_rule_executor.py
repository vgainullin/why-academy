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
from emit_log import _judge_section as emit_log_judge_section  # noqa: E402


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

    def test_adversarial_judge_metadata_is_backfilled(self) -> None:
        batch_id = "test_rule_executor_backfill_judge_adversarial"
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
            }))
            (target / "target.json").write_text(json.dumps({"target": "derive x = 3"}))
            (target / "target_metrics.json").write_text(json.dumps({
                "target_index": 0,
                "accepted": False,
            }))
            (iter_dir / "status.txt").write_text("judge_rejected")
            (iter_dir / "problem.json").write_text(json.dumps({"id": "p_judge"}))
            (iter_dir / "problem.verifier.json").write_text(json.dumps({
                "timestamp": "2026-06-16T00:00:00+00:00",
                "verifier_version": "fixture",
                "n_nodes": 2,
                "n_edges": 1,
                "node_truth": {"TRUE": 2, "FALSE": 0, "ERROR": 0, "NA": 0},
                "edge_summary": {"PASS": 1, "FAIL": 0, "UNCOVERED": 0, "WEAK_PASS": 0, "ERROR": 0},
                "edge_results": [],
            }))
            (iter_dir / "problem.judge.json").write_text(json.dumps({
                "judge_version": "judge.v2",
                "backend": "openrouter",
                "model": "fixture-judge",
                "overall": "FAIL",
                "primary_overall": "PASS",
                "verdicts": {
                    "one_rule_per_edge": {"verdict": "PASS"},
                    "target_goal_reached": {"verdict": "PASS"},
                },
                "adversarial": {
                    "status": "refuted",
                    "criterion": "one_rule_per_edge",
                    "reason": "edge fuses two transformations",
                },
            }))

            n = backfill_batch(batch)

        try:
            self.assertEqual(n, 1)
            rec = json.loads(out_path.read_text().splitlines()[0])
            judge_eval = rec["judge_eval"]
            self.assertEqual(judge_eval["backend"], "openrouter")
            self.assertEqual(judge_eval["overall"], "FAIL")
            self.assertEqual(judge_eval["primary_overall"], "PASS")
            self.assertEqual(judge_eval["adversarial"]["status"], "refuted")
            self.assertEqual(judge_eval["adversarial"]["criterion"], "one_rule_per_edge")
        finally:
            out_path.unlink(missing_ok=True)

    def test_graph_shape_is_backfilled_for_goal_contract_audit(self) -> None:
        batch_id = "test_graph_shape_backfill"
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
            }))
            (target / "target.json").write_text(json.dumps({"target": "solve 4x - 10 = 8x - 2"}))
            (target / "target_metrics.json").write_text(json.dumps({
                "target_index": 0,
                "accepted": True,
                "accepted_at_iter": 0,
            }))
            (iter_dir / "status.txt").write_text("PASS")
            (iter_dir / "problem.json").write_text(json.dumps({
                "id": "p_shape",
                "root_node": "n0",
                "goal_node": "n0",
                "nodes": [{"id": "n0"}, {"id": "n1"}],
                "edges": [{"from": "n0", "to": "n1", "rule": "divide_both_sides"}],
            }))
            (iter_dir / "problem.verifier.json").write_text(json.dumps({
                "timestamp": "2026-06-16T00:00:00+00:00",
                "verifier_version": "fixture",
                "n_nodes": 2,
                "n_edges": 1,
                "node_truth": {"TRUE": 0, "FALSE": 2, "ERROR": 0, "NA": 0},
                "edge_summary": {"PASS": 1, "FAIL": 0, "UNCOVERED": 0, "WEAK_PASS": 0, "ERROR": 0},
                "edge_results": [],
            }))

            n = backfill_batch(batch)

        try:
            self.assertEqual(n, 1)
            rec = json.loads(out_path.read_text().splitlines()[0])
            shape = rec["graph_shape"]
            self.assertEqual(shape["root_node"], "n0")
            self.assertEqual(shape["goal_node"], "n0")
            self.assertFalse(shape["goal_is_terminal"])
            self.assertTrue(shape["goal_reachable_from_root"])
            self.assertEqual(shape["terminal_nodes"], ["n1"])
        finally:
            out_path.unlink(missing_ok=True)

    def test_emit_log_judge_section_preserves_adversarial_metadata(self) -> None:
        judge_eval = emit_log_judge_section({
            "judge_version": "judge.v2",
            "model": "fixture-judge",
            "overall": "ERROR",
            "primary_overall": "PASS",
            "verdicts": {"target_goal_reached": {"verdict": "PASS"}},
            "adversarial": {
                "status": "error",
                "fail_mode": "closed",
                "error": "could not parse adversarial JSON",
            },
            "consistency_error": "overall is non-pass but all criterion verdicts are PASS/SKIP",
        })

        self.assertEqual(judge_eval["backend"], "claude")
        self.assertEqual(judge_eval["primary_overall"], "PASS")
        self.assertEqual(judge_eval["adversarial"]["status"], "error")
        self.assertIn("consistency_error", judge_eval)


if __name__ == "__main__":
    unittest.main()
