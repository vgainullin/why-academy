import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class OuterLoopPromptContractTests(unittest.TestCase):

    def test_judge_aggregation_mismatch_can_route_to_bug_investigate(self) -> None:
        prompt = (PROJECT_ROOT / "derivations" / "prompts" /
                  "outer_loop_epoch.md").read_text()

        self.assertIn("JUDGE_AGGREGATION_MISMATCH", prompt)
        self.assertIn('judge_eval.overall` is `FAIL` or `ERROR`', prompt)
        self.assertIn("every criterion verdict is `PASS` or `SKIP`", prompt)
        self.assertIn("strongly prefer", prompt)
        self.assertIn("`BUG_INVESTIGATE` over `CONTINUE_EPOCH`", prompt)
        self.assertIn("Validator proposal thresholds do not block this route", prompt)

    def test_every_non_pass_judge_outcome_must_be_accounted_for(self) -> None:
        prompt = (PROJECT_ROOT / "derivations" / "prompts" /
                  "outer_loop_epoch.md").read_text()

        self.assertIn("Every non-PASS `judge_eval.overall` must be", prompt)
        self.assertIn("`JUDGE_REJECTED`, `JUDGE_AGGREGATION_MISMATCH`, or", prompt)
        self.assertIn("`JUDGE_ERROR`", prompt)

    def test_completed_bug_investigation_routes_to_implementation(self) -> None:
        prompt = (PROJECT_ROOT / "derivations" / "prompts" /
                  "outer_loop_epoch.md").read_text()

        self.assertIn("proposal_bug_*.md", prompt)
        self.assertIn("Do not investigate it again", prompt)
        self.assertIn("route to", prompt)
        self.assertIn("`IMPLEMENT`", prompt)

    def test_experiment_is_post_implementation(self) -> None:
        prompt = (PROJECT_ROOT / "derivations" / "prompts" /
                  "outer_loop_epoch.md").read_text()

        self.assertIn("proceed to `EXPERIMENT` after", prompt)
        self.assertIn("A/B experiment after implementation", prompt)

    def test_structured_eval_verdicts_are_authoritative(self) -> None:
        prompt = (PROJECT_ROOT / "derivations" / "prompts" /
                  "outer_loop_epoch.md").read_text()

        self.assertIn("eval_verdict.json", prompt)
        self.assertIn("authoritative implementation/evaluation record", prompt)
        self.assertIn("promotion/regression contract", prompt)


if __name__ == "__main__":
    unittest.main()
