from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import autonomous_epoch as ae  # noqa: E402
import closure_test as ct  # noqa: E402


def _epoch_dir(tmp: Path, epoch: int = 1) -> Path:
    d = tmp / "derivations" / "reports" / f"epoch_{epoch:03d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_log(tmp: Path, epoch: int, name: str, records: list[dict]) -> None:
    logs_dir = tmp / "derivations" / "logs" / f"epoch_{epoch:03d}"
    logs_dir.mkdir(parents=True, exist_ok=True)
    with (logs_dir / name).open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _make_validator(tmp: Path, rule: str) -> None:
    vdir = tmp / "derivations" / "validators"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / f"{rule}.py").write_text(f'RULE_NAME = "{rule}"\ndef validate(f,t,a):\n    return ("PASS","")\n')


# ── PHASES ───────────────────────────────────────────────────────────────
class PhasesOrderTests(unittest.TestCase):

    def test_bug_investigate_between_analyze_and_experiment(self) -> None:
        idx = {p: i for i, p in enumerate(ae.PHASES)}
        self.assertIn("BUG_INVESTIGATE", ae.PHASES)
        self.assertLess(idx["ANALYZE"], idx["BUG_INVESTIGATE"])
        self.assertLess(idx["BUG_INVESTIGATE"], idx["EXPERIMENT"])


# ── Seed evidence matching ───────────────────────────────────────────────
class MatchSeedEvidenceTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rec(self, edges, **kw) -> dict:
        r = {"target": "t", "batch_id": "b", "edge_results": edges}
        r.update(kw)
        return r

    def test_validator_rejected_matches_when_validator_exists(self) -> None:
        _make_validator(self.tmp, "divide_both_sides")
        logs = [self._rec([{"rule": "divide_both_sides", "status": "FAIL", "reason": "no"}])
                for _ in range(3)]
        seed = {"evidence_signals": ["VALIDATOR_REJECTED"],
                "affected_rules": ["divide_both_sides"]}
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            matches = ae._match_seed_evidence(seed, logs)
        self.assertEqual(len(matches), 3)
        self.assertEqual({m["signal"] for m in matches}, {"VALIDATOR_REJECTED"})

    def test_validator_rejected_skips_when_no_validator(self) -> None:
        # No validator file created -> the FAIL is UNCOVERED, not a rejection.
        logs = [self._rec([{"rule": "divide_both_sides", "status": "FAIL", "reason": "no"}])
                for _ in range(3)]
        seed = {"evidence_signals": ["VALIDATOR_REJECTED"],
                "affected_rules": ["divide_both_sides"]}
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            matches = ae._match_seed_evidence(seed, logs)
        self.assertEqual(matches, [])

    def test_validator_rejected_skips_non_fail_status(self) -> None:
        _make_validator(self.tmp, "divide_both_sides")
        logs = [self._rec([{"rule": "divide_both_sides", "status": "PASS"}])]
        seed = {"evidence_signals": ["VALIDATOR_REJECTED"],
                "affected_rules": ["divide_both_sides"]}
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            matches = ae._match_seed_evidence(seed, logs)
        self.assertEqual(matches, [])

    def test_judge_signal_matches(self) -> None:
        logs = [self._rec(
            [{"rule": "substitute_value", "status": "PASS"}],
            judge_eval={"overall": "FAIL", "verdicts": {"one_rule_per_edge": "FAIL"}},
        )]
        seed = {"evidence_signals": ["one_rule_per_edge"],
                "affected_rules": ["substitute_value", "simplify_expression"]}
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            matches = ae._match_seed_evidence(seed, logs)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["signal"], "one_rule_per_edge")

    def test_judge_signal_skips_when_no_affected_rule_in_record(self) -> None:
        logs = [self._rec(
            [{"rule": "other_rule", "status": "PASS"}],
            judge_eval={"overall": "FAIL", "verdicts": {"one_rule_per_edge": "FAIL"}},
        )]
        seed = {"evidence_signals": ["one_rule_per_edge"],
                "affected_rules": ["substitute_value"]}
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            matches = ae._match_seed_evidence(seed, logs)
        self.assertEqual(matches, [])

    def test_dedup_by_record_signal_rule(self) -> None:
        _make_validator(self.tmp, "divide_both_sides")
        # Two FAIL edges for the same rule in the same record -> one match.
        logs = [self._rec([
            {"rule": "divide_both_sides", "status": "FAIL", "reason": "a"},
            {"rule": "divide_both_sides", "status": "FAIL", "reason": "b"},
        ])]
        seed = {"evidence_signals": ["VALIDATOR_REJECTED"],
                "affected_rules": ["divide_both_sides"]}
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            matches = ae._match_seed_evidence(seed, logs)
        self.assertEqual(len(matches), 1)


