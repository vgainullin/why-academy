from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import ab_bugfix_compare as abc  # noqa: E402


def _make_worktree(tmp: Path, name: str, *, closures: list[dict] | None = None,
                   proposals: list[dict] | None = None,
                   state: dict | None = None,
                   epoch_state: dict | None = None,
                   regression: dict | None = None) -> Path:
    wt = tmp / name
    reports = wt / "derivations" / "reports" / "epoch_001"
    reports.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(closures or []):
        (reports / f"proposal_bug_seed{i}_closure.json").write_text(json.dumps(c))
    for i, p in enumerate(proposals or []):
        (reports / f"proposal_bug_seed{i}.md").write_text(p)
    st = wt / "derivations" / "state.json"
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_text(json.dumps(state or {"epoch": 1, "validator_version": "v2", "config_version": "v5"}))
    es = wt / "derivations" / "_epoch_state.json"
    es.write_text(json.dumps(epoch_state or {"phase": "DONE", "batch_id": "test"}))
    if regression:
        for rule, entries in regression.items():
            corpus = wt / "derivations" / "test_corpus" / rule
            corpus.mkdir(parents=True, exist_ok=True)
            (corpus / "positive.json").write_text(json.dumps(entries.get("positive", [])))
            (corpus / "negative.json").write_text(json.dumps(entries.get("negative", [])))
    return wt


class FindClosureSidecarsTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_finds_sidecars_across_epochs(self) -> None:
        wt = self.tmp / "wt"
        r1 = wt / "derivations" / "reports" / "epoch_001"
        r2 = wt / "derivations" / "reports" / "epoch_002"
        r1.mkdir(parents=True); r2.mkdir(parents=True)
        (r1 / "proposal_bug_a_closure.json").write_text(json.dumps({"seed_hypothesis": "a"}))
        (r2 / "proposal_bug_b_closure.json").write_text(json.dumps({"seed_hypothesis": "b"}))
        result = abc.find_closure_sidecars(wt)
        self.assertEqual(len(result), 2)
        self.assertEqual({r["seed_hypothesis"] for r in result}, {"a", "b"})

    def test_empty_when_no_reports(self) -> None:
        wt = self.tmp / "wt"
        wt.mkdir()
        self.assertEqual(abc.find_closure_sidecars(wt), [])


class CountRegressionTestsTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_counts_bugfix_entries(self) -> None:
        wt = self.tmp / "wt"
        corpus = wt / "derivations" / "test_corpus" / "divide_both_sides"
        corpus.mkdir(parents=True)
        (corpus / "positive.json").write_text(json.dumps([
            {"description": "existing"},
            {"description": "[bugfix:seed1] repro"},
        ]))
        (corpus / "negative.json").write_text(json.dumps([
            {"description": "existing neg"},
            {"description": "[bugfix:seed1] neg repro"},
        ]))
        result = abc.count_regression_tests(wt, "divide_both_sides")
        self.assertEqual(result["total_positive"], 2)
        self.assertEqual(result["total_negative"], 2)
        self.assertEqual(result["bugfix_positive"], 1)
        self.assertEqual(result["bugfix_negative"], 1)

    def test_empty_when_no_corpus(self) -> None:
        wt = self.tmp / "wt"
        wt.mkdir()
        result = abc.count_regression_tests(wt, "nonexistent")
        self.assertEqual(result["total_positive"], 0)


class CompareWorktreesTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _closure(self, seed: str, *, lift: float = 1.0, holdout=None,
                 actual="PASS", threshold=0.4) -> dict:
        return {
            "kind": "BUGFIX", "rule": "divide_both_sides",
            "seed_hypothesis": seed, "lift_fraction": lift,
            "holdout_regressed": holdout, "actual_status": actual,
            "expected_status": "PASS", "min_lift_threshold": threshold,
        }

    def _proposal(self, seed: str, *, kind="BUGFIX", evidence=5) -> str:
        return (
            f"**Kind**: {kind}\n"
            f"**Affected rule**: `divide_both_sides`\n"
            f"**Seed hypothesis**: {seed}\n"
            f"**Evidence count**: {evidence}\n"
        )

    def test_both_confirmed_higher_lift_wins(self) -> None:
        c = _make_worktree(self.tmp, "control",
            closures=[self._closure("s1", lift=1.0)],
            proposals=[self._proposal("s1")])
        t = _make_worktree(self.tmp, "treatment",
            closures=[self._closure("s1", lift=0.8)],
            proposals=[self._proposal("s1")])
        summary = abc.compare_worktrees(c, t)
        self.assertEqual(summary["paired"]["overall_winner"], "control")
        self.assertEqual(summary["paired"]["n_seeds"], 1)
        self.assertEqual(summary["pairs"][0]["winner"], "control")

    def test_confirmed_beats_failed(self) -> None:
        c = _make_worktree(self.tmp, "control",
            closures=[self._closure("s1", lift=1.0)],
            proposals=[self._proposal("s1")])
        t = _make_worktree(self.tmp, "treatment",
            closures=[self._closure("s1", lift=0.0, actual="FAIL")],
            proposals=[self._proposal("s1")])
        summary = abc.compare_worktrees(c, t)
        self.assertEqual(summary["pairs"][0]["winner"], "control")
        self.assertEqual(summary["paired"]["control_confirmed"], 1)
        self.assertEqual(summary["paired"]["treatment_confirmed"], 0)

    def test_holdout_regression_counts(self) -> None:
        c = _make_worktree(self.tmp, "control",
            closures=[self._closure("s1", lift=1.0, holdout=None)],
            proposals=[self._proposal("s1")])
        t = _make_worktree(self.tmp, "treatment",
            closures=[self._closure("s1", lift=1.0, holdout="some.json")],
            proposals=[self._proposal("s1")])
        summary = abc.compare_worktrees(c, t)
        self.assertEqual(summary["paired"]["control_holdout_regressed"], 0)
        self.assertEqual(summary["paired"]["treatment_holdout_regressed"], 1)

    def test_tie_when_identical(self) -> None:
        c = _make_worktree(self.tmp, "control",
            closures=[self._closure("s1", lift=1.0)],
            proposals=[self._proposal("s1")])
        t = _make_worktree(self.tmp, "treatment",
            closures=[self._closure("s1", lift=1.0)],
            proposals=[self._proposal("s1")])
        summary = abc.compare_worktrees(c, t)
        self.assertEqual(summary["pairs"][0]["winner"], "tie")
        self.assertEqual(summary["paired"]["overall_winner"], "tie")

    def test_seeds_only_in_one_side(self) -> None:
        c = _make_worktree(self.tmp, "control",
            closures=[self._closure("s1"), self._closure("s2")],
            proposals=[self._proposal("s1"), self._proposal("s2")])
        t = _make_worktree(self.tmp, "treatment",
            closures=[self._closure("s1")],
            proposals=[self._proposal("s1")])
        summary = abc.compare_worktrees(c, t)
        self.assertEqual(summary["paired"]["n_seeds"], 2)
        # s2 only in control → control wins that seed
        s2_pair = next(p for p in summary["pairs"] if p["seed"] == "s2")
        self.assertEqual(s2_pair["winner"], "control")
        self.assertIsNone(s2_pair["treatment"]["closure_verdict"])

    def test_investigate_proposal_no_closure(self) -> None:
        c = _make_worktree(self.tmp, "control",
            closures=[],
            proposals=[self._proposal("s1", kind="INVESTIGATE")])
        t = _make_worktree(self.tmp, "treatment",
            closures=[self._closure("s1")],
            proposals=[self._proposal("s1")])
        summary = abc.compare_worktrees(c, t)
        s1 = summary["pairs"][0]
        self.assertIsNone(s1["control"]["closure_verdict"])
        self.assertEqual(s1["treatment"]["closure_verdict"], "REPRO_CONFIRMED")
        self.assertEqual(s1["winner"], "treatment")

    def test_overall_winner_multiple_seeds(self) -> None:
        c = _make_worktree(self.tmp, "control",
            closures=[self._closure("s1", lift=1.0), self._closure("s2", lift=0.0, actual="FAIL")],
            proposals=[self._proposal("s1"), self._proposal("s2")])
        t = _make_worktree(self.tmp, "treatment",
            closures=[self._closure("s1", lift=0.0, actual="FAIL"), self._closure("s2", lift=1.0)],
            proposals=[self._proposal("s1"), self._proposal("s2")])
        summary = abc.compare_worktrees(c, t)
        self.assertEqual(summary["paired"]["control_wins"], 1)
        self.assertEqual(summary["paired"]["treatment_wins"], 1)
        self.assertEqual(summary["paired"]["overall_winner"], "tie")


class RenderMarkdownTests(unittest.TestCase):

    def test_renders_all_sections(self) -> None:
        summary = {
            "experiment_id": "test",
            "control_worktree": {
                "worktree_path": "/c", "epoch": 1, "validator_version": "v2",
                "n_bugfix_proposals": 1, "n_investigate_proposals": 1, "n_closures": 1,
            },
            "treatment_worktree": {
                "worktree_path": "/t", "epoch": 2, "validator_version": "v3",
                "n_bugfix_proposals": 1, "n_investigate_proposals": 0, "n_closures": 1,
            },
            "paired": {
                "n_seeds": 1, "control_confirmed": 1, "treatment_confirmed": 1,
                "control_holdout_regressed": 0, "treatment_holdout_regressed": 0,
                "control_wins": 0, "treatment_wins": 0, "ties": 1,
                "overall_winner": "tie",
            },
            "pairs": [{
                "seed": "s1", "winner": "tie",
                "control": {"kind": "BUGFIX", "closure_verdict": "REPRO_CONFIRMED",
                            "lift_fraction": 1.0, "holdout_regressed": None,
                            "regression_tests": {"bugfix_positive": 1, "bugfix_negative": 1,
                                                 "total_positive": 5, "total_negative": 3}},
                "treatment": {"kind": "BUGFIX", "closure_verdict": "REPRO_CONFIRMED",
                              "lift_fraction": 1.0, "holdout_regressed": None,
                              "regression_tests": {"bugfix_positive": 1, "bugfix_negative": 1,
                                                   "total_positive": 5, "total_negative": 3}},
            }],
        }
        md = abc.render_markdown(summary)
        self.assertIn("# A/B Bugfix Comparison", md)
        self.assertIn("## Worktree summaries", md)
        self.assertIn("## Per-seed comparison", md)
        self.assertIn("## Regression test coverage", md)
        self.assertIn("s1", md)
        self.assertIn("REPRO_CONFIRMED", md)


if __name__ == "__main__":
    unittest.main()
