from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import judge  # noqa: E402


class ValidateRefutationTests(unittest.TestCase):
    def test_valid_refutation(self) -> None:
        ok, _ = judge.validate_refutation(
            {"refuted": True, "criterion": "one_rule_per_edge", "reason": "n1->n2 fuses two rules"})
        self.assertTrue(ok)

    def test_valid_uphold(self) -> None:
        ok, _ = judge.validate_refutation({"refuted": False, "criterion": None, "reason": ""})
        self.assertTrue(ok)

    def test_uphold_with_criterion_rejected(self) -> None:
        ok, why = judge.validate_refutation(
            {"refuted": False, "criterion": "target_goal_reached", "reason": ""})
        self.assertFalse(ok)
        self.assertIn("criterion", why)

    def test_uphold_with_reason_rejected(self) -> None:
        ok, why = judge.validate_refutation(
            {"refuted": False, "criterion": None, "reason": "No concrete violation."})
        self.assertFalse(ok)
        self.assertIn("reason", why)

    def test_non_bool_refuted_rejected(self) -> None:
        ok, why = judge.validate_refutation({"refuted": "yes"})
        self.assertFalse(ok)
        self.assertIn("boolean", why)

    def test_refutation_without_valid_criterion_rejected(self) -> None:
        ok, _ = judge.validate_refutation({"refuted": True, "criterion": "vibes", "reason": "bad"})
        self.assertFalse(ok)

    def test_refutation_without_reason_rejected(self) -> None:
        ok, _ = judge.validate_refutation(
            {"refuted": True, "criterion": "target_goal_reached", "reason": "  "})
        self.assertFalse(ok)


class ApplyAdversarialTests(unittest.TestCase):
    def _pass_record(self) -> dict:
        return {"problem_id": "p", "overall": "PASS", "verdicts": {}}

    def test_refutation_flips_to_fail(self) -> None:
        out = judge.apply_adversarial(
            self._pass_record(),
            {"status": "refuted", "criterion": "one_rule_per_edge", "reason": "fused"})
        self.assertEqual(out["overall"], "FAIL")
        self.assertEqual(out["primary_overall"], "PASS")

    def test_uphold_keeps_pass(self) -> None:
        out = judge.apply_adversarial(self._pass_record(), {"status": "upheld", "reason": ""})
        self.assertEqual(out["overall"], "PASS")

    def test_error_fails_closed_by_default(self) -> None:
        out = judge.apply_adversarial(
            self._pass_record(), {"status": "error", "fail_mode": "closed", "error": "timeout"})
        self.assertEqual(out["overall"], "ERROR")

    def test_error_can_fail_open(self) -> None:
        out = judge.apply_adversarial(
            self._pass_record(), {"status": "error", "fail_mode": "open", "error": "timeout"})
        self.assertEqual(out["overall"], "PASS")


class ExtractAdversarialJsonTests(unittest.TestCase):
    def test_extracts_fenced_json_after_prose(self) -> None:
        parsed = judge._extract_json(
            "No violation.\n\n```json\n"
            '{"refuted": false, "criterion": null, "reason": ""}'
            "\n```"
        )

        self.assertEqual(parsed["refuted"], False)
        self.assertIsNone(parsed["criterion"])

    def test_prefers_fenced_json_over_earlier_braces(self) -> None:
        parsed = judge._extract_json(
            "Ignore this set {not json}.\n\n```json\n"
            '{"refuted": true, "criterion": "one_rule_per_edge", "reason": "fused"}'
            "\n```"
        )

        self.assertEqual(parsed["refuted"], True)
        self.assertEqual(parsed["criterion"], "one_rule_per_edge")