# ── Proposal writing ─────────────────────────────────────────────────────
class WriteBugfixProposalTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.epoch_dir = _epoch_dir(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bugfix_kind_when_reproduction_present(self) -> None:
        seed = {
            "id": "orientation_false_rejection",
            "hypothesis": "h",
            "affected_rules": ["divide_both_sides"],
            "reproduction": {"from_srepr": "Eq(5*R/2, h)", "to_srepr": "Eq(h, 5*R/2)",
                             "args": {"divisor": "g*m"}, "expected": "PASS", "actual": "FAIL",
                             "proposed_change": "Accept swapped orientation"},
        }
        path = ae._write_bugfix_proposal(self.epoch_dir, seed, [{"record_index": 0, "signal": "x",
                                                                 "rule": "divide_both_sides"}],
                                         "BUGFIX")
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "proposal_bug_orientation_false_rejection.md")
        text = path.read_text()
        self.assertIn("**Kind**: BUGFIX", text)
        self.assertIn("**Seed hypothesis**: orientation_false_rejection", text)
        self.assertIn("Eq(5*R/2, h)", text)
        self.assertIn('{"divisor": "g*m"}', text)

    def test_investigate_kind_when_no_reproduction(self) -> None:
        seed = {"id": "fused_subst_simplify", "hypothesis": "h",
                "affected_rules": ["substitute_value"]}
        path = ae._write_bugfix_proposal(self.epoch_dir, seed, [], "INVESTIGATE")
        text = path.read_text()
        self.assertIn("**Kind**: INVESTIGATE", text)
        self.assertNotIn("## Reproduction case", text)

    def test_seed_id_sanitized_in_filename(self) -> None:
        seed = {"id": "weird id!!", "hypothesis": "h", "affected_rules": ["r"],
                "reproduction": {"from_srepr": "a", "to_srepr": "b"}}
        path = ae._write_bugfix_proposal(self.epoch_dir, seed, [], "BUGFIX")
        self.assertTrue(path.name.startswith("proposal_bug_"))


