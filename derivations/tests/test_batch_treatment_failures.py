from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / "scripts" / "batch.py"
SPEC = importlib.util.spec_from_file_location("batch_script", BATCH_PATH)
assert SPEC is not None and SPEC.loader is not None
batch_script = importlib.util.module_from_spec(SPEC)
sys.modules["batch_script"] = batch_script
SPEC.loader.exec_module(batch_script)


class BatchTreatmentFailureTests(unittest.TestCase):
    def test_engine_preflight_rejects_local_claude_inner(self) -> None:
        os.environ.pop("ALLOW_LOCAL_CLAUDE", None)

        error = batch_script.batch_engine_preflight(
            {"adversarial_judge": {"enabled": False}},
            {"inner": "claude", "judge": "deepseek", "evolve": "codex"},
        )

        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("inner", error)
        self.assertIn("local Claude Code engine is disabled", error)

    def test_engine_preflight_rejects_local_claude_adversarial(self) -> None:
        os.environ.pop("ALLOW_LOCAL_CLAUDE", None)

        error = batch_script.batch_engine_preflight(
            {"adversarial_judge": {"enabled": True, "engine": "claude"}},
            {"inner": "codex", "judge": "deepseek", "evolve": "codex"},
        )

        self.assertIsNotNone(error)
        assert error is not None
        self.assertIn("adversarial_judge", error)
        self.assertIn("local Claude Code engine is disabled", error)

    def test_engine_preflight_accepts_openrouter_adversarial(self) -> None:
        error = batch_script.batch_engine_preflight(
            {"adversarial_judge": {"enabled": True, "engine": "openrouter"}},
            {"inner": "codex", "judge": "deepseek", "evolve": "codex"},
        )

        self.assertIsNone(error)

    def test_pool_preflight_writes_batch_error_before_targets(self) -> None:
        class BrokenPool:
            def preflight(self) -> dict:
                raise RuntimeError("startup failed")

        batch_id = "test_batch_pool_preflight_failure"
        batch_dir = ROOT / "derivations" / "_evolutions" / "batches" / batch_id
        shutil.rmtree(batch_dir, ignore_errors=True)

        try:
            ok, error = batch_script.run_pool_preflight(batch_id, BrokenPool())

            self.assertFalse(ok)
            self.assertIn("startup failed", error or "")
            sidecar = json.loads((batch_dir / "preflight_error.json").read_text())
            self.assertEqual(sidecar["failure_class"], "worker_pool_preflight_failed")
            self.assertIn("startup failed", sidecar["error"])
            self.assertFalse((batch_dir / "targets").exists())
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)

    def test_rule_executor_allowance_returns_success_for_expected_failures(self) -> None:
        rc, counts = batch_script.batch_exit_code(
            [
                ("target a", 1, {"failure_reason": "rule_executor_coverage_gap_iter_0"}),
                ("target b", 1, {"failure_reason": "substitution_structural_fail_iter_1"}),
                ("target d", 1, {"failure_reason": "normalization_boundary_fail_iter_0"}),
                ("target c", 0, {"accepted": True}),
            ],
            evolution_mode=True,
            inner_mode="rule_executor",
            allow_treatment_failures=True,
        )

        self.assertEqual(rc, 0)
        self.assertEqual(counts["rule_executor_coverage_gap"], 1)
        self.assertEqual(counts["substitution_structural_fail"], 1)
        self.assertEqual(counts["normalization_boundary_fail"], 1)

    def test_allowance_does_not_mask_unexpected_failures(self) -> None:
        rc, counts = batch_script.batch_exit_code(
            [
                ("target a", 1, {"failure_reason": "rule_executor_coverage_gap_iter_0"}),
                ("target b", 1, {"failure_reason": "judge_fail_iter_1"}),
            ],
            evolution_mode=True,
            inner_mode="rule_executor",
            allow_treatment_failures=True,
        )

        self.assertEqual(rc, 1)
        self.assertEqual(counts["rule_executor_coverage_gap"], 1)
        self.assertEqual(counts["unexpected"], 1)

    def test_allowance_requires_rule_executor_mode(self) -> None:
        rc, counts = batch_script.batch_exit_code(
            [("target a", 1, {"failure_reason": "rule_executor_coverage_gap_iter_0"})],
            evolution_mode=True,
            inner_mode="json",
            allow_treatment_failures=True,
        )

        self.assertEqual(rc, 1)
        self.assertEqual(counts, {})

    def test_bridge_resume_preflight_rejects_incompatible_checkpoint(self) -> None:
        batch_id = "test_batch_bridge_incompatible_resume"
        batch_dir = ROOT / "derivations" / "_evolutions" / "batches" / batch_id
        shutil.rmtree(batch_dir, ignore_errors=True)
        batch_dir.mkdir(parents=True)
        (batch_dir / "checkpoint.json").write_text(json.dumps({
            "batch_id": batch_id,
            "inner_mode": "rule_executor",
            "experiment_id": "rule_executor_ab_test",
            "treatment_id": "rule_executor",
            "rule_executor_version": "rule_executor.v1",
            "substitution_structural_check_version": "substitution_structural_check.v1",
        }))

        try:
            error = batch_script.batch_resume_preflight(
                batch_id,
                inner_mode="rule_executor",
                experiment_id="rule_executor_ab_test",
                treatment_id="rule_executor_normalization_bridge_v1",
                normalization_mode="preserve-executor-boundaries",
            )

            self.assertIsNotNone(error)
            assert error is not None
            self.assertIn("incompatible batch resume metadata", error)
            self.assertIn("treatment_id", error)
            self.assertIn("normalization_mode", error)
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)

    def test_bridge_resume_preflight_rejects_missing_checkpoint_with_existing_state(self) -> None:
        batch_id = "test_batch_bridge_missing_checkpoint"
        batch_dir = ROOT / "derivations" / "_evolutions" / "batches" / batch_id
        shutil.rmtree(batch_dir, ignore_errors=True)
        (batch_dir / "targets" / "target_000").mkdir(parents=True)

        try:
            error = batch_script.batch_resume_preflight(
                batch_id,
                inner_mode="rule_executor",
                experiment_id="rule_executor_ab_test",
                treatment_id="rule_executor_normalization_bridge_v1",
                normalization_mode="preserve-executor-boundaries",
            )

            self.assertIsNotNone(error)
            assert error is not None
            self.assertIn("existing target state has no checkpoint", error)
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)

    def test_bridge_resume_preflight_allows_fresh_batch_id(self) -> None:
        batch_id = "test_batch_bridge_fresh_resume"
        batch_dir = ROOT / "derivations" / "_evolutions" / "batches" / batch_id
        shutil.rmtree(batch_dir, ignore_errors=True)

        error = batch_script.batch_resume_preflight(
            batch_id,
            inner_mode="rule_executor",
            experiment_id="rule_executor_ab_test",
            treatment_id="rule_executor_normalization_bridge_v1",
            normalization_mode="preserve-executor-boundaries",
        )

        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