class NormalizePrimaryRecordTests(unittest.TestCase):
    def test_nonpass_with_only_pass_skip_criteria_is_explicit_error(self) -> None:
        out = judge.normalize_primary_record({
            "overall": "FAIL",
            "verdicts": {
                "one_rule_per_edge": {"verdict": "PASS"},
                "given_facts_visible": {"verdict": "SKIP"},
                "target_goal_reached": {"verdict": "PASS"},
            },
        })

        self.assertEqual(out["overall"], "ERROR")
        self.assertIn("consistency_error", out)

    def test_failed_criterion_explains_fail(self) -> None:
        out = judge.normalize_primary_record({
            "overall": "FAIL",
            "verdicts": {
                "one_rule_per_edge": {"verdict": "FAIL"},
                "given_facts_visible": {"verdict": "SKIP"},
            },
        })

        self.assertEqual(out["overall"], "FAIL")
        self.assertNotIn("consistency_error", out)

    def test_missing_criterion_verdict_is_not_the_pass_skip_mismatch(self) -> None:
        out = judge.normalize_primary_record({
            "overall": "FAIL",
            "verdicts": {
                "one_rule_per_edge": {"verdict": "PASS"},
                "given_facts_visible": None,
            },
        })

        self.assertEqual(out["overall"], "FAIL")
        self.assertNotIn("consistency_error", out)

    def test_repairs_adversarial_parse_error_uphold_from_raw_tail(self) -> None:
        out = judge.normalize_primary_record({
            "overall": "ERROR",
            "primary_overall": "PASS",
            "verdicts": {
                "one_rule_per_edge": {"verdict": "PASS"},
                "given_facts_visible": {"verdict": "SKIP"},
                "target_goal_reached": {"verdict": "PASS"},
            },
            "adversarial": {
                "status": "error",
                "error": "could not parse adversarial JSON",
                "raw_tail": (
                    "No violation.\n\n```json\n"
                    '{"refuted": false, "criterion": null, "reason": ""}'
                    "\n```"
                ),
            },
        })

        self.assertEqual(out["overall"], "PASS")
        self.assertEqual(out["adversarial"]["status"], "upheld")
        self.assertNotIn("consistency_error", out)

    def test_repairs_adversarial_parse_error_refutation_from_raw_tail(self) -> None:
        out = judge.normalize_primary_record({
            "overall": "ERROR",
            "primary_overall": "PASS",
            "verdicts": {
                "one_rule_per_edge": {"verdict": "PASS"},
                "given_facts_visible": {"verdict": "SKIP"},
                "target_goal_reached": {"verdict": "PASS"},
            },
            "adversarial": {
                "status": "error",
                "error": "could not parse adversarial JSON",
                "raw_tail": (
                    "Found a violation.\n\n```json\n"
                    '{"refuted": true, "criterion": "one_rule_per_edge", "reason": "fused"}'
                    "\n```"
                ),
            },
        })

        self.assertEqual(out["overall"], "FAIL")
        self.assertEqual(out["adversarial"]["status"], "refuted")
        self.assertEqual(out["adversarial"]["criterion"], "one_rule_per_edge")


class AdversarialSettingsTests(unittest.TestCase):
    def test_defaults_when_section_absent(self) -> None:
        s = judge.adversarial_settings({})
        self.assertFalse(s["enabled"])
        self.assertEqual(s["engine"], "openrouter")
        self.assertEqual(s["model"], "anthropic/claude-sonnet-4.6")
        self.assertEqual(s["fail_mode"], "closed")

    def test_reads_config_section(self) -> None:
        s = judge.adversarial_settings({
            "adversarial_judge": {"enabled": True, "engine": "claude", "model": "opus", "fail_mode": "open"}})
        self.assertTrue(s["enabled"])
        self.assertEqual(s["engine"], "claude")
        self.assertEqual(s["model"], "opus")
        self.assertEqual(s["fail_mode"], "open")

    def test_env_overrides_model(self) -> None:
        import os
        os.environ["ADVERSARIAL_JUDGE_MODEL"] = "haiku"
        try:
            s = judge.adversarial_settings({"adversarial_judge": {"enabled": True, "model": "opus"}})
            self.assertEqual(s["model"], "haiku")
        finally:
            del os.environ["ADVERSARIAL_JUDGE_MODEL"]

    def test_env_can_request_engine_default_model(self) -> None:
        import os
        os.environ["ADVERSARIAL_JUDGE_MODEL"] = "default"
        try:
            s = judge.adversarial_settings({"adversarial_judge": {"enabled": True, "model": "opus"}})
            self.assertIsNone(s["model"])
        finally:
            del os.environ["ADVERSARIAL_JUDGE_MODEL"]


class ProductionJudgeRoutingTests(unittest.TestCase):
    def test_legacy_evolution_script_routes_through_judge_wrapper(self) -> None:
        script = (ROOT / "scripts" / "inner_with_evolution.sh").read_text()
        self.assertIn("derivations/judge.py", script)
        self.assertNotIn("derivations/deepseek_judge.py", script)


if __name__ == "__main__":
    unittest.main()