# ── Regression test generation ───────────────────────────────────────────
class WriteRegressionTestsTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.corpus = self.tmp / "test_corpus"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_positive_only_when_no_negative(self) -> None:
        repro = {"from_srepr": "Eq(5*R/2, h)", "to_srepr": "Eq(h, 5*R/2)",
                 "args": {"divisor": "g*m"}, "expected": "PASS"}
        summary = ae.write_regression_tests("divide_both_sides", repro, "seed1",
                                            corpus_root=self.corpus)
        self.assertEqual(summary["positive_written"], 1)
        self.assertEqual(summary["negative_written"], 0)
        pos = json.loads((self.corpus / "divide_both_sides" / "positive.json").read_text())
        self.assertEqual(len(pos), 1)
        self.assertEqual(pos[0]["expected"], "PASS")
        self.assertFalse((self.corpus / "divide_both_sides" / "negative.json").exists())

    def test_writes_negative_when_provided(self) -> None:
        repro = {"from_srepr": "Eq(3*x, 15)", "to_srepr": "Eq(x, 6)",
                 "args": {"divisor": 3}, "expected": "PASS",
                 "negative": {"from_srepr": "Eq(3*x, 15)", "to_srepr": "Eq(x, 99)",
                              "args": {"divisor": 3}}}
        summary = ae.write_regression_tests("divide_both_sides", repro, "seed1",
                                            corpus_root=self.corpus)
        self.assertEqual(summary["negative_written"], 1)
        neg = json.loads((self.corpus / "divide_both_sides" / "negative.json").read_text())
        self.assertEqual(neg[0]["expected"], "FAIL")

    def test_preserves_and_dedups_existing_entries(self) -> None:
        rule_dir = self.corpus / "divide_both_sides"
        rule_dir.mkdir(parents=True)
        (rule_dir / "positive.json").write_text(json.dumps([
            {"description": "existing", "from_srepr": "a", "to_srepr": "b", "args": {}, "expected": "PASS"}
        ]))
        repro = {"from_srepr": "Eq(5*R/2, h)", "to_srepr": "Eq(h, 5*R/2)",
                 "args": {"divisor": "g*m"}, "expected": "PASS"}
        ae.write_regression_tests("divide_both_sides", repro, "seed1", corpus_root=self.corpus)
        pos = json.loads((rule_dir / "positive.json").read_text())
        self.assertEqual(len(pos), 2)
        # Running again does not duplicate the bugfix entry.
        ae.write_regression_tests("divide_both_sides", repro, "seed1", corpus_root=self.corpus)
        pos = json.loads((rule_dir / "positive.json").read_text())
        self.assertEqual(len(pos), 2)


# ── Proposal parsing helpers ─────────────────────────────────────────────
class ProposalParserTests(unittest.TestCase):

    def test_parsers_round_trip(self) -> None:
        tmp = Path(tempfile.mktemp(suffix=".md"))
        tmp.write_text(
            "**Kind**: BUGFIX\n"
            "**Affected rule**: `divide_both_sides`\n"
            "**Seed hypothesis**: orientation_false_rejection\n\n"
            "## Reproduction case\n\n"
            "- from_srepr: Eq(5*R/2, h)\n"
            "- to_srepr: Eq(h, 5*R/2)\n"
            '- args: {"divisor": "g*m"}\n'
            "- expected: PASS\n"
            "- actual: FAIL\n\n"
            "## Proposed change\n\n"
            "Accept swapped orientation\n"
        )
        try:
            self.assertEqual(ae.kind_from_proposal(tmp), "BUGFIX")
            self.assertEqual(ae.affected_rule_from_proposal(tmp), "divide_both_sides")
            self.assertEqual(ae.seed_id_from_proposal(tmp), "orientation_false_rejection")
            self.assertTrue(ae.is_bugfix_proposal(tmp))
            repro = ae.reproduction_from_proposal(tmp)
            self.assertIsNotNone(repro)
            self.assertEqual(repro["from_srepr"], "Eq(5*R/2, h)")
            self.assertEqual(repro["args"], {"divisor": "g*m"})
            self.assertEqual(repro["expected"], "PASS")
        finally:
            tmp.unlink()

    def test_reproduction_returns_none_when_absent(self) -> None:
        tmp = Path(tempfile.mktemp(suffix=".md"))
        tmp.write_text("**Kind**: INVESTIGATE\n**Affected rule**: none\n")
        try:
            self.assertIsNone(ae.reproduction_from_proposal(tmp))
            self.assertFalse(ae.is_bugfix_proposal(tmp))
        finally:
            tmp.unlink()

    def test_reproduction_parses_negative_sub_block(self) -> None:
        tmp = Path(tempfile.mktemp(suffix=".md"))
        tmp.write_text(
            "**Kind**: BUGFIX\n"
            "**Affected rule**: `divide_both_sides`\n"
            "**Seed hypothesis**: s1\n\n"
            "## Reproduction case\n\n"
            "- from_srepr: Eq(3*x, 15)\n"
            "- to_srepr: Eq(5, x)\n"
            '- args: {"divisor": 3}\n'
            "- expected: PASS\n"
            "- actual: FAIL\n\n"
            "A negative (must-FAIL) regression case:\n"
            "- from_srepr: Eq(3*x, 15)\n"
            "- to_srepr: Eq(x, 6)\n"
            '- args: {"divisor": 3}\n'
            "- expected: FAIL\n\n"
            "## Proposed change\n\n"
            "Accept swapped orientation\n"
        )
        try:
            repro = ae.reproduction_from_proposal(tmp)
            self.assertIsNotNone(repro)
            self.assertEqual(repro["from_srepr"], "Eq(3*x, 15)")
            self.assertEqual(repro["to_srepr"], "Eq(5, x)")
            self.assertEqual(repro["expected"], "PASS")
            self.assertIn("negative", repro)
            neg = repro["negative"]
            self.assertEqual(neg["to_srepr"], "Eq(x, 6)")
            self.assertEqual(neg["expected"], "FAIL")
        finally:
            tmp.unlink()


