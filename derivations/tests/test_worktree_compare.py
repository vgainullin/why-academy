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

import worktree_compare as wc  # noqa: E402


def _make_worktree(tmp: Path, name: str, **kw) -> Path:
    wt = tmp / name
    reports = wt / "derivations" / "reports" / "epoch_001"
    reports.mkdir(parents=True, exist_ok=True)

    closures = kw.get("closures", [])
    for i, c in enumerate(closures):
        (reports / f"proposal_bug_seed{i}_closure.json").write_text(json.dumps(c))

    proposals = kw.get("proposals", [])
    for i, p in enumerate(proposals):
        (reports / f"proposal_bug_seed{i}.md").write_text(p)

    st = wt / "derivations" / "state.json"
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_text(json.dumps(kw.get("state", {"epoch": 1, "validator_version": "v2", "config_version": "v5"})))

    es = wt / "derivations" / "_epoch_state.json"
    es.write_text(json.dumps(kw.get("epoch_state", {"phase": "DONE", "batch_id": "test"})))

    regression = kw.get("regression", {})
    for rule, entries in regression.items():
        corpus = wt / "derivations" / "test_corpus" / rule
        corpus.mkdir(parents=True, exist_ok=True)
        (corpus / "positive.json").write_text(json.dumps(entries.get("positive", [])))
        (corpus / "negative.json").write_text(json.dumps(entries.get("negative", [])))

    # Batch artifacts
    if "batch_targets" in kw:
        batch_dir = wt / "derivations" / "_evolutions" / "batches" / "batch_test"
        targets_dir = batch_dir / "targets"
        targets_dir.mkdir(parents=True, exist_ok=True)
        for i, t in enumerate(kw["batch_targets"]):
            td = targets_dir / f"target_{i:03d}"
            td.mkdir()
            (td / "target.json").write_text(json.dumps({"target": t.get("target", "")}))
            (td / "target_metrics.json").write_text(json.dumps({
                "target_index": i, "accepted": t.get("accepted", False),
                "first_try_pass": t.get("first_try_pass", False),
                "n_iterations": t.get("n_iterations", 3),
            }))

    return wt


# ── Framework protocol tests ─────────────────────────────────────────────


class ExtractorRegistryTests(unittest.TestCase):

    def test_builtin_extractors_registered(self) -> None:
        for name in ("bugfix", "batch", "test"):
            self.assertIn(name, wc.EXTRACTORS)

    def test_load_extractor_by_name(self) -> None:
        ext = wc.load_extractor("bugfix")
        self.assertIsInstance(ext, wc.BugfixExtractor)

    def test_load_extractor_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            wc.load_extractor("nonexistent")

    def test_load_extractor_custom_module(self) -> None:
        tmp = Path(tempfile.mktemp(suffix=".py"))
        tmp.write_text(
            "from worktree_compare import Extractor\n"
            "from pathlib import Path\n"
            "class Extractor(Extractor):\n"
            "    name = 'custom'\n"
            "    def extract(self, wt): return {'worktree_path': str(wt), 'pairs_key': 'x', 'x': []}\n"
            "    def pair(self, c, t): return []\n"
            "    def summarize(self, p, c, t): return {'extractor': 'custom', 'paired': {}, 'pairs': []}\n"
            "    def render_markdown(self, s): return '# custom'\n"
        )
        try:
            ext = wc.load_extractor("custom", module_path=str(tmp))
            self.assertEqual(ext.name, "custom")
        finally:
            tmp.unlink()


class AutoDetectTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detects_bugfix_when_closure_sidecars(self) -> None:
        wt = _make_worktree(self.tmp, "wt",
            closures=[{"seed_hypothesis": "s1", "lift_fraction": 1.0}])
        self.assertEqual(wc.auto_detect(wt), "bugfix")

    def test_detects_batch_when_evo_batches(self) -> None:
        wt = _make_worktree(self.tmp, "wt", batch_targets=[{"target": "x"}])
        self.assertEqual(wc.auto_detect(wt), "batch")

    def test_falls_back_to_test(self) -> None:
        wt = self.tmp / "empty"
        wt.mkdir()
        self.assertEqual(wc.auto_detect(wt), "test")


