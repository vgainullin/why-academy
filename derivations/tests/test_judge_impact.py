from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import judge_impact as ji  # noqa: E402


class JudgeImpactTests(unittest.TestCase):
    def test_refuted_primary_pass_counts_as_material_candidate_delta(self) -> None:
        row = ji.candidate_row(
            Path("/tmp/batches/b/targets/target_000/iter_00/problem.json"),
            {
                "problem_id": "p",
                "primary_overall": "PASS",
                "overall": "FAIL",
                "adversarial": {"status": "refuted", "reason": "n1 -> n2 fuses two rules"},
            },
        )
        self.assertTrue(row["changed"])
        self.assertEqual(row["impact"], "blocked_by_refutation")

    def test_target_delay_is_material(self) -> None:
        rows = [
            {
                "target_id": "target_000",
                "target": "t",
                "iter": "iter_00",
                "iter_number": 0,
                "primary_overall": "PASS",
                "hardened_overall": "FAIL",
                "changed": True,
                "impact": "blocked_by_refutation",
                "problem_id": "p0",
            },
            {
                "target_id": "target_000",
                "target": "t",
                "iter": "iter_01",
                "iter_number": 1,
                "primary_overall": "PASS",
                "hardened_overall": "PASS",
                "changed": False,
                "impact": "accepted_by_both",
                "problem_id": "p1",
            },
        ]
        summary = ji.summarize(rows)
        self.assertTrue(summary["material_difference"])
        self.assertEqual(summary["changed_targets"][0]["impact"], "delayed_acceptance")


if __name__ == "__main__":
    unittest.main()