# ── phase_bug_investigate ────────────────────────────────────────────────
class PhaseBugInvestigateTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.state_path = self.tmp / "derivations" / "_epoch_state.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, cfg: dict, state: dict) -> dict:
        def fake_save(c, s):
            self.state_path.write_text(json.dumps(s))
        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "_state_path", lambda c: self.state_path), \
             patch.object(ae, "save_state", side_effect=fake_save), \
             patch.object(ae, "epoch_num", return_value=1):
            ae.phase_bug_investigate(cfg, state)
        return state

    def test_disabled_skips_to_experiment(self) -> None:
        cfg = {"runner": {"bug_investigate": {"enabled": False}}}
        state = {"phase": "BUG_INVESTIGATE"}
        self._run(cfg, state)
        self.assertEqual(state["phase"], "EXPERIMENT")

    def test_no_section_skips_to_experiment(self) -> None:
        cfg = {"runner": {}}
        state = {"phase": "BUG_INVESTIGATE"}
        self._run(cfg, state)
        self.assertEqual(state["phase"], "EXPERIMENT")

    def test_insufficient_evidence_no_proposal(self) -> None:
        _make_validator(self.tmp, "divide_both_sides")
        _write_log(self.tmp, 1, "r.jsonl", [
            {"target": "t", "batch_id": "b",
             "edge_results": [{"rule": "divide_both_sides", "status": "FAIL", "reason": "x"}]}
        ])
        cfg = {"runner": {"bug_investigate": {
            "enabled": True, "min_occurrences": 2,
            "seeds": [{"id": "s1", "hypothesis": "h", "affected_rules": ["divide_both_sides"],
                       "evidence_signals": ["VALIDATOR_REJECTED"],
                       "reproduction": {"from_srepr": "a", "to_srepr": "b"}}]
        }}}
        state = {"phase": "BUG_INVESTIGATE"}
        self._run(cfg, state)
        self.assertEqual(state["phase"], "EXPERIMENT")
        self.assertIn("s1", state["bug_seeds_processed"])
        self.assertEqual(list(_epoch_dir(self.tmp).glob("proposal_*.md")), [])

    def test_writes_bugfix_proposal_when_evidence_sufficient(self) -> None:
        _make_validator(self.tmp, "divide_both_sides")
        _write_log(self.tmp, 1, "r.jsonl", [
            {"target": "t", "batch_id": "b",
             "edge_results": [{"rule": "divide_both_sides", "status": "FAIL", "reason": "x"}]}
            for _ in range(3)
        ])
        cfg = {"runner": {"bug_investigate": {
            "enabled": True, "min_occurrences": 2, "max_proposals_per_epoch": 3,
            "seeds": [{
                "id": "orientation_false_rejection", "hypothesis": "h",
                "affected_rules": ["divide_both_sides"], "evidence_signals": ["VALIDATOR_REJECTED"],
                "reproduction": {"from_srepr": "Eq(5*R/2, h)", "to_srepr": "Eq(h, 5*R/2)",
                                 "args": {"divisor": "g*m"}, "expected": "PASS", "actual": "FAIL"}
            }]
        }}}
        state = {"phase": "BUG_INVESTIGATE"}
        self._run(cfg, state)
        self.assertEqual(state["phase"], "EXPERIMENT")
        props = list(_epoch_dir(self.tmp).glob("proposal_*.md"))
        self.assertEqual(len(props), 1)
        self.assertIn("**Kind**: BUGFIX", props[0].read_text())

    def test_seed_without_reproduction_writes_investigate(self) -> None:
        _make_validator(self.tmp, "substitute_value")
        _write_log(self.tmp, 1, "r.jsonl", [
            {"target": "t", "batch_id": "b",
             "edge_results": [{"rule": "substitute_value", "status": "FAIL"}],
             "judge_eval": {"overall": "FAIL", "verdicts": {"one_rule_per_edge": "FAIL"}}}
            for _ in range(3)
        ])
        cfg = {"runner": {"bug_investigate": {
            "enabled": True, "min_occurrences": 2, "max_proposals_per_epoch": 3,
            "seeds": [{"id": "fused_subst_simplify", "hypothesis": "h",
                       "affected_rules": ["substitute_value", "simplify_expression"],
                       "evidence_signals": ["one_rule_per_edge"]}]
        }}}
        state = {"phase": "BUG_INVESTIGATE"}
        self._run(cfg, state)
        props = list(_epoch_dir(self.tmp).glob("proposal_*.md"))
        self.assertEqual(len(props), 1)
        self.assertIn("**Kind**: INVESTIGATE", props[0].read_text())

    def test_resumes_skipping_processed_seeds(self) -> None:
        _make_validator(self.tmp, "divide_both_sides")
        _write_log(self.tmp, 1, "r.jsonl", [
            {"target": "t", "batch_id": "b",
             "edge_results": [{"rule": "divide_both_sides", "status": "FAIL"}]}
            for _ in range(3)
        ])
        cfg = {"runner": {"bug_investigate": {
            "enabled": True, "min_occurrences": 2,
            "seeds": [{"id": "s1", "hypothesis": "h", "affected_rules": ["divide_both_sides"],
                       "evidence_signals": ["VALIDATOR_REJECTED"],
                       "reproduction": {"from_srepr": "a", "to_srepr": "b"}}]
        }}}
        state = {"phase": "BUG_INVESTIGATE", "bug_seeds_processed": ["s1"]}
        self._run(cfg, state)
        self.assertEqual(list(_epoch_dir(self.tmp).glob("proposal_*.md")), [])

    def test_max_proposals_cap(self) -> None:
        _make_validator(self.tmp, "r_a")
        _make_validator(self.tmp, "r_b")
        _write_log(self.tmp, 1, "r.jsonl", [
            {"target": "t", "batch_id": "b",
             "edge_results": [{"rule": "r_a", "status": "FAIL"}, {"rule": "r_b", "status": "FAIL"}]}
            for _ in range(3)
        ])
        cfg = {"runner": {"bug_investigate": {
            "enabled": True, "min_occurrences": 2, "max_proposals_per_epoch": 1,
            "seeds": [
                {"id": "s1", "hypothesis": "h", "affected_rules": ["r_a"],
                 "evidence_signals": ["VALIDATOR_REJECTED"],
                 "reproduction": {"from_srepr": "a", "to_srepr": "b"}},
                {"id": "s2", "hypothesis": "h", "affected_rules": ["r_b"],
                 "evidence_signals": ["VALIDATOR_REJECTED"],
                 "reproduction": {"from_srepr": "a", "to_srepr": "b"}},
            ]
        }}}
        state = {"phase": "BUG_INVESTIGATE"}
        self._run(cfg, state)
        props = list(_epoch_dir(self.tmp).glob("proposal_*.md"))
        self.assertEqual(len(props), 1)


