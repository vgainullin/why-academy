from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

from ab_compare import ComparisonRefused, compare_batches  # noqa: E402


def issue_keys(exc: ComparisonRefused) -> set[tuple[str, str, str, str | None]]:
    return {
        (
            issue["side"],
            issue["artifact"],
            issue["code"],
            issue.get("field"),
        )
        for issue in exc.issues.get("invalid_targets", [])
    }


def write_target(batch: Path, idx: int, target: str, *, accepted: bool, status: str,
                 failure_reason: str | None = None) -> None:
    target_dir = batch / "targets" / f"target_{idx:03d}"
    iter_dir = target_dir / "iter_00"
    iter_dir.mkdir(parents=True)
    (target_dir / "target.json").write_text(json.dumps({"target": target}))
    metrics = {
        "target_index": idx,
        "accepted": accepted,
        "n_iterations": 1,
        "first_try_pass": accepted,
        "failure_reason": failure_reason,
    }
    if accepted:
        metrics["accepted_at_iter"] = 0
    (target_dir / "target_metrics.json").write_text(json.dumps(metrics))
    (iter_dir / "status.txt").write_text(status)


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


class AbCompareTests(unittest.TestCase):
    def test_compares_paired_control_and_treatment_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "control"
            treatment = root / "treatment"
            control.mkdir()
            treatment.mkdir()
            (control / "checkpoint.json").write_text(json.dumps({
                "batch_id": "control",
                "inner_mode": "json",
                "experiment_id": "ab_test",
            }))
            (treatment / "checkpoint.json").write_text(json.dumps({
                "batch_id": "treatment",
                "inner_mode": "rule_executor",
                "experiment_id": "ab_test",
                "treatment_id": "rule_executor",
            }))
            write_target(control, 0, "solve x", accepted=True, status="PASS")
            write_target(treatment, 0, "solve x", accepted=False,
                         status="rule_executor_coverage_gap",
                         failure_reason="rule_executor_coverage_gap_iter_0")
            write_target(control, 1, "derive y", accepted=False, status="FAIL",
                         failure_reason="judge_fail_iter_0")
            write_target(treatment, 1, "derive y", accepted=True, status="PASS")

            summary = compare_batches(control, treatment, experiment_id="ab_test")

            self.assertEqual(summary["paired"]["n_pairs"], 2)
            self.assertEqual(summary["paired"]["control_accepted"], 1)
            self.assertEqual(summary["paired"]["treatment_accepted"], 1)
            self.assertEqual(summary["paired"]["acceptance_delta"], 0.0)
            self.assertEqual(summary["paired"]["control_only_accepted"], 1)
            self.assertEqual(summary["paired"]["treatment_only_accepted"], 1)
            self.assertEqual(
                summary["treatment_batch"]["treatment_failure_counts"]["rule_executor_coverage_gap"],
                1,
            )

    def test_counts_normalization_bridge_failures_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "control"
            treatment = root / "treatment"
            control.mkdir()
            treatment.mkdir()
            (control / "checkpoint.json").write_text(json.dumps({
                "batch_id": "control",
                "inner_mode": "json",
                "experiment_id": "ab_test",
            }))
            (treatment / "checkpoint.json").write_text(json.dumps({
                "batch_id": "treatment",
                "inner_mode": "rule_executor",
                "experiment_id": "ab_test",
                "treatment_id": "rule_executor_normalization_bridge_v1",
                "normalization_mode": "preserve-executor-boundaries",
            }))
            write_target(control, 0, "derive h", accepted=True, status="PASS")
            write_target(treatment, 0, "derive h", accepted=False,
                         status="normalization_boundary_fail",
                         failure_reason="normalization_boundary_fail_iter_0")
            bridge_path = treatment / "targets" / "target_000" / "iter_00" / "problem.normalization_bridge.json"
            bridge_path.write_text(json.dumps({
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

            summary = compare_batches(control, treatment, experiment_id="ab_test")

            self.assertEqual(
                summary["treatment_batch"]["treatment_failure_counts"]["normalization_boundary_fail"],
                1,
            )
            self.assertEqual(
                summary["treatment_batch"]["normalization_bridge"]["status_counts"]["normalization_boundary_fail"],
                1,
            )
            self.assertEqual(summary["treatment_batch"]["normalization_bridge"]["blocked_merges"], 1)

    def test_bridge_status_counts_do_not_replace_iteration_status_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "control"
            treatment = root / "treatment"
            control.mkdir()
            treatment.mkdir()
            (control / "checkpoint.json").write_text(json.dumps({
                "batch_id": "control",
                "inner_mode": "json",
                "experiment_id": "ab_test",
            }))
            (treatment / "checkpoint.json").write_text(json.dumps({
                "batch_id": "treatment",
                "inner_mode": "rule_executor",
                "experiment_id": "ab_test",
                "treatment_id": "rule_executor_normalization_bridge_v1",
                "normalization_mode": "preserve-executor-boundaries",
            }))
            write_target(control, 0, "derive h", accepted=True, status="PASS")
            write_target(control, 1, "derive y", accepted=True, status="PASS")
            write_target(treatment, 0, "derive h", accepted=True, status="PASS")
            write_target(treatment, 1, "derive y", accepted=False,
                         status="substitution_structural_fail",
                         failure_reason="substitution_structural_fail_iter_0")
            for idx in (0, 1):
                bridge_path = treatment / "targets" / f"target_{idx:03d}" / "iter_00" / "problem.normalization_bridge.json"
                bridge_path.write_text(json.dumps({
                    "bridge_version": "normalization_bridge.v1",
                    "normalization_mode": "preserve-executor-boundaries",
                    "status": "PASS",
                    "metrics": {
                        "protected_edges": 1,
                        "preserved_edges": 1,
                        "collapsed_protected_edges": 0,
                        "blocked_merges": 0,
                        "allowed_noop_drops": 0,
                        "raw_pass_normalized_substitution_fail": 0,
                    },
                }))

            summary = compare_batches(control, treatment, experiment_id="ab_test")

            self.assertEqual(
                summary["treatment_batch"]["iter_status_counts"],
                {"PASS": 1, "substitution_structural_fail": 1},
            )
            self.assertEqual(
                summary["treatment_batch"]["treatment_failure_counts"],
                {"substitution_structural_fail": 1},
            )
            self.assertEqual(
                summary["treatment_batch"]["normalization_bridge"]["status_counts"],
                {"PASS": 2},
            )

    def test_refuses_missing_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "control"
            treatment = root / "treatment"
            control.mkdir()
            treatment.mkdir()
            write_target(control, 0, "solve x", accepted=True, status="PASS")
            write_target(treatment, 0, "solve x", accepted=True, status="PASS")
            write_target(treatment, 1, "derive y", accepted=True, status="PASS")

            with self.assertRaises(ComparisonRefused) as cm:
                compare_batches(control, treatment)

            self.assertEqual(cm.exception.issues["missing_in_control"], [1])

    def test_refuses_mismatched_target_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "control"
            treatment = root / "treatment"
            control.mkdir()
            treatment.mkdir()
            write_target(control, 0, "solve x", accepted=True, status="PASS")
            write_target(treatment, 0, "solve y", accepted=True, status="PASS")

            with self.assertRaises(ComparisonRefused) as cm:
                compare_batches(control, treatment)

            self.assertEqual(cm.exception.issues["target_mismatches"], [0])

    def test_refuses_missing_target_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "control"
            treatment = root / "treatment"
            control.mkdir()
            treatment.mkdir()
            write_target(control, 0, "solve x", accepted=True, status="PASS")
            write_target(treatment, 0, "solve x", accepted=True, status="PASS")
            (treatment / "targets" / "target_000" / "target_metrics.json").unlink()

            with self.assertRaises(ComparisonRefused) as cm:
                compare_batches(control, treatment)

            self.assertIn(
                ("treatment", "target_metrics.json", "missing_file", None),
                issue_keys(cm.exception),
            )

    def test_refuses_corrupt_target_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "control"
            treatment = root / "treatment"
            control.mkdir()
            treatment.mkdir()
            write_target(control, 0, "solve x", accepted=True, status="PASS")
            write_target(treatment, 0, "solve x", accepted=True, status="PASS")
            (treatment / "targets" / "target_000" / "target_metrics.json").write_text("{")

            with self.assertRaises(ComparisonRefused) as cm:
                compare_batches(control, treatment)

            self.assertIn(
                ("treatment", "target_metrics.json", "invalid_json", None),
                issue_keys(cm.exception),
            )

    def test_refuses_bad_target_json_artifacts(self) -> None:
        cases = [
            ("missing", lambda path: path.unlink(), "missing_file", None),
            ("corrupt", lambda path: path.write_text("{"), "invalid_json", None),
            ("empty", lambda path: path.write_text(json.dumps({"target": "  "})), "empty_target_text", "target"),
        ]
        for name, mutate, code, field in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                control = root / "control"
                treatment = root / "treatment"
                control.mkdir()
                treatment.mkdir()
                write_target(control, 0, "solve x", accepted=True, status="PASS")
                write_target(treatment, 0, "solve x", accepted=True, status="PASS")
                mutate(treatment / "targets" / "target_000" / "target.json")

                with self.assertRaises(ComparisonRefused) as cm:
                    compare_batches(control, treatment)

                self.assertIn(
                    ("treatment", "target.json", code, field),
                    issue_keys(cm.exception),
                )

    def test_refuses_missing_required_metrics_without_defaulting_false(self) -> None:
        for field in ("accepted", "first_try_pass"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                control = root / "control"
                treatment = root / "treatment"
                control.mkdir()
                treatment.mkdir()
                write_target(control, 0, "solve x", accepted=True, status="PASS")
                write_target(treatment, 0, "solve x", accepted=True, status="PASS")
                metrics_path = treatment / "targets" / "target_000" / "target_metrics.json"
                metrics = json.loads(metrics_path.read_text())
                del metrics[field]
                metrics_path.write_text(json.dumps(metrics))

                with self.assertRaises(ComparisonRefused) as cm:
                    compare_batches(control, treatment)

                self.assertIn(
                    ("treatment", "target_metrics.json", "missing_required_metric", field),
                    issue_keys(cm.exception),
                )

    def test_cli_writes_comparison_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "control"
            treatment = root / "treatment"
            control.mkdir()
            treatment.mkdir()
            (control / "checkpoint.json").write_text(json.dumps({"batch_id": "control", "inner_mode": "json"}))
            (treatment / "checkpoint.json").write_text(json.dumps({
                "batch_id": "treatment",
                "inner_mode": "rule_executor",
                "treatment_id": "rule_executor",
            }))
            write_target(control, 0, "solve x", accepted=True, status="PASS")
            write_target(treatment, 0, "solve x", accepted=True, status="PASS")

            result = subprocess.run(
                [
                    sys.executable,
                    "derivations/ab_compare.py",
                    "--control",
                    str(control),
                    "--treatment",
                    str(treatment),
                    "--experiment-id",
                    "ab_test",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((treatment / "ab_comparison.json").exists())
            self.assertTrue((treatment / "ab_comparison.md").exists())

    def test_cli_refuses_incomplete_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "control"
            treatment = root / "treatment"
            control.mkdir()
            treatment.mkdir()
            write_target(control, 0, "solve x", accepted=True, status="PASS")
            write_target(treatment, 0, "solve x", accepted=True, status="PASS")
            write_target(treatment, 1, "derive y", accepted=True, status="PASS")

            result = subprocess.run(
                [
                    sys.executable,
                    "derivations/ab_compare.py",
                    "--control",
                    str(control),
                    "--treatment",
                    str(treatment),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("comparison_refused", result.stderr)
            self.assertFalse((treatment / "ab_comparison.json").exists())

    def test_cli_refuses_corrupt_target_metrics_with_machine_readable_issue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "control"
            treatment = root / "treatment"
            control.mkdir()
            treatment.mkdir()
            write_target(control, 0, "solve x", accepted=True, status="PASS")
            write_target(treatment, 0, "solve x", accepted=True, status="PASS")
            (treatment / "targets" / "target_000" / "target_metrics.json").write_text("{")

            result = subprocess.run(
                [
                    sys.executable,
                    "derivations/ab_compare.py",
                    "--control",
                    str(control),
                    "--treatment",
                    str(treatment),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(result.returncode, 2)
            refusal = json.loads(result.stderr)
            self.assertEqual(refusal["error"], "comparison_refused")
            self.assertIn(
                ("treatment", "target_metrics.json", "invalid_json", None),
                {
                    (
                        issue["side"],
                        issue["artifact"],
                        issue["code"],
                        issue.get("field"),
                    )
                    for issue in refusal["issues"]["invalid_targets"]
                },
            )
            self.assertFalse((treatment / "ab_comparison.json").exists())

    def test_recomputes_accepted_substitution_from_problem_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = root / "control"
            treatment = root / "treatment"
            control.mkdir()
            treatment.mkdir()
            (control / "checkpoint.json").write_text(json.dumps({"batch_id": "control", "inner_mode": "json"}))
            (treatment / "checkpoint.json").write_text(json.dumps({
                "batch_id": "treatment",
                "inner_mode": "rule_executor",
                "treatment_id": "rule_executor",
            }))
            write_target(control, 0, "derive h", accepted=True, status="PASS")
            write_target(treatment, 0, "derive h", accepted=True, status="PASS")

            iter_dir = treatment / "targets" / "target_000" / "iter_00"
            (iter_dir / "problem.json").write_text(json.dumps(fused_substitution_problem()))
            (iter_dir / "problem.substitution_check.json").write_text(json.dumps({
                "status": "PASS",
                "n_inspected": 1,
                "failures": [],
                "parse_errors": [],
            }))

            summary = compare_batches(control, treatment, experiment_id="ab_test")

            self.assertEqual(summary["treatment_batch"]["accepted_substitution"]["n_failed_edges"], 1)


if __name__ == "__main__":
    unittest.main()
