from __future__ import annotations

import importlib.util
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
    def test_rule_executor_allowance_returns_success_for_expected_failures(self) -> None:
        rc, counts = batch_script.batch_exit_code(
            [
                ("target a", 1, {"failure_reason": "rule_executor_coverage_gap_iter_0"}),
                ("target b", 1, {"failure_reason": "substitution_structural_fail_iter_1"}),
                ("target c", 0, {"accepted": True}),
            ],
            evolution_mode=True,
            inner_mode="rule_executor",
            allow_treatment_failures=True,
        )

        self.assertEqual(rc, 0)
        self.assertEqual(counts["rule_executor_coverage_gap"], 1)
        self.assertEqual(counts["substitution_structural_fail"], 1)

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


if __name__ == "__main__":
    unittest.main()