# ── BugfixExtractor tests ────────────────────────────────────────────────


class BugfixExtractorTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.ext = wc.BugfixExtractor()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _closure(self, seed, *, lift=1.0, holdout=None, actual="PASS") -> dict:
        return {"kind": "BUGFIX", "rule": "r", "seed_hypothesis": seed,
                "lift_fraction": lift, "holdout_regressed": holdout,
                "actual_status": actual, "expected_status": "PASS",
                "min_lift_threshold": 0.4}

    def _proposal(self, seed, *, kind="BUGFIX", evidence=5) -> str:
        return (f"**Kind**: {kind}\n**Affected rule**: `r`\n"
                f"**Seed hypothesis**: {seed}\n**Evidence count**: {evidence}\n")

    def test_extract_reads_closures_and_proposals(self) -> None:
        wt = _make_worktree(self.tmp, "wt",
            closures=[self._closure("s1")], proposals=[self._proposal("s1")])
        result = self.ext.extract(wt)
        self.assertEqual(len(result["seed_results"]), 1)
        sr = result["seed_results"][0]
        self.assertEqual(sr["seed"], "s1")
        self.assertEqual(sr["closure_verdict"], "REPRO_CONFIRMED")
        self.assertEqual(sr["lift_fraction"], 1.0)

    def test_pair_confirmed_beats_failed(self) -> None:
        c = _make_worktree(self.tmp, "c", closures=[self._closure("s1", lift=1.0)], proposals=[self._proposal("s1")])
        t = _make_worktree(self.tmp, "t", closures=[self._closure("s1", lift=0.0, actual="FAIL")], proposals=[self._proposal("s1")])
        pairs = self.ext.pair(self.ext.extract(c), self.ext.extract(t))
        self.assertEqual(pairs[0]["winner"], "control")

    def test_pair_tie_when_identical(self) -> None:
        c = _make_worktree(self.tmp, "c", closures=[self._closure("s1")], proposals=[self._proposal("s1")])
        t = _make_worktree(self.tmp, "t", closures=[self._closure("s1")], proposals=[self._proposal("s1")])
        pairs = self.ext.pair(self.ext.extract(c), self.ext.extract(t))
        self.assertEqual(pairs[0]["winner"], "tie")

    def test_summarize_aggregates(self) -> None:
        c = _make_worktree(self.tmp, "c", closures=[self._closure("s1")], proposals=[self._proposal("s1")])
        t = _make_worktree(self.tmp, "t", closures=[], proposals=[self._proposal("s1", kind="INVESTIGATE")])
        cm = self.ext.extract(c)
        tm = self.ext.extract(t)
        pairs = self.ext.pair(cm, tm)
        summary = self.ext.summarize(pairs, cm, tm)
        self.assertEqual(summary["paired"]["control_confirmed"], 1)
        self.assertEqual(summary["paired"]["treatment_confirmed"], 0)
        self.assertEqual(summary["paired"]["overall_winner"], "control")

    def test_render_markdown_has_sections(self) -> None:
        c = _make_worktree(self.tmp, "c", closures=[self._closure("s1")], proposals=[self._proposal("s1")])
        t = _make_worktree(self.tmp, "t", closures=[self._closure("s1")], proposals=[self._proposal("s1")])
        summary = wc.compare_worktrees(c, t, self.ext)
        md = self.ext.render_markdown(summary)
        self.assertIn("## Per-seed comparison", md)
        self.assertIn("## Regression test coverage", md)


# ── BatchExtractor tests ─────────────────────────────────────────────────


class BatchExtractorTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.ext = wc.BatchExtractor()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_extract_reads_batch_targets(self) -> None:
        wt = _make_worktree(self.tmp, "wt",
            batch_targets=[{"target": "a", "accepted": True}, {"target": "b", "accepted": False}])
        result = self.ext.extract(wt)
        self.assertEqual(result["n_targets"], 2)
        self.assertEqual(result["n_accepted"], 1)
        self.assertAlmostEqual(result["acceptance_rate"], 0.5)

    def test_pair_accepted_beats_failed(self) -> None:
        c = _make_worktree(self.tmp, "c", batch_targets=[{"target": "a", "accepted": True}])
        t = _make_worktree(self.tmp, "t", batch_targets=[{"target": "a", "accepted": False}])
        pairs = self.ext.pair(self.ext.extract(c), self.ext.extract(t))
        self.assertEqual(pairs[0]["winner"], "control")

    def test_summarize_acceptance_delta(self) -> None:
        c = _make_worktree(self.tmp, "c", batch_targets=[{"target": "a", "accepted": True}, {"target": "b", "accepted": True}])
        t = _make_worktree(self.tmp, "t", batch_targets=[{"target": "a", "accepted": True}, {"target": "b", "accepted": False}])
        cm = self.ext.extract(c)
        tm = self.ext.extract(t)
        pairs = self.ext.pair(cm, tm)
        summary = self.ext.summarize(pairs, cm, tm)
        self.assertAlmostEqual(summary["paired"]["acceptance_delta"], -0.5)


# ── TestSuiteExtractor tests ─────────────────────────────────────────────


class TestSuiteExtractorTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.ext = wc.TestSuiteExtractor()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_winner_both_pass_more_tests_wins(self) -> None:
        self.assertEqual(self.ext._test_winner(
            {"passed": True, "ran": 100}, {"passed": True, "ran": 90}), "control")
        self.assertEqual(self.ext._test_winner(
            {"passed": True, "ran": 90}, {"passed": True, "ran": 100}), "treatment")

    def test_winner_pass_beats_fail(self) -> None:
        self.assertEqual(self.ext._test_winner(
            {"passed": True, "ran": 1}, {"passed": False, "ran": 1}), "control")
        self.assertEqual(self.ext._test_winner(
            {"passed": False, "ran": 1}, {"passed": True, "ran": 1}), "treatment")

    def test_winner_both_fail_is_tie(self) -> None:
        self.assertEqual(self.ext._test_winner(
            {"passed": False, "ran": 1}, {"passed": False, "ran": 1}), "tie")

    @patch.object(wc.TestSuiteExtractor, "_run_tests")
    def test_extract_and_summarize(self, mock_run) -> None:
        wt = self.tmp / "wt"
        wt.mkdir()
        mock_run.return_value = {"ran": 50, "passed": True}
        result = self.ext.extract(wt)
        self.assertTrue(result["passed"])
        self.assertEqual(result["ran"], 50)


# ── compare_worktrees integration ────────────────────────────────────────


class CompareWorktreesTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bugfix_comparison_end_to_end(self) -> None:
        c = _make_worktree(self.tmp, "c",
            closures=[{"seed_hypothesis": "s1", "lift_fraction": 1.0, "kind": "BUGFIX",
                       "rule": "r", "actual_status": "PASS", "expected_status": "PASS",
                       "min_lift_threshold": 0.4, "holdout_regressed": None}],
            proposals=["**Kind**: BUGFIX\n**Affected rule**: `r`\n**Seed hypothesis**: s1\n**Evidence count**: 3\n"])
        t = _make_worktree(self.tmp, "t",
            closures=[], proposals=["**Kind**: INVESTIGATE\n**Affected rule**: `r`\n**Seed hypothesis**: s1\n**Evidence count**: 3\n"])
        summary = wc.compare_worktrees(c, t, wc.BugfixExtractor(), experiment_id="test")
        self.assertEqual(summary["extractor"], "bugfix")
        self.assertEqual(summary["paired"]["overall_winner"], "control")
        self.assertEqual(summary["experiment_id"], "test")


if __name__ == "__main__":
    unittest.main()