# ── phase_implement BUGFIX routing ───────────────────────────────────────
class PhaseImplementBugfixTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.validators_dir = self.tmp / "derivations" / "validators"
        self.validators_dir.mkdir(parents=True)
        self.state_json = self.tmp / "derivations" / "state.json"
        self.state_json.write_text(json.dumps({
            "epoch": 1, "prompt_version": "v1", "validator_version": "v2", "config_version": "v5"
        }))
        self.reports_dir = self.tmp / "derivations" / "reports" / "epoch_001"
        self.reports_dir.mkdir(parents=True)
        self.rule = "divide_both_sides"
        (self.validators_dir / f"{self.rule}.py").write_bytes(b"# original\n")
        # A BUGFIX proposal.
        self.bugfix = self.reports_dir / "proposal_bug_orientation.md"
        self.bugfix.write_text(
            "**Kind**: BUGFIX\n"
            "**Affected rule**: `divide_both_sides`\n"
            "**Seed hypothesis**: orientation_false_rejection\n\n"
            "## Reproduction case\n\n"
            "- from_srepr: Eq(5*R/2, h)\n"
            "- to_srepr: Eq(h, 5*R/2)\n"
            '- args: {"divisor": "g*m"}\n'
            "- expected: PASS\n"
            "- actual: FAIL\n"
        )
        # An ordinary proposal that sorts earlier by name but must NOT take priority.
        self.ordinary = self.reports_dir / "proposal_01_normal.md"
        self.ordinary.write_text(
            "**Kind**: NEW_VALIDATOR\n**Affected rule**: `other_rule`\n"
        )
        self.other_rule_path = self.validators_dir / "other_rule.py"
        self.cfg = {
            "runner": {
                "auto_promote": {"min_lift_fraction": 0.4, "revert_on_holdout_regression": True},
                "epoch": {"max_proposals_per_epoch": 5, "stop_on_first_failed_promotion": False},
            }
        }
        self.state_path = self.tmp / "derivations" / "_epoch_state.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_phase(self, *, implement_rc: int, closure_rc: int,
                   closure_data: dict | None = None) -> dict:
        state = {"phase": "IMPLEMENT", "proposals_handled": []}

        def fake_save_state(cfg, s):
            self.state_path.write_text(json.dumps(s))

        def fake_run(cmd, **kw):
            result = MagicMock()
            if "implement.sh" in str(cmd[0]):
                result.returncode = implement_rc
            elif "closure_test.sh" in str(cmd[0]):
                result.returncode = closure_rc
                if closure_data is not None:
                    sidecar = self.bugfix.with_name(self.bugfix.stem + "_closure.json")
                    sidecar.write_text(json.dumps(closure_data))
            else:
                result.returncode = 0
            return result

        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "run", side_effect=fake_run), \
             patch.object(ae, "epoch_num", return_value=1), \
             patch.object(ae, "validator_version", return_value="v2"), \
             patch.object(ae, "_state_json_path", lambda: self.state_json), \
             patch.object(ae, "_state_path", lambda c: self.state_path), \
             patch.object(ae, "save_state", side_effect=fake_save_state):
            ae.phase_implement(self.cfg, state)
        return state

    def test_bugfix_prioritized_ahead_of_numbered_proposals(self) -> None:
        # Cap proposals to 1; BUGFIX must be the one handled, not proposal_01.
        self.cfg["runner"]["epoch"]["max_proposals_per_epoch"] = 1
        state = self._run_phase(implement_rc=0, closure_rc=0,
                                closure_data={"lift_fraction": 1.0, "holdout_regressed": None})
        self.assertIn("proposal_bug_orientation.md", state["proposals_handled"])
        self.assertNotIn("proposal_01_normal.md", state["proposals_handled"])

    def test_bugfix_promotion_writes_regression_tests(self) -> None:
        calls = []
        with patch.object(ae, "write_regression_tests",
                          side_effect=lambda *a, **k: calls.append((a, k)) or
                          {"positive_written": 1, "negative_written": 0,
                           "positive_path": "p", "negative_path": None}):
            state = self._run_phase(implement_rc=0, closure_rc=0,
                                    closure_data={"lift_fraction": 1.0, "holdout_regressed": None})
        self.assertEqual(state["phase"], "CLOSE")
        self.assertEqual(len(calls), 1)
        rule, repro, seed_id = calls[0][0]
        self.assertEqual(rule, "divide_both_sides")
        self.assertEqual(seed_id, "orientation_false_rejection")
        self.assertEqual(repro["from_srepr"], "Eq(5*R/2, h)")

    def test_bugfix_reverted_on_low_lift(self) -> None:
        state = self._run_phase(implement_rc=0, closure_rc=0,
                                closure_data={"lift_fraction": 0.0, "holdout_regressed": None})
        # Validator restored to original.
        self.assertEqual((self.validators_dir / "divide_both_sides.py").read_bytes(), b"# original\n")
        self.assertIn("proposal_bug_orientation.md", state["proposals_handled"])

    def test_bugfix_implement_failure_restores(self) -> None:
        state = self._run_phase(implement_rc=1, closure_rc=0)
        self.assertEqual((self.validators_dir / "divide_both_sides.py").read_bytes(), b"# original\n")
        self.assertIn("proposal_bug_orientation.md", state["proposals_handled"])


