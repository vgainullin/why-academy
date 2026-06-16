from __future__ import annotations

import json
import re
import shutil
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

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


if __name__ == "__main__":
    unittest.main()
