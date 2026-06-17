from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import judge_calibration as jc  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _case(cid, labels, provenance="human_confirmed"):
    return {"id": cid, "dir": Path("/nonexistent") / cid, "target": "t",
            "labels": labels, "rationale": "", "label_provenance": provenance}


class ScoreCaseTests(unittest.TestCase):
    def test_verifier_caught_fail_label_is_safe(self) -> None:
        s = jc.score_case(_case("f", {"overall": "FAIL"}), verifier_ok=False, judge_record=None)
        self.assertEqual(s["bucket"], "verifier_caught")
        self.assertFalse(s["false_pass"])
        self.assertFalse(s["contradiction"])

    def test_verifier_caught_pass_label_is_contradiction(self) -> None:
        s = jc.score_case(_case("p", {"overall": "PASS"}), verifier_ok=False, judge_record=None)
        self.assertTrue(s["contradiction"])

    def test_judged_agreement(self) -> None:
        labels = {"one_rule_per_edge": "PASS", "given_facts_visible": "SKIP",
                  "target_goal_reached": "PASS", "overall": "PASS"}
        record = {"overall": "PASS", "verdicts": {
            "one_rule_per_edge": {"verdict": "PASS"},
            "given_facts_visible": {"verdict": "SKIP"},
            "target_goal_reached": {"verdict": "PASS"}}}
        s = jc.score_case(_case("ok", labels), verifier_ok=True, judge_record=record)
        self.assertEqual(s["bucket"], "judged")
        self.assertTrue(s["overall_agree"])
        self.assertFalse(s["false_pass"])
        self.assertFalse(s["false_fail"])

    def test_false_pass_detected(self) -> None:
        labels = {"one_rule_per_edge": "FAIL", "overall": "FAIL"}
        record = {"overall": "PASS", "verdicts": {"one_rule_per_edge": {"verdict": "PASS"}}}
        s = jc.score_case(_case("fp", labels), verifier_ok=True, judge_record=record)
        self.assertTrue(s["false_pass"])
        self.assertFalse(s["false_fail"])

    def test_false_fail_detected(self) -> None:
        labels = {"overall": "PASS", "one_rule_per_edge": "PASS"}
        record = {"overall": "FAIL", "verdicts": {"one_rule_per_edge": {"verdict": "FAIL"}}}
        s = jc.score_case(_case("ff", labels), verifier_ok=True, judge_record=record)
        self.assertTrue(s["false_fail"])
        self.assertFalse(s["false_pass"])

    def test_pass_label_skip_judge_counts_as_agreement(self) -> None:
        labels = {"given_facts_visible": "PASS", "overall": "PASS"}
        record = {"overall": "PASS", "verdicts": {"given_facts_visible": {"verdict": "SKIP"}}}
        s = jc.score_case(_case("skip", labels), verifier_ok=True, judge_record=record)
        self.assertTrue(s["criteria"]["given_facts_visible"]["agree"])


class AggregateTests(unittest.TestCase):
    def _scored(self, *triples):
        # (label_overall, judge_overall, verifier_ok)
        out = []
        for i, (lab, jud, vok) in enumerate(triples):
            rec = None if not vok else {"overall": jud, "verdicts": {}}
            out.append(jc.score_case(_case(f"c{i}", {"overall": lab}), verifier_ok=vok, judge_record=rec))
        return out

    def test_clean_run_passes(self) -> None:
        scored = self._scored(("PASS", "PASS", True), ("FAIL", "FAIL", True), ("FAIL", "FAIL", False))
        summary = jc.aggregate(scored, {"max_false_pass": 0, "min_overall_agreement": 0.8})
        self.assertTrue(summary["passed"])
        self.assertEqual(summary["n_judged"], 2)
        self.assertEqual(summary["n_verifier_caught"], 1)
        self.assertEqual(summary["false_passes"], [])

    def test_false_pass_fails_run(self) -> None:
        scored = self._scored(("PASS", "PASS", True), ("FAIL", "PASS", True))
        summary = jc.aggregate(scored, {"max_false_pass": 0, "min_overall_agreement": 0.5})
        self.assertEqual(len(summary["false_passes"]), 1)
        self.assertFalse(summary["passed"])

    def test_low_agreement_fails_run(self) -> None:
        scored = self._scored(("PASS", "FAIL", True), ("PASS", "FAIL", True),
                              ("PASS", "PASS", True), ("PASS", "PASS", True))
        # 2/4 agree -> 50% < 80%, but no false passes (all PASS-labeled)
        summary = jc.aggregate(scored, {"max_false_pass": 0, "min_overall_agreement": 0.8})
        self.assertEqual(summary["false_passes"], [])
        self.assertEqual(summary["overall_agreement"], 0.5)
        self.assertFalse(summary["passed"])

    def test_contradiction_fails_run(self) -> None:
        scored = self._scored(("PASS", "PASS", True), ("PASS", None, False))
        summary = jc.aggregate(scored, {"max_false_pass": 0, "min_overall_agreement": 0.5})
        self.assertEqual(len(summary["contradictions"]), 1)
        self.assertFalse(summary["passed"])


class EndToEndStubTests(unittest.TestCase):
    """Drive the real harness against the real corpus with stub judges."""

    def run_cal(self, stub: str) -> tuple[int, dict]:
        out = ROOT / "derivations" / "test_corpus" / "judge_holdout" / "reports" / f"_test_{stub}.json"
        proc = subprocess.run(
            [sys.executable, str(DERIVATIONS / "judge_calibration.py"),
             "--judge-cmd", f"{sys.executable} {FIXTURES / stub}",
             "--max-false-pass", "0", "--min-overall-agreement", "0.8",
             "--out", str(out)],
            cwd=ROOT, capture_output=True, text=True, timeout=300,
        )
        report = json.loads(out.read_text())
        out.unlink(missing_ok=True)
        return proc.returncode, report

    def test_oracle_judge_passes_calibration(self) -> None:
        rc, report = self.run_cal("stub_judge_oracle.py")
        summary = report["summary"]
        self.assertEqual(summary["false_passes"], [], summary)
        self.assertEqual(summary["contradictions"], [], summary)
        self.assertEqual(summary["overall_agreement"], 1.0, summary)
        self.assertTrue(summary["passed"])
        self.assertEqual(rc, 0)
        # Corpus must actually exercise the judge, not be all verifier-caught.
        self.assertGreaterEqual(summary["n_judged"], 6, summary)

    def test_lazy_judge_is_caught_by_false_pass_metric(self) -> None:
        rc, report = self.run_cal("stub_judge_lazy.py")
        summary = report["summary"]
        self.assertGreater(len(summary["false_passes"]), 0, summary)
        self.assertFalse(summary["passed"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