# ── closure_test BUGFIX path ─────────────────────────────────────────────
class ClosureBugfixTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.reports_dir = self.tmp / "reports" / "epoch_001"
        self.reports_dir.mkdir(parents=True)
        self.proposal = self.reports_dir / "proposal_bug_orientation.md"
        self.proposal.write_text(
            "**Kind**: BUGFIX\n"
            "**Affected rule**: `divide_both_sides`\n"
            "**Seed hypothesis**: orientation_false_rejection\n\n"
            "## Reproduction case\n\n"
            "- from_srepr: Eq(5*R/2, h)\n"
            "- to_srepr: Eq(h, 5*R/2)\n"
            '- args: {"divisor": "g*m"}\n'
            "- expected: PASS\n"
            "- actual: FAIL\n"
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, repro_status: str, holdout: str | None) -> int:
        cfg = {"runner": {"auto_promote": {"min_lift_fraction": 0.4}}}
        with patch.object(ct, "load_config", return_value=(cfg, "v5")), \
             patch.object(ct, "_run_reproduction",
                           return_value=(repro_status, "reason")), \
             patch.object(ct, "_holdout_regression", return_value=holdout):
            with patch.object(sys, "argv", ["closure_test.py", str(self.proposal)]):
                return ct.main()

    def test_pass_no_holdout_returns_zero(self) -> None:
        rc = self._run("PASS", None)
        self.assertEqual(rc, 0)
        sidecar = self.proposal.with_name(self.proposal.stem + "_closure.json")
        rec = json.loads(sidecar.read_text())
        self.assertEqual(rec["kind"], "BUGFIX")
        self.assertEqual(rec["actual_status"], "PASS")
        self.assertEqual(rec["lift_fraction"], 1.0)
        self.assertEqual(rec["seed_hypothesis"], "orientation_false_rejection")

    def test_fail_returns_one(self) -> None:
        rc = self._run("FAIL", None)
        self.assertEqual(rc, 1)
        sidecar = self.proposal.with_name(self.proposal.stem + "_closure.json")
        rec = json.loads(sidecar.read_text())
        self.assertEqual(rec["lift_fraction"], 0.0)

    def test_holdout_regression_returns_one(self) -> None:
        rc = self._run("PASS", "some_holdout.json")
        self.assertEqual(rc, 1)

    def test_no_reproduction_returns_one(self) -> None:
        self.proposal.write_text(
            "**Kind**: BUGFIX\n**Affected rule**: `divide_both_sides`\n"
            "**Seed hypothesis**: s1\n"
        )
        cfg = {"runner": {"auto_promote": {"min_lift_fraction": 0.4}}}
        with patch.object(ct, "load_config", return_value=(cfg, "v5")), \
             patch.object(ct, "_run_reproduction", return_value=("PASS", "")), \
             patch.object(ct, "_holdout_regression", return_value=None):
            with patch.object(sys, "argv", ["closure_test.py", str(self.proposal)]):
                rc = ct.main()
        self.assertEqual(rc, 1)


