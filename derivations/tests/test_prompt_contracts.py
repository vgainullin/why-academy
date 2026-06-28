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
        self.assertIn("no explicit", prompt)
        self.assertIn("strongly prefer", prompt)
        self.assertIn("`BUG_INVESTIGATE` over `CONTINUE_EPOCH`", prompt)
        self.assertIn("Validator proposal thresholds do not block this route", prompt)

    def test_every_non_pass_judge_outcome_must_be_accounted_for(self) -> None:
        prompt = (PROJECT_ROOT / "derivations" / "prompts" /
                  "outer_loop_epoch.md").read_text()

        self.assertIn("Every non-PASS `judge_eval.overall` must be", prompt)
        self.assertIn("`JUDGE_REJECTED`, `JUDGE_AGGREGATION_MISMATCH`, or", prompt)
        self.assertIn("`JUDGE_ERROR`", prompt)

    def test_adversarial_judge_context_controls_attempt_classification(self) -> None:
        prompt = (PROJECT_ROOT / "derivations" / "prompts" /
                  "outer_loop_epoch.md").read_text()

        self.assertIn("primary_overall", prompt)
        self.assertIn("judge_eval.adversarial.status == \"refuted\"", prompt)
        self.assertIn("judge_eval.adversarial.status == \"error\"", prompt)
        self.assertIn("judge_eval.consistency_error", prompt)
        self.assertIn("Adversarial metadata is authoritative context", prompt)

    def test_completed_bug_investigation_routes_to_implementation(self) -> None:
        prompt = (PROJECT_ROOT / "derivations" / "prompts" /
                  "outer_loop_epoch.md").read_text()

        self.assertIn("proposal_bug_*.md", prompt)
        self.assertIn("Do not investigate it again", prompt)
        self.assertIn("route to", prompt)
        self.assertIn("`IMPLEMENT`", prompt)
        self.assertIn("proposal_paths", prompt)

    def test_experiment_is_post_implementation(self) -> None:
        prompt = (PROJECT_ROOT / "derivations" / "prompts" /
                  "outer_loop_epoch.md").read_text()

        self.assertIn("proceed to `EXPERIMENT` after", prompt)
        self.assertIn("A/B experiment after implementation", prompt)
        self.assertIn("experiment_spec", prompt)
        self.assertIn("success_criteria", prompt)
        self.assertIn("failure_policy", prompt)
        self.assertIn("PARK_TREATMENT", prompt)
        self.assertIn("without adding a meta-meta loop", prompt)

    def test_structured_eval_verdicts_are_authoritative(self) -> None:
        prompt = (PROJECT_ROOT / "derivations" / "prompts" /
                  "outer_loop_epoch.md").read_text()

        self.assertIn("eval_verdict.json", prompt)
        self.assertIn("authoritative implementation/evaluation record", prompt)
        self.assertIn("promotion/regression contract", prompt)

    def test_bug_investigate_requires_replayable_bugfix_fixture(self) -> None:
        prompt = (PROJECT_ROOT / "derivations" / "prompts" /
                  "bug_investigate_candidate.md").read_text()

        self.assertIn("current closure harness can replay", prompt)
        self.assertIn("judge_eval.verdicts", prompt)
        self.assertIn("If you cannot provide one of those replayable forms", prompt)

    def test_implement_prompt_allows_only_typed_judge_bugfixes(self) -> None:
        prompt = (PROJECT_ROOT / "derivations" / "prompts" /
                  "implement_proposal.md").read_text()

        self.assertIn("Judge/system BUGFIX", prompt)
        self.assertIn("judge.normalize_primary_record", prompt)
        self.assertIn("**Do NOT modify** `judge.py` unless", prompt)
        self.assertIn("a fenced JSON", prompt)


if __name__ == "__main__":
    unittest.main()
