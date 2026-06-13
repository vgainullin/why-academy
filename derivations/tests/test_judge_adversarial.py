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


class AdversarialSettingsTests(unittest.TestCase):
    def test_defaults_when_section_absent(self) -> None:
        s = judge.adversarial_settings({})
        self.assertFalse(s["enabled"])
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


if __name__ == "__main__":
    unittest.main()
