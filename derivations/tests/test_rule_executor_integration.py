from __future__ import annotations

import concurrent.futures
import json
import re
import shutil
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import inner_evolve  # noqa: E402
from inner_evolve import process_target  # noqa: E402


class InvalidPlanPool:
    model = "fixture"

    def submit(self, prompt: str) -> dict:
        self.prompt = prompt
        return {"text": "{not-json", "result": {}}


class NormalizationFusionPool:
    model = "fixture"

    def submit(self, prompt: str) -> dict:
        self.prompt = prompt
        match = re.search(r"`id` must be exactly `([^`]+)`", prompt)
        problem_id = match.group(1) if match else "missing_problem_id"
        plan = {
            "id": problem_id,
            "root_ref": "energy_reduced",
            "goal_ref": "combined",
            "facts": [
                {
                    "ref": "energy_reduced",
                    "expr": (
                        "Eq(Add(Mul(Integer(2), Symbol('R')), "
                        "Mul(Rational(1, 2), Pow(Symbol('g'), Integer(-1)), Pow(v, Integer(2))), "
                        "evaluate=False), Symbol('h'), evaluate=False)"
                    ),
                }
            ],
            "steps": [
                {
                    "id": "substitute_v2",
                    "from": "energy_reduced",
                    "rule": "substitute_value",
                    "rule_args": {"symbol": "v**2", "replacement": "Symbol('g')*Symbol('R')"},
                },
                {
                    "id": "combined",
                    "from": "substitute_v2",
                    "rule": "simplify_expression",
                    "rule_args": {},
                },
            ],
        }
        return {"text": json.dumps(plan), "result": {}}


