from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import introspective_log_review as ilr  # noqa: E402


class IntrospectiveLogReviewTests(unittest.TestCase):
    def make_batch(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        tmp = tempfile.TemporaryDirectory()
        batch = Path(tmp.name) / "batch"
        iter0 = batch / "targets" / "target_008" / "iter_00"
        iter1 = batch / "targets" / "target_008" / "iter_01"
        iter0.mkdir(parents=True)
        iter1.mkdir(parents=True)
        target_dir = batch / "targets" / "target_008"
        (target_dir / "target.json").write_text(json.dumps({"target": "derive h = 5R/2"}))
        (target_dir / "target_metrics.json").write_text(json.dumps({"accepted": False}))
        (iter0 / "status.txt").write_text("FAIL\n")
        (iter0 / "problem.judge.json").write_text(json.dumps({
            "overall": "FAIL",
            "primary_overall": "PASS",
            "adversarial": {
                "status": "refuted",
                "criterion": "one_rule_per_edge",
                "reason": "substitution and simplification fused",
            },
        }))
        (iter1 / "status.txt").write_text("verify_fail\n")
        (iter1 / "problem.verifier.json").write_text(json.dumps({
            "edge_summary": {"PASS": 1, "FAIL": 1},
            "edge_results": [
                {
                    "from": "n6",
                    "to": "n7",
                    "rule": "divide_both_sides",
                    "status": "FAIL",
                    "reason": "also swapped sides",
                }
            ],
        }))
        (iter1 / "addendum.md").write_text("Repair previous fused substitution.\n")
        return tmp, batch

    def test_prompt_points_reviewer_at_files_and_hypothesis_schema(self) -> None:
        tmp, batch = self.make_batch()
        self.addCleanup(tmp.cleanup)

        target_dir = ilr.find_target_dir(batch, "target_008")
        prompt = ilr.build_prompt(batch, target_dir)

        self.assertIn("targets/target_008/target_metrics.json", prompt)
        self.assertIn("targets/target_008/iter_00/problem.judge.json", prompt)
        self.assertIn("targets/target_008/iter_01/problem.verifier.json", prompt)
        self.assertIn("hypothesis_for_next_change", prompt)
        self.assertIn("experiment_to_validate", prompt)
        self.assertIn("Return JSON only", prompt)

    def test_write_prompt_uses_stable_artifact_name(self) -> None:
        tmp, batch = self.make_batch()
        self.addCleanup(tmp.cleanup)

        prompt_path = ilr.write_prompt(batch, "target_008", batch)

        self.assertEqual(prompt_path.name, "introspective_log_review_target_008_prompt.md")
        self.assertTrue(prompt_path.exists())

    def test_codex_command_sets_model_effort_and_read_only_output(self) -> None:
        output = Path("/tmp/out.json")
        cmd = ilr.codex_command(
            codex_bin="codex",
            model="gpt-5.5",
            reasoning_effort="xhigh",
            sandbox="read-only",
            output_path=output,
        )

        self.assertEqual(cmd[:4], ["codex", "exec", "-C", str(ilr.PROJECT_ROOT)])
        self.assertIn("--model", cmd)
        self.assertIn("gpt-5.5", cmd)
        self.assertIn('model_reasoning_effort="xhigh"', cmd)
        self.assertIn("--sandbox", cmd)
        self.assertIn("read-only", cmd)
        self.assertIn(str(output), cmd)
        self.assertEqual(cmd[-1], "-")


if __name__ == "__main__":
    unittest.main()