# ── Log verification (backfill bridge) ───────────────────────────────────


class EpochLogVerificationTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_logs(self, epoch: int, records: list[dict]) -> None:
        logs_dir = self.tmp / "derivations" / "logs" / f"epoch_{epoch:03d}"
        logs_dir.mkdir(parents=True, exist_ok=True)
        with (logs_dir / "batch_test.jsonl").open("w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def test_count_returns_zero_when_no_logs_dir(self) -> None:
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            self.assertEqual(ae._epoch_log_count(1), 0)

    def test_count_returns_zero_when_empty_dir(self) -> None:
        (self.tmp / "derivations" / "logs" / "epoch_001").mkdir(parents=True)
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            self.assertEqual(ae._epoch_log_count(1), 0)

    def test_count_returns_record_count(self) -> None:
        self._write_logs(1, [{"a": 1}, {"b": 2}, {"c": 3}])
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            self.assertEqual(ae._epoch_log_count(1), 3)

    def test_count_skips_blank_lines(self) -> None:
        logs_dir = self.tmp / "derivations" / "logs" / "epoch_001"
        logs_dir.mkdir(parents=True)
        with (logs_dir / "batch.jsonl").open("w") as f:
            f.write('{"a":1}\n\n  \n{"b":2}\n')
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            self.assertEqual(ae._epoch_log_count(1), 2)

    def test_verify_returns_false_when_no_logs(self) -> None:
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            self.assertFalse(ae._verify_epoch_logs(1, "TEST"))

    def test_verify_returns_true_when_logs_exist(self) -> None:
        self._write_logs(1, [{"a": 1}])
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            self.assertTrue(ae._verify_epoch_logs(1, "TEST"))


class PhaseGenerateLogGuardTests(unittest.TestCase):
    """Verify that phase_generate pauses when backfill produces no jsonl."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.state_path = self.tmp / "derivations" / "_epoch_state.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_json = self.tmp / "derivations" / "state.json"
        self.state_json.write_text(json.dumps({
            "epoch": 1, "prompt_version": "v1", "validator_version": "v2",
            "config_version": "v5"
        }))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_generate(self, *, has_logs: bool) -> dict:
        state = {"phase": "GENERATE", "batch_id": "test_batch"}
        if has_logs:
            logs_dir = self.tmp / "derivations" / "logs" / "epoch_001"
            logs_dir.mkdir(parents=True)
            (logs_dir / "batch_test.jsonl").write_text('{"a":1}\n')

        cfg = {"runner": {"state_file": "derivations/_epoch_state.json"}}

        def fake_save(c, s):
            self.state_path.write_text(json.dumps(s))

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "run", return_value=mock_result), \
             patch.object(ae, "epoch_num", return_value=1), \
             patch.object(ae, "save_state", side_effect=fake_save), \
             patch.object(ae, "_state_path", lambda c: self.state_path):
            ae.phase_generate(cfg, state, Path("derivations/targets/cohort_v1.txt"))
        return state

    def test_pauses_when_no_logs_after_generate(self) -> None:
        state = self._run_generate(has_logs=False)
        self.assertEqual(state["phase"], "PAUSED_ERROR")
        self.assertIn("backfill", state.get("error", "").lower())

    def test_advances_when_logs_exist(self) -> None:
        state = self._run_generate(has_logs=True)
        self.assertEqual(state["phase"], "ANALYZE")


if __name__ == "__main__":
    unittest.main()