class RuleExecutorIntegrationTests(unittest.TestCase):
    def test_rule_executor_plan_invalid_writes_failure_artifacts(self) -> None:
        batch_id = "test_rule_executor_process_target"
        batch_dir = DERIVATIONS / "_evolutions" / "batches" / batch_id
        shutil.rmtree(batch_dir, ignore_errors=True)
        try:
            metrics = process_target(
                "solve x + 2 = 5 for x",
                0,
                batch_id,
                InvalidPlanPool(),
                max_iter=1,
                inner_engine="fixture",
                inner_mode="rule_executor",
                experiment_id="rule_executor_ab_test",
                treatment_id="rule_executor",
                judge_engine="fixture",
                evolve_engine="fixture",
                judge_model="fixture",
                evolve_model="fixture",
            )

            iter_dir = batch_dir / "targets" / "target_000" / "iter_00"
            self.assertFalse(metrics["accepted"])
            self.assertEqual(metrics["failure_reason"], "rule_plan_invalid_iter_0")
            self.assertEqual((iter_dir / "status.txt").read_text(), "rule_plan_invalid")
            self.assertTrue((iter_dir / "rule_plan.raw.txt").exists())
            self.assertTrue((iter_dir / "rule_executor_error.json").exists())
            self.assertFalse((iter_dir / "problem.json").exists())
            checkpoint = json.loads((batch_dir / "checkpoint.json").read_text())
            self.assertEqual(checkpoint["inner_mode"], "rule_executor")
            self.assertEqual(checkpoint["treatment_id"], "rule_executor")
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)

    def test_rule_executor_rejects_normalization_induced_fused_substitution(self) -> None:
        batch_id = "test_rule_executor_normalized_fusion"
        batch_dir = DERIVATIONS / "_evolutions" / "batches" / batch_id
        shutil.rmtree(batch_dir, ignore_errors=True)
        try:
            metrics = process_target(
                "derive h = 5R/2 from 2R + v^2/(2g) = h and v^2 = gR",
                0,
                batch_id,
                NormalizationFusionPool(),
                max_iter=1,
                inner_engine="fixture",
                inner_mode="rule_executor",
                experiment_id="rule_executor_ab_test",
                treatment_id="rule_executor",
                judge_engine="fixture",
                evolve_engine="fixture",
                judge_model="fixture",
                evolve_model="fixture",
            )

            iter_dir = batch_dir / "targets" / "target_000" / "iter_00"
            self.assertFalse(metrics["accepted"])
            self.assertEqual(metrics["failure_reason"], "substitution_structural_fail_iter_0")
            self.assertEqual((iter_dir / "status.txt").read_text(), "substitution_structural_fail")

            raw_report = json.loads((iter_dir / "problem.raw.substitution_check.json").read_text())
            normalized_report = json.loads((iter_dir / "problem.substitution_check.json").read_text())
            error = json.loads((iter_dir / "rule_executor_error.json").read_text())

            self.assertEqual(raw_report["status"], "PASS", raw_report)
            self.assertEqual(normalized_report["status"], "FAIL", normalized_report)
            self.assertEqual(error["failure_class"], "substitution_structural_fail")
            self.assertIn("normalized substitution edge", error["error"])
            self.assertTrue((iter_dir / "problem.normalizer.json").exists())
            self.assertFalse((iter_dir / "problem.judge.json").exists())
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)

    def test_rule_executor_boundary_normalization_mode_reaches_local_gates(self) -> None:
        batch_id = "test_rule_executor_boundary_bridge"
        batch_dir = DERIVATIONS / "_evolutions" / "batches" / batch_id
        shutil.rmtree(batch_dir, ignore_errors=True)
        real_run_py = inner_evolve._run_py

        def fake_run_py(*args, cwd=None):
            if args and args[0] == "derivations/judge.py":
                problem_path = Path(args[1])
                problem = json.loads(problem_path.read_text())
                judge_path = problem_path.with_name(problem_path.stem + ".judge.json")
                judge_path.write_text(json.dumps({
                    "judge_version": "fixture",
                    "backend": "fixture",
                    "model": "fixture",
                    "verdicts": [{"overall": "PASS"}],
                    "overall": "PASS",
                    "problem_id": problem["id"],
                }))
                return subprocess.CompletedProcess(args, 0, "fixture judge PASS\n", "")
            return real_run_py(*args, cwd=cwd)

        try:
            with patch.object(inner_evolve, "_run_py", side_effect=fake_run_py):
                metrics = process_target(
                    "derive h = 5R/2",
                    0,
                    batch_id,
                    NormalizationFusionPool(),
                    max_iter=1,
                    inner_engine="fixture",
                    inner_mode="rule_executor",
                    experiment_id="rule_executor_ab_test",
                    treatment_id="rule_executor_normalization_bridge_v1",
                    normalization_mode="preserve-executor-boundaries",
                    judge_engine="fixture",
                    evolve_engine="fixture",
                    judge_model="fixture",
                    evolve_model="fixture",
                )

            iter_dir = batch_dir / "targets" / "target_000" / "iter_00"
            self.assertTrue(metrics["accepted"])
            self.assertEqual((iter_dir / "status.txt").read_text(), "PASS")
            bridge = json.loads((iter_dir / "problem.normalization_bridge.json").read_text())
            self.assertEqual(bridge["status"], "PASS", bridge)
            self.assertEqual(bridge["metrics"]["protected_edges"], 2)
            self.assertEqual(bridge["metrics"]["preserved_edges"], 2)
            normalized_report = json.loads((iter_dir / "problem.substitution_check.json").read_text())
            self.assertEqual(normalized_report["status"], "PASS", normalized_report)
            checkpoint = json.loads((batch_dir / "checkpoint.json").read_text())
            self.assertEqual(checkpoint["normalization_mode"], "preserve-executor-boundaries")
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)

    def test_boundary_normalization_rerun_clears_stale_bridge_failure_artifacts(self) -> None:
        batch_id = "test_rule_executor_boundary_bridge_stale"
        batch_dir = DERIVATIONS / "_evolutions" / "batches" / batch_id
        shutil.rmtree(batch_dir, ignore_errors=True)
        iter_dir = batch_dir / "targets" / "target_000" / "iter_00"
        iter_dir.mkdir(parents=True)
        (batch_dir / "checkpoint.json").write_text(json.dumps({
            "batch_id": batch_id,
            "inner_mode": "rule_executor",
            "experiment_id": "rule_executor_ab_test",
            "treatment_id": "rule_executor_normalization_bridge_v1",
            "normalization_mode": "preserve-executor-boundaries",
            "rule_executor_version": "rule_executor.v1",
            "normalization_bridge_version": "normalization_bridge.v1",
            "substitution_structural_check_version": "substitution_structural_check.v1",
        }))
        stale_payload = {"failure_class": "normalization_boundary_fail"}
        (iter_dir / "normalization_bridge_error.json").write_text(json.dumps(stale_payload))
        (iter_dir / "rule_executor_error.json").write_text(json.dumps(stale_payload))
        (iter_dir / "problem.normalization_bridge_candidate.json").write_text(json.dumps({"id": "stale"}))
        real_run_py = inner_evolve._run_py

        def fake_run_py(*args, cwd=None):
            if args and args[0] == "derivations/judge.py":
                problem_path = Path(args[1])
                problem = json.loads(problem_path.read_text())
                judge_path = problem_path.with_name(problem_path.stem + ".judge.json")
                judge_path.write_text(json.dumps({
                    "judge_version": "fixture",
                    "backend": "fixture",
                    "model": "fixture",
                    "verdicts": [{"overall": "PASS"}],
                    "overall": "PASS",
                    "problem_id": problem["id"],
                }))
                return subprocess.CompletedProcess(args, 0, "fixture judge PASS\n", "")
            return real_run_py(*args, cwd=cwd)

        try:
            with patch.object(inner_evolve, "_run_py", side_effect=fake_run_py):
                metrics = process_target(
                    "derive h = 5R/2",
                    0,
                    batch_id,
                    NormalizationFusionPool(),
                    max_iter=1,
                    inner_engine="fixture",
                    inner_mode="rule_executor",
                    experiment_id="rule_executor_ab_test",
                    treatment_id="rule_executor_normalization_bridge_v1",
                    normalization_mode="preserve-executor-boundaries",
                    judge_engine="fixture",
                    evolve_engine="fixture",
                    judge_model="fixture",
                    evolve_model="fixture",
                )

            self.assertTrue(metrics["accepted"])
            self.assertEqual((iter_dir / "status.txt").read_text(), "PASS")
            self.assertFalse((iter_dir / "normalization_bridge_error.json").exists())
            self.assertFalse((iter_dir / "rule_executor_error.json").exists())
            self.assertFalse((iter_dir / "problem.normalization_bridge_candidate.json").exists())
            bridge = json.loads((iter_dir / "problem.normalization_bridge.json").read_text())
            self.assertEqual(bridge["status"], "PASS", bridge)
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)

    def test_boundary_normalization_rerun_clears_stale_bridge_artifacts_before_plan_parse(self) -> None:
        batch_id = "test_rule_executor_boundary_bridge_stale_early"
        batch_dir = DERIVATIONS / "_evolutions" / "batches" / batch_id
        shutil.rmtree(batch_dir, ignore_errors=True)
        iter_dir = batch_dir / "targets" / "target_000" / "iter_00"
        iter_dir.mkdir(parents=True)
        (batch_dir / "checkpoint.json").write_text(json.dumps({
            "batch_id": batch_id,
            "inner_mode": "rule_executor",
            "experiment_id": "rule_executor_ab_test",
            "treatment_id": "rule_executor_normalization_bridge_v1",
            "normalization_mode": "preserve-executor-boundaries",
            "rule_executor_version": "rule_executor.v1",
            "normalization_bridge_version": "normalization_bridge.v1",
            "substitution_structural_check_version": "substitution_structural_check.v1",
        }))
        stale_payload = {"failure_class": "normalization_boundary_fail"}
        (iter_dir / "problem.normalization_bridge.json").write_text(json.dumps({
            "bridge_version": "normalization_bridge.v1",
            "status": "normalization_boundary_fail",
        }))
        (iter_dir / "problem.normalization_bridge_candidate.json").write_text(json.dumps({"id": "stale"}))
        (iter_dir / "problem.normalizer.json").write_text(json.dumps({"id_map": {"stale": "stale"}}))
        (iter_dir / "normalization_bridge_error.json").write_text(json.dumps(stale_payload))
        (iter_dir / "rule_executor_error.json").write_text(json.dumps(stale_payload))

        try:
            metrics = process_target(
                "solve x + 2 = 5 for x",
                0,
                batch_id,
                InvalidPlanPool(),
                max_iter=1,
                inner_engine="fixture",
                inner_mode="rule_executor",
                experiment_id="rule_executor_ab_test",
                treatment_id="rule_executor_normalization_bridge_v1",
                normalization_mode="preserve-executor-boundaries",
                judge_engine="fixture",
                evolve_engine="fixture",
                judge_model="fixture",
                evolve_model="fixture",
            )

            self.assertFalse(metrics["accepted"])
            self.assertEqual(metrics["failure_reason"], "rule_plan_invalid_iter_0")
            self.assertEqual((iter_dir / "status.txt").read_text(), "rule_plan_invalid")
            self.assertFalse((iter_dir / "problem.normalization_bridge.json").exists())
            self.assertFalse((iter_dir / "problem.normalization_bridge_candidate.json").exists())
            self.assertFalse((iter_dir / "problem.normalizer.json").exists())
            self.assertFalse((iter_dir / "normalization_bridge_error.json").exists())
            error = json.loads((iter_dir / "rule_executor_error.json").read_text())
            self.assertEqual(error["failure_class"], "rule_plan_invalid")
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)

    def test_boundary_normalization_mode_rejects_non_rule_executor(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires inner_mode=rule_executor"):
            process_target(
                "solve x + 2 = 5 for x",
                0,
                "test_rule_executor_boundary_bridge_invalid_mode",
                InvalidPlanPool(),
                max_iter=1,
                inner_engine="fixture",
                inner_mode="json",
                experiment_id="rule_executor_ab_test",
                treatment_id="rule_executor_normalization_bridge_v1",
                normalization_mode="preserve-executor-boundaries",
                judge_engine="fixture",
                evolve_engine="fixture",
                judge_model="fixture",
                evolve_model="fixture",
            )

    def test_boundary_normalization_rejects_incompatible_completed_resume_before_skip(self) -> None:
        batch_id = "test_rule_executor_boundary_bridge_incompatible_resume"
        batch_dir = DERIVATIONS / "_evolutions" / "batches" / batch_id
        shutil.rmtree(batch_dir, ignore_errors=True)
        target_dir = batch_dir / "targets" / "target_000"
        iter_dir = target_dir / "iter_00"
        iter_dir.mkdir(parents=True)
        (batch_dir / "checkpoint.json").write_text(json.dumps({
            "batch_id": batch_id,
            "inner_mode": "rule_executor",
            "experiment_id": "rule_executor_ab_test",
            "treatment_id": "rule_executor",
            "rule_executor_version": "rule_executor.v1",
            "substitution_structural_check_version": "substitution_structural_check.v1",
        }))
        (target_dir / "ACCEPTED.txt").write_text("iter_00")
        (target_dir / "target_metrics.json").write_text(json.dumps({
            "target_index": 0,
            "accepted": True,
            "n_iterations": 1,
        }))
        (iter_dir / "status.txt").write_text("PASS")
        pool = InvalidPlanPool()

        try:
            with self.assertRaisesRegex(
                inner_evolve.BatchResumeContractError,
                "incompatible batch resume metadata",
            ):
                process_target(
                    "solve x + 2 = 5 for x",
                    0,
                    batch_id,
                    pool,
                    max_iter=1,
                    inner_engine="fixture",
                    inner_mode="rule_executor",
                    experiment_id="rule_executor_ab_test",
                    treatment_id="rule_executor_normalization_bridge_v1",
                    normalization_mode="preserve-executor-boundaries",
                    judge_engine="fixture",
                    evolve_engine="fixture",
                    judge_model="fixture",
                    evolve_model="fixture",
                )
            self.assertFalse(hasattr(pool, "prompt"))
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)

    def test_boundary_normalization_rejects_existing_batch_state_without_checkpoint(self) -> None:
        batch_id = "test_rule_executor_boundary_bridge_missing_checkpoint"
        batch_dir = DERIVATIONS / "_evolutions" / "batches" / batch_id
        shutil.rmtree(batch_dir, ignore_errors=True)
        target_dir = batch_dir / "targets" / "target_000"
        target_dir.mkdir(parents=True)
        (target_dir / "FAILED.txt").write_text("rule_executor_coverage_gap_iter_0")
        (target_dir / "target_metrics.json").write_text(json.dumps({
            "target_index": 0,
            "accepted": False,
            "n_iterations": 1,
            "failure_reason": "rule_executor_coverage_gap_iter_0",
        }))

        try:
            with self.assertRaisesRegex(
                inner_evolve.BatchResumeContractError,
                "existing target state has no checkpoint",
            ):
                process_target(
                    "solve x + 2 = 5 for x",
                    0,
                    batch_id,
                    InvalidPlanPool(),
                    max_iter=1,
                    inner_engine="fixture",
                    inner_mode="rule_executor",
                    experiment_id="rule_executor_ab_test",
                    treatment_id="rule_executor_normalization_bridge_v1",
                    normalization_mode="preserve-executor-boundaries",
                    judge_engine="fixture",
                    evolve_engine="fixture",
                    judge_model="fixture",
                    evolve_model="fixture",
                )
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)

    def test_boundary_normalization_parallel_fresh_start_publishes_checkpoint_before_targets(self) -> None:
        batch_id = "test_rule_executor_boundary_bridge_parallel_fresh"
        batch_dir = DERIVATIONS / "_evolutions" / "batches" / batch_id
        checkpoint_path = batch_dir / "checkpoint.json"
        shutil.rmtree(batch_dir, ignore_errors=True)
        first_publish = threading.Event()
        release_first_publish = threading.Event()
        publish_lock = threading.Lock()
        delayed_first_publish = False
        real_link = inner_evolve.os.link

        def delayed_checkpoint_publish(src, dst, *args, **kwargs):
            nonlocal delayed_first_publish
            should_delay = False
            if Path(dst) == checkpoint_path:
                with publish_lock:
                    if not delayed_first_publish:
                        delayed_first_publish = True
                        should_delay = True
                        first_publish.set()
                if should_delay:
                    release_first_publish.wait(5)
            return real_link(src, dst, *args, **kwargs)

        def run_target(target_index: int) -> dict:
            return process_target(
                "solve x + 2 = 5 for x",
                target_index,
                batch_id,
                InvalidPlanPool(),
                max_iter=1,
                inner_engine="fixture",
                inner_mode="rule_executor",
                experiment_id="rule_executor_ab_test",
                treatment_id="rule_executor_normalization_bridge_v1",
                normalization_mode="preserve-executor-boundaries",
                judge_engine="fixture",
                evolve_engine="fixture",
                judge_model="fixture",
                evolve_model="fixture",
            )

        try:
            with patch.object(inner_evolve.os, "link", side_effect=delayed_checkpoint_publish):
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    first = executor.submit(run_target, 0)
                    try:
                        self.assertTrue(first_publish.wait(2))
                        self.assertFalse((batch_dir / "targets").exists())
                        second = executor.submit(run_target, 1)
                        second_metrics = second.result(timeout=10)
                    finally:
                        release_first_publish.set()
                    first_metrics = first.result(timeout=10)

            self.assertEqual(first_metrics["failure_reason"], "rule_plan_invalid_iter_0")
            self.assertEqual(second_metrics["failure_reason"], "rule_plan_invalid_iter_0")
            checkpoint = json.loads(checkpoint_path.read_text())
            self.assertEqual(checkpoint["normalization_mode"], "preserve-executor-boundaries")
            self.assertTrue((batch_dir / "targets" / "target_000" / "target_metrics.json").exists())
            self.assertTrue((batch_dir / "targets" / "target_001" / "target_metrics.json").exists())
        finally:
            release_first_publish.set()
            shutil.rmtree(batch_dir, ignore_errors=True)

    def test_bridge_failure_does_not_leave_stale_verifier_sidecar(self) -> None:
        batch_id = "test_rule_executor_boundary_bridge_fail"
        batch_dir = DERIVATIONS / "_evolutions" / "batches" / batch_id
        shutil.rmtree(batch_dir, ignore_errors=True)
        real_run_py = inner_evolve._run_py

        def fake_run_py(*args, cwd=None):
            if args and args[0] == "derivations/normalization_bridge.py":
                bridge_path = Path(args[args.index("--bridge-report") + 1])
                bridge_path.write_text(json.dumps({
                    "bridge_version": "normalization_bridge.v1",
                    "normalization_mode": "preserve-executor-boundaries",
                    "status": "normalization_boundary_fail",
                    "metrics": {"protected_edges": 1, "preserved_edges": 0},
                }))
                return subprocess.CompletedProcess(args, 1, "fixture bridge FAIL\n", "")
            return real_run_py(*args, cwd=cwd)

        try:
            with patch.object(inner_evolve, "_run_py", side_effect=fake_run_py):
                metrics = process_target(
                    "derive h = 5R/2",
                    0,
                    batch_id,
                    NormalizationFusionPool(),
                    max_iter=1,
                    inner_engine="fixture",
                    inner_mode="rule_executor",
                    experiment_id="rule_executor_ab_test",
                    treatment_id="rule_executor_normalization_bridge_v1",
                    normalization_mode="preserve-executor-boundaries",
                    judge_engine="fixture",
                    evolve_engine="fixture",
                    judge_model="fixture",
                    evolve_model="fixture",
                )

            iter_dir = batch_dir / "targets" / "target_000" / "iter_00"
            self.assertFalse(metrics["accepted"])
            self.assertEqual(metrics["failure_reason"], "normalization_boundary_fail_iter_0")
            self.assertEqual((iter_dir / "status.txt").read_text(), "normalization_boundary_fail")
            self.assertFalse((iter_dir / "problem.verifier.json").exists())
            self.assertTrue((iter_dir / "problem.raw.verifier.json").exists())
            self.assertTrue((iter_dir / "normalization_bridge_error.json").exists())
            self.assertFalse((iter_dir / "problem.judge.json").exists())
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
