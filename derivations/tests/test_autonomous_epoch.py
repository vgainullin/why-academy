from __future__ import annotations

import json
import os
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
from llm_cli import QuotaExhaustedError as LLMQuota  # noqa: E402


class QuotaExhaustedErrorUnificationTests(unittest.TestCase):
    """The single QuotaExhaustedError fix: claude_worker re-exports from llm_cli."""

    def test_claude_worker_quota_error_is_llm_cli_quota_error(self) -> None:
        from claude_worker import QuotaExhaustedError as ClaudeQuota
        self.assertIs(ClaudeQuota, LLMQuota)

    def test_isinstance_check_with_single_class(self) -> None:
        from claude_worker import QuotaExhaustedError as ClaudeQuota
        err = ClaudeQuota("test")
        self.assertIsInstance(err, LLMQuota)


class ClearStaleProposalsTests(unittest.TestCase):
    """clear_stale_proposals removes proposal_*.md without closure sidecars."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.epoch_dir = self.tmp / "epoch_001"
        self.epoch_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_proposal(self, name: str, with_closure: bool = False) -> Path:
        p = self.epoch_dir / name
        p.write_text("# Proposal\n**Kind**: NEW_VALIDATOR\n**Affected rule**: `foo`\n")
        if with_closure:
            stem = name.rsplit(".", 1)[0]
            (self.epoch_dir / f"{stem}_closure.json").write_text("{}")
        return p

    def test_removes_proposal_without_closure(self) -> None:
        self._make_proposal("proposal_01_foo.md")
        removed = ae.clear_stale_proposals(self.epoch_dir, set())
        self.assertEqual(removed, 1)
        self.assertFalse((self.epoch_dir / "proposal_01_foo.md").exists())

    def test_keeps_proposal_with_closure(self) -> None:
        self._make_proposal("proposal_01_foo.md", with_closure=True)
        removed = ae.clear_stale_proposals(self.epoch_dir, set())
        self.assertEqual(removed, 0)
        self.assertTrue((self.epoch_dir / "proposal_01_foo.md").exists())

    def test_keeps_proposal_in_handled(self) -> None:
        self._make_proposal("proposal_01_foo.md")
        removed = ae.clear_stale_proposals(self.epoch_dir, {"proposal_01_foo.md"})
        self.assertEqual(removed, 0)

    def test_ignores_closure_files(self) -> None:
        self._make_proposal("proposal_01_foo.md", with_closure=True)
        # The closure file itself should never be targeted
        removed = ae.clear_stale_proposals(self.epoch_dir, set())
        self.assertEqual(removed, 0)

    def test_mixed_set(self) -> None:
        self._make_proposal("proposal_01_foo.md")  # stale
        self._make_proposal("proposal_02_bar.md", with_closure=True)  # keep
        self._make_proposal("proposal_03_baz.md")  # stale
        removed = ae.clear_stale_proposals(self.epoch_dir, set())
        self.assertEqual(removed, 2)
        self.assertFalse((self.epoch_dir / "proposal_01_foo.md").exists())
        self.assertTrue((self.epoch_dir / "proposal_02_bar.md").exists())
        self.assertFalse((self.epoch_dir / "proposal_03_baz.md").exists())


class SnapshotRestoreTests(unittest.TestCase):
    """Snapshot/restore round-trips for validator files and state.json."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.validators_dir = self.tmp / "derivations" / "validators"
        self.validators_dir.mkdir(parents=True)
        self.state_json = self.tmp / "derivations" / "state.json"
        self.state_json.parent.mkdir(parents=True, exist_ok=True)
        self.state_json.write_text(json.dumps({
            "epoch": 1, "prompt_version": "v1", "validator_version": "v2", "config_version": "v5"
        }))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_snapshot_existing_validator(self) -> None:
        rule_path = self.validators_dir / "my_rule.py"
        rule_path.write_bytes(b"# original code\n")
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            snap = ae.snapshot_validator("my_rule")
        self.assertIsNotNone(snap)
        assert snap is not None
        self.assertTrue(snap["existed"])
        self.assertEqual(snap["content"], b"# original code\n")

    def test_snapshot_missing_validator(self) -> None:
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            snap = ae.snapshot_validator("nonexistent")
        self.assertIsNotNone(snap)
        assert snap is not None
        self.assertFalse(snap["existed"])
        self.assertIsNone(snap["content"])

    def test_restore_validator_existing(self) -> None:
        rule_path = self.validators_dir / "my_rule.py"
        rule_path.write_bytes(b"# original\n")
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            snap = ae.snapshot_validator("my_rule")
            rule_path.write_bytes(b"# modified by LLM\n")
            ae.restore_validator_snapshot(snap)
        self.assertEqual(rule_path.read_bytes(), b"# original\n")

    def test_restore_validator_was_deleted(self) -> None:
        rule_path = self.validators_dir / "my_rule.py"
        rule_path.write_bytes(b"# original\n")
        with patch.object(ae, "PROJECT_ROOT", self.tmp):
            snap = ae.snapshot_validator("my_rule")
            rule_path.unlink()
            ae.restore_validator_snapshot(snap)
        self.assertTrue(rule_path.exists())
        self.assertEqual(rule_path.read_bytes(), b"# original\n")

    def test_restore_validator_never_existed(self) -> None:
        rule_path = self.validators_dir / "new_rule.py"
        rule_path.write_bytes(b"# LLM created this\n")
        snap = {"path": rule_path, "existed": False, "content": None}
        ae.restore_validator_snapshot(snap)
        self.assertFalse(rule_path.exists())

    def test_state_json_snapshot_restore(self) -> None:
        with patch.object(ae, "_state_json_path", lambda: self.state_json):
            original = self.state_json.read_bytes()
            snap = ae.snapshot_state_json()
            self.state_json.write_text(json.dumps({
                "epoch": 1, "validator_version": "v3", "config_version": "v5"
            }))
            ae.restore_state_json(snap)
        self.assertEqual(self.state_json.read_bytes(), original)


class AffectedRuleFromProposalTests(unittest.TestCase):

    def test_extracts_rule(self) -> None:
        tmp = Path(tempfile.mktemp(suffix=".md"))
        tmp.write_text("# Proposal 1\n**Kind**: NEW_VALIDATOR\n**Affected rule**: `divide_both_sides`\n")
        rule = ae.affected_rule_from_proposal(tmp)
        self.assertEqual(rule, "divide_both_sides")
        tmp.unlink()

    def test_extracts_rule_without_backticks(self) -> None:
        tmp = Path(tempfile.mktemp(suffix=".md"))
        tmp.write_text("**Affected rule**: substitute_value\n")
        rule = ae.affected_rule_from_proposal(tmp)
        self.assertEqual(rule, "substitute_value")
        tmp.unlink()

    def test_returns_none_when_missing(self) -> None:
        tmp = Path(tempfile.mktemp(suffix=".md"))
        tmp.write_text("# Proposal 1\n**Kind**: INVESTIGATE\n")
        rule = ae.affected_rule_from_proposal(tmp)
        self.assertIsNone(rule)
        tmp.unlink()


class PhaseGenerateExitCodeTests(unittest.TestCase):
    """phase_generate: only advance to ANALYZE on rc 0 or 1; pause on 2/70; PAUSED_QUOTA on 75."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = {"runner": {"state_file": "derivations/_epoch_state.json"}}
        self.state_path = self.tmp / "derivations" / "_epoch_state.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_phase(self, returncode: int) -> dict:
        state = {"phase": "GENERATE"}
        mock_result = MagicMock(returncode=returncode)

        # Create fake jsonl logs so the post-GENERATE log verification passes.
        logs_dir = self.tmp / "derivations" / "logs" / "epoch_001"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "batch_test.jsonl").write_text('{"target": "fake"}\n')

        def fake_save_state(cfg, s):
            self.state_path.write_text(json.dumps(s))

        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "run", return_value=mock_result), \
             patch.object(ae, "epoch_num", return_value=1), \
             patch.object(ae, "_state_path", lambda c: self.state_path), \
             patch.object(ae, "save_state", side_effect=fake_save_state):
            ae.phase_generate(self.cfg, state, Path("queue.txt"))

        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return state

    def test_rc_0_advances_to_analyze(self) -> None:
        state = self._run_phase(0)
        self.assertEqual(state["phase"], "ANALYZE")

    def test_rc_1_advances_to_analyze(self) -> None:
        state = self._run_phase(1)
        self.assertEqual(state["phase"], "ANALYZE")

    def test_rc_2_writes_paused_error(self) -> None:
        state = self._run_phase(2)
        self.assertEqual(state["phase"], "PAUSED_ERROR")
        self.assertEqual(state["resume_phase"], "GENERATE")
        self.assertIn("batch.sh exited 2", state["error"])

    def test_rc_70_writes_paused_error(self) -> None:
        state = self._run_phase(70)
        self.assertEqual(state["phase"], "PAUSED_ERROR")
        self.assertIn("batch.sh exited 70", state["error"])

    def test_rc_75_writes_paused_quota(self) -> None:
        state = self._run_phase(75)
        self.assertEqual(state["phase"], "PAUSED_QUOTA")
        self.assertEqual(state["resume_phase"], "GENERATE")


class PhaseImplementSnapshotRestoreTests(unittest.TestCase):
    """phase_implement restores both validator file AND state.json on failure."""

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
        self.rule_path = self.validators_dir / f"{self.rule}.py"
        self.rule_path.write_bytes(b"# original validator code\n")

        self.proposal = self.reports_dir / "proposal_01_divide_both_sides.md"
        self.proposal.write_text(
            "**Kind**: STRENGTHEN_VALIDATOR\n**Affected rule**: `divide_both_sides`\n"
        )

        self.cfg = {
            "runner": {
                "auto_promote": {"min_lift_fraction": 0.4, "revert_on_holdout_regression": True},
                "epoch": {"max_proposals_per_epoch": 5, "stop_on_first_failed_promotion": False},
            }
        }
        self.state_path = self.tmp / "derivations" / "_epoch_state.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_phase(self, implement_rc: int, closure_rc: int,
                   closure_data: dict | None = None) -> None:
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
                    sidecar = self.proposal.with_name(self.proposal.stem + "_closure.json")
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

    def test_implement_failure_restores_validator_and_state(self) -> None:
        # Simulate LLM modifying both the validator and state.json during implement.sh
        def fake_run(cmd, **kw):
            result = MagicMock()
            if "implement.sh" in str(cmd[0]):
                self.rule_path.write_bytes(b"# LLM modified this\n")
                self.state_json.write_text(json.dumps({
                    "epoch": 1, "validator_version": "v3", "config_version": "v5"
                }))
                result.returncode = 1
            else:
                result.returncode = 0
            return result

        state = {"phase": "IMPLEMENT", "proposals_handled": []}

        def fake_save_state(cfg, s):
            self.state_path.write_text(json.dumps(s))

        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "run", side_effect=fake_run), \
             patch.object(ae, "epoch_num", return_value=1), \
             patch.object(ae, "validator_version", return_value="v2"), \
             patch.object(ae, "_state_json_path", lambda: self.state_json), \
             patch.object(ae, "_state_path", lambda c: self.state_path), \
             patch.object(ae, "save_state", side_effect=fake_save_state):
            ae.phase_implement(self.cfg, state)

        # Both should be restored to original
        self.assertEqual(self.rule_path.read_bytes(), b"# original validator code\n")
        restored_state = json.loads(self.state_json.read_text())
        self.assertEqual(restored_state["validator_version"], "v2")

    def test_closure_no_sidecar_restores_validator_and_state(self) -> None:
        self._run_phase(implement_rc=0, closure_rc=0, closure_data=None)
        self.assertEqual(self.rule_path.read_bytes(), b"# original validator code\n")

    def test_revert_on_low_lift_restores_validator_and_state(self) -> None:
        self._run_phase(
            implement_rc=0, closure_rc=0,
            closure_data={"lift_fraction": 0.1, "holdout_regressed": False},
        )
        self.assertEqual(self.rule_path.read_bytes(), b"# original validator code\n")
        restored_state = json.loads(self.state_json.read_text())
        self.assertEqual(restored_state["validator_version"], "v2")

    def test_promote_on_sufficient_lift_keeps_changes(self) -> None:
        self._run_phase(
            implement_rc=0, closure_rc=0,
            closure_data={"lift_fraction": 0.5, "holdout_regressed": False},
        )
        # Validator not restored (stays as-is since we didn't modify it in this test)
        self.assertEqual(self.rule_path.read_bytes(), b"# original validator code\n")

    def test_quota_during_implement_restores_and_pauses(self) -> None:
        state = {"phase": "IMPLEMENT", "proposals_handled": []}

        def fake_save_state(cfg, s):
            self.state_path.write_text(json.dumps(s))

        def fake_run(cmd, **kw):
            result = MagicMock()
            result.returncode = 75
            return result

        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "run", side_effect=fake_run), \
             patch.object(ae, "epoch_num", return_value=1), \
             patch.object(ae, "validator_version", return_value="v2"), \
             patch.object(ae, "_state_json_path", lambda: self.state_json), \
             patch.object(ae, "_state_path", lambda c: self.state_path), \
             patch.object(ae, "save_state", side_effect=fake_save_state):
            ae.phase_implement(self.cfg, state)

        self.assertEqual(state["phase"], "PAUSED_QUOTA")
        self.assertEqual(state["resume_phase"], "IMPLEMENT")
        self.assertEqual(self.rule_path.read_bytes(), b"# original validator code\n")


class ResumeFromPauseTests(unittest.TestCase):
    """_resume_from_pause clears all resumable pause states."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.state_path = self.tmp / "_epoch_state.json"
        self.cfg = {"runner": {"state_file": "_epoch_state.json"}}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _resume(self, state: dict) -> dict:
        def fake_save_state(cfg, s):
            self.state_path.write_text(json.dumps(s))
        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "_state_path", lambda c: self.state_path), \
             patch.object(ae, "save_state", side_effect=fake_save_state):
            ae._resume_from_pause(state, self.cfg)
        return state

    def test_resumes_from_paused_quota(self) -> None:
        state = {"phase": "PAUSED_QUOTA", "resume_phase": "GENERATE"}
        self._resume(state)
        self.assertEqual(state["phase"], "GENERATE")
        self.assertNotIn("resume_phase", state)

    def test_resumes_from_paused_error(self) -> None:
        state = {"phase": "PAUSED_ERROR", "resume_phase": "IMPLEMENT", "error": "boom"}
        self._resume(state)
        self.assertEqual(state["phase"], "IMPLEMENT")
        self.assertNotIn("error", state)

    def test_resumes_from_paused_wallclock(self) -> None:
        state = {"phase": "PAUSED_WALLCLOCK", "resume_phase": "ANALYZE"}
        self._resume(state)
        self.assertEqual(state["phase"], "ANALYZE")

    def test_resumes_from_paused_signal(self) -> None:
        state = {"phase": "PAUSED_SIGNAL", "resume_phase": "CLOSE", "error": "signal: SIGTERM"}
        self._resume(state)
        self.assertEqual(state["phase"], "CLOSE")

    def test_does_not_touch_done(self) -> None:
        state = {"phase": "DONE"}
        self._resume(state)
        self.assertEqual(state["phase"], "DONE")

    def test_does_not_touch_active_phase(self) -> None:
        state = {"phase": "GENERATE"}
        self._resume(state)
        self.assertEqual(state["phase"], "GENERATE")

    def test_defaults_to_generate_when_no_resume_phase(self) -> None:
        state = {"phase": "PAUSED_QUOTA"}
        self._resume(state)
        self.assertEqual(state["phase"], "GENERATE")


class WritePauseStateTests(unittest.TestCase):
    """_write_pause_state writes all fields and persists."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.state_path = self.tmp / "_epoch_state.json"
        self.cfg = {"runner": {"state_file": "_epoch_state.json"}}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_paused_error_with_traceback(self) -> None:
        state = {"phase": "IMPLEMENT"}
        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "_state_path", lambda c: self.state_path), \
             patch.object(ae, "save_state", lambda cfg, s: self.state_path.write_text(json.dumps(s))):
            ae._write_pause_state(self.cfg, state, "PAUSED_ERROR",
                                  resume_phase="IMPLEMENT", error="KeyError: 'foo'")
        self.assertEqual(state["phase"], "PAUSED_ERROR")
        self.assertEqual(state["resume_phase"], "IMPLEMENT")
        self.assertEqual(state["error"], "KeyError: 'foo'")
        self.assertIn("paused_at", state)


class ImplementVersionBumpTests(unittest.TestCase):
    """Test the validator_version bump logic that was moved from the LLM to implement.sh."""

    def _bump_version(self, state_json: dict) -> str:
        """Replicate the bump logic from implement.sh in Python for testing."""
        import re
        old = state_json["validator_version"]
        m = re.match(r"v?(\d+)", old)
        new = f"v{int(m.group(1)) + 1}"
        state_json["validator_version"] = new
        return new

    def test_bump_v1_to_v2(self) -> None:
        d = {"validator_version": "v1"}
        new = self._bump_version(d)
        self.assertEqual(new, "v2")
        self.assertEqual(d["validator_version"], "v2")

    def test_bump_v9_to_v10(self) -> None:
        d = {"validator_version": "v9"}
        new = self._bump_version(d)
        self.assertEqual(new, "v10")

    def test_bump_strips_v_prefix(self) -> None:
        d = {"validator_version": "5"}
        new = self._bump_version(d)
        self.assertEqual(new, "v6")

    def test_bump_preserves_other_fields(self) -> None:
        d = {"epoch": 3, "validator_version": "v2", "config_version": "v5", "prompt_version": "v1"}
        self._bump_version(d)
        self.assertEqual(d["epoch"], 3)
        self.assertEqual(d["config_version"], "v5")
        self.assertEqual(d["prompt_version"], "v1")
        self.assertEqual(d["validator_version"], "v3")


class NonDestructiveArtifactHandlingTests(unittest.TestCase):
    """Stale canonical artifacts should be moved aside, not deleted."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.problems_dir = self.tmp / "derivations" / "problems"
        self.problems_dir.mkdir(parents=True)
        self.iter_dir = self.tmp / "iter_00"
        self.iter_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_move_stale_artifacts_to_prior_dir(self) -> None:
        import shutil as sh
        problem_id = "evo_test_t000_i00"
        problem_file = self.problems_dir / f"{problem_id}.json"
        problem_file.write_text('{"old": true}')
        verifier_file = self.problems_dir / f"{problem_id}.verifier.json"
        verifier_file.write_text('{"edges": []}')

        prior_dir = self.iter_dir / ".prior"
        for stale in self.problems_dir.glob(f"{problem_id}.*"):
            prior_dir.mkdir(exist_ok=True)
            sh.move(str(stale), str(prior_dir / stale.name))

        self.assertFalse(problem_file.exists())
        self.assertFalse(verifier_file.exists())
        self.assertTrue((prior_dir / f"{problem_id}.json").exists())
        self.assertTrue((prior_dir / f"{problem_id}.verifier.json").exists())

    def test_no_stale_artifacts_no_prior_dir(self) -> None:
        problem_id = "evo_test_t000_i00"
        prior_dir = self.iter_dir / ".prior"
        for stale in self.problems_dir.glob(f"{problem_id}.*"):
            prior_dir.mkdir(exist_ok=True)
            sh.move(str(stale), str(prior_dir / stale.name))
        self.assertFalse(prior_dir.exists())


class PromptForbidsStateJsonTests(unittest.TestCase):
    """The implement_proposal.md prompt must forbid modifying state.json."""

    def test_state_json_in_forbidden_list(self) -> None:
        prompt = (DERIVATIONS / "prompts" / "implement_proposal.md").read_text()
        self.assertIn("state.json", prompt)

    def test_prompt_does_not_ask_llm_to_bump_version(self) -> None:
        prompt = (DERIVATIONS / "prompts" / "implement_proposal.md").read_text()
        # The old step 5 that told the LLM to bump validator_version should be gone
        self.assertNotIn("Bump `validator_version`", prompt)
        self.assertNotIn("increment `validator_version`", prompt)

    def test_prompt_says_wrapper_handles_version(self) -> None:
        prompt = (DERIVATIONS / "prompts" / "implement_proposal.md").read_text()
        self.assertIn("implement.sh wrapper", prompt)


class ExperimentPhaseTests(unittest.TestCase):
    """Tests for the EXPERIMENT phase: config gating, target selection, verdict logic."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.state_path = self.tmp / "_epoch_state.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_json = self.tmp / "derivations" / "state.json"
        self.state_json.parent.mkdir(parents=True, exist_ok=True)
        self.state_json.write_text(json.dumps({
            "epoch": 1, "prompt_version": "v1", "validator_version": "v2", "config_version": "v5"
        }))
        self.queue_path = self.tmp / "queue.txt"
        self.queue_path.write_text("# test queue\nsolve x + 2 = 5 for x\nderive E = mc^2\nsolve 3x = 12\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_phase(self, cfg: dict, state: dict) -> dict:
        def fake_save_state(c, s):
            self.state_path.write_text(json.dumps(s))
        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "_state_path", lambda c: self.state_path), \
             patch.object(ae, "_state_json_path", lambda: self.state_json), \
             patch.object(ae, "save_state", side_effect=fake_save_state), \
             patch.object(ae, "epoch_num", return_value=1):
            ae.phase_experiment(cfg, state, self.queue_path)
        return state

    def test_disabled_skips_to_implement(self) -> None:
        cfg = {"runner": {"experiment": {"enabled": False}}}
        state = {"phase": "EXPERIMENT"}
        self._run_phase(cfg, state)
        self.assertEqual(state["phase"], "IMPLEMENT")

    def test_no_experiment_section_skips_to_implement(self) -> None:
        cfg = {"runner": {}}
        state = {"phase": "EXPERIMENT"}
        self._run_phase(cfg, state)
        self.assertEqual(state["phase"], "IMPLEMENT")

    def test_too_few_targets_skips(self) -> None:
        queue = self.tmp / "small_queue.txt"
        queue.write_text("# one target\nsolve x = 1\n")
        cfg = {"runner": {"experiment": {"enabled": True, "max_targets": 5}}}
        state = {"phase": "EXPERIMENT"}
        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "_state_path", lambda c: self.state_path), \
             patch.object(ae, "save_state", lambda c, s: self.state_path.write_text(json.dumps(s))), \
             patch.object(ae, "epoch_num", return_value=1):
            ae.phase_experiment(cfg, state, queue)
        self.assertEqual(state["phase"], "IMPLEMENT")

    def test_existing_verdict_skips_to_implement(self) -> None:
        cfg = {"runner": {"experiment": {"enabled": True, "max_targets": 5}}}
        state = {"phase": "EXPERIMENT", "experiment_id": "test_exp"}
        epoch_dir = self.tmp / "derivations" / "reports" / "epoch_001"
        epoch_dir.mkdir(parents=True)
        (epoch_dir / "experiment_verdict.json").write_text('{"status": "neutral"}')
        self._run_phase(cfg, state)
        self.assertEqual(state["phase"], "IMPLEMENT")


class ExperimentTargetSelectionTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.queue = self.tmp / "queue.txt"
        self.queue.write_text(
            "# header comment\n"
            "solve x + 2 = 5 for x\n"
            "derive E = mc^2\n"
            "# mid comment\n"
            "solve 3x = 12\n"
            "factor x^2 - 9\n"
            "derive v = u + at\n"
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_selects_up_to_max(self) -> None:
        cfg = {"runner": {"experiment": {"max_targets": 3}}}
        state = {}
        targets = ae._experiment_targets(cfg, state, self.queue)
        self.assertEqual(len(targets), 3)
        self.assertNotIn("# header comment", targets)

    def test_selects_all_if_fewer_than_max(self) -> None:
        cfg = {"runner": {"experiment": {"max_targets": 10}}}
        state = {}
        targets = ae._experiment_targets(cfg, state, self.queue)
        self.assertEqual(len(targets), 5)

    def test_ignores_comments_and_blanks(self) -> None:
        cfg = {"runner": {"experiment": {"max_targets": 100}}}
        state = {}
        targets = ae._experiment_targets(cfg, state, self.queue)
        for t in targets:
            self.assertFalse(t.startswith("#"))
            self.assertTrue(t.strip())


class ExperimentVerdictTests(unittest.TestCase):
    """Test the verdict logic by mocking batch runs and ab_compare."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.state_path = self.tmp / "_epoch_state.json"
        self.state_json = self.tmp / "derivations" / "state.json"
        self.state_json.parent.mkdir(parents=True, exist_ok=True)
        self.state_json.write_text(json.dumps({
            "epoch": 1, "prompt_version": "v1", "validator_version": "v2", "config_version": "v5"
        }))
        self.queue_path = self.tmp / "queue.txt"
        self.queue_path.write_text("# queue\nsolve x + 2 = 5\nderive E = mc^2\nsolve 3x = 12\n")
        self.epoch_dir = self.tmp / "derivations" / "reports" / "epoch_001"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_with_mock_batches(self, cfg: dict, *, comparison_data: dict | None) -> dict:
        state = {"phase": "EXPERIMENT"}

        def fake_save_state(c, s):
            self.state_path.write_text(json.dumps(s))

        def fake_run(cmd, **kw):
            result = MagicMock()
            cmd_str = " ".join(str(c) for c in cmd)
            if "batch.sh" in cmd_str:
                result.returncode = 0
                # Simulate batch creating checkpoint + target_metrics
                batch_id_idx = cmd.index("--batch-id") + 1 if "--batch-id" in cmd else -1
                if batch_id_idx > 0:
                    bid = cmd[batch_id_idx]
                    bdir = self.tmp / "derivations" / "_evolutions" / "batches" / bid
                    tdir = bdir / "targets" / "target_000"
                    tdir.mkdir(parents=True, exist_ok=True)
                    (bdir / "checkpoint.json").write_text(json.dumps({"batch_id": bid, "inner_mode": "json"}))
                    (tdir / "target_metrics.json").write_text(json.dumps({"target_index": 0, "accepted": True}))
                    (tdir / "target.json").write_text(json.dumps({"target": "solve x + 2 = 5"}))
            elif "ab_compare.py" in cmd_str:
                result.returncode = 0 if comparison_data else 2
                if comparison_data:
                    treatment_idx = cmd.index("--treatment") + 1 if "--treatment" in cmd else -1
                    if treatment_idx > 0:
                        tdir = Path(cmd[treatment_idx])
                        (tdir / "ab_comparison.json").write_text(json.dumps(comparison_data))
            else:
                result.returncode = 0
            return result

        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "_state_path", lambda c: self.state_path), \
             patch.object(ae, "_state_json_path", lambda: self.state_json), \
             patch.object(ae, "save_state", side_effect=fake_save_state), \
             patch.object(ae, "epoch_num", return_value=1), \
             patch.object(ae, "run", side_effect=fake_run):
            ae.phase_experiment(cfg, state, self.queue_path)
        return state

    def test_treatment_won_verdict(self) -> None:
        cfg = {"runner": {"experiment": {
            "enabled": True, "max_targets": 3,
            "control_inner_mode": "json",
            "treatment_inner_mode": "rule_executor",
            "treatment_normalization_mode": "preserve-executor-boundaries",
            "min_acceptance_delta": 0.0,
            "promote_on_win": False,
        }}}
        comparison = {"paired": {
            "acceptance_delta": 0.5,
            "control_acceptance_rate": 0.25,
            "treatment_acceptance_rate": 0.75,
            "first_try_pass_delta": 0.5,
            "n_pairs": 3,
            "both_accepted": 1,
            "treatment_only_accepted": 1,
            "control_only_accepted": 0,
            "both_failed": 1,
        }}
        state = self._run_with_mock_batches(cfg, comparison_data=comparison)
        self.assertEqual(state["phase"], "IMPLEMENT")
        verdict = json.loads((self.epoch_dir / "experiment_verdict.json").read_text())
        self.assertEqual(verdict["status"], "treatment_won")
        self.assertEqual(verdict["acceptance_delta"], 0.5)
        self.assertNotIn("promoted_experiment", state)

    def test_promote_on_win_sets_promoted_experiment(self) -> None:
        cfg = {"runner": {"experiment": {
            "enabled": True, "max_targets": 3,
            "control_inner_mode": "json",
            "treatment_inner_mode": "rule_executor",
            "treatment_normalization_mode": "preserve-executor-boundaries",
            "min_acceptance_delta": 0.0,
            "promote_on_win": True,
        }}}
        comparison = {"paired": {
            "acceptance_delta": 0.3,
            "control_acceptance_rate": 0.3,
            "treatment_acceptance_rate": 0.6,
            "first_try_pass_delta": 0.3,
            "n_pairs": 3,
            "both_accepted": 1,
            "treatment_only_accepted": 1,
            "control_only_accepted": 0,
            "both_failed": 1,
        }}
        state = self._run_with_mock_batches(cfg, comparison_data=comparison)
        self.assertIn("promoted_experiment", state)
        self.assertEqual(state["promoted_experiment"]["inner_mode"], "rule_executor")

    def test_control_won_verdict(self) -> None:
        cfg = {"runner": {"experiment": {
            "enabled": True, "max_targets": 3,
            "min_acceptance_delta": 0.0,
            "promote_on_win": False,
        }}}
        comparison = {"paired": {
            "acceptance_delta": -0.25,
            "control_acceptance_rate": 0.75,
            "treatment_acceptance_rate": 0.5,
            "first_try_pass_delta": -0.25,
            "n_pairs": 3,
            "both_accepted": 1,
            "treatment_only_accepted": 0,
            "control_only_accepted": 1,
            "both_failed": 1,
        }}
        state = self._run_with_mock_batches(cfg, comparison_data=comparison)
        verdict = json.loads((self.epoch_dir / "experiment_verdict.json").read_text())
        self.assertEqual(verdict["status"], "control_won")
        self.assertNotIn("promoted_experiment", state)

    def test_neutral_verdict(self) -> None:
        cfg = {"runner": {"experiment": {
            "enabled": True, "max_targets": 3,
            "min_acceptance_delta": 0.0,
            "promote_on_win": False,
        }}}
        comparison = {"paired": {
            "acceptance_delta": 0.0,
            "control_acceptance_rate": 0.5,
            "treatment_acceptance_rate": 0.5,
            "first_try_pass_delta": 0.0,
            "n_pairs": 3,
            "both_accepted": 1,
            "treatment_only_accepted": 0,
            "control_only_accepted": 0,
            "both_failed": 2,
        }}
        state = self._run_with_mock_batches(cfg, comparison_data=comparison)
        verdict = json.loads((self.epoch_dir / "experiment_verdict.json").read_text())
        self.assertEqual(verdict["status"], "neutral")

    def test_comparison_failure_verdict(self) -> None:
        cfg = {"runner": {"experiment": {
            "enabled": True, "max_targets": 3,
            "min_acceptance_delta": 0.0,
            "promote_on_win": False,
        }}}
        state = self._run_with_mock_batches(cfg, comparison_data=None)
        verdict = json.loads((self.epoch_dir / "experiment_verdict.json").read_text())
        self.assertEqual(verdict["status"], "comparison_failed")

    def test_quota_pause_during_control(self) -> None:
        cfg = {"runner": {"experiment": {
            "enabled": True, "max_targets": 3,
        }}}
        state = {"phase": "EXPERIMENT"}

        def fake_save_state(c, s):
            self.state_path.write_text(json.dumps(s))

        def fake_run(cmd, **kw):
            result = MagicMock()
            result.returncode = 75  # quota
            return result

        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "_state_path", lambda c: self.state_path), \
             patch.object(ae, "_state_json_path", lambda: self.state_json), \
             patch.object(ae, "save_state", side_effect=fake_save_state), \
             patch.object(ae, "epoch_num", return_value=1), \
             patch.object(ae, "run", side_effect=fake_run):
            ae.phase_experiment(cfg, state, self.queue_path)
        self.assertEqual(state["phase"], "PAUSED_QUOTA")
        self.assertEqual(state["resume_phase"], "EXPERIMENT")


class PhasesListTests(unittest.TestCase):

    def test_experiment_in_phases(self) -> None:
        self.assertIn("EXPERIMENT", ae.PHASES)

    def test_phases_order(self) -> None:
        idx = {p: i for i, p in enumerate(ae.PHASES)}
        self.assertLess(idx["ANALYZE"], idx["EXPERIMENT"])
        self.assertLess(idx["EXPERIMENT"], idx["IMPLEMENT"])


class PromptUpdateProposalTests(unittest.TestCase):
    """PROMPT_UPDATE proposals go through promote_prompt.sh, not implement.sh."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.state_json = self.tmp / "derivations" / "state.json"
        self.state_json.parent.mkdir(parents=True, exist_ok=True)
        self.state_json.write_text(json.dumps({
            "epoch": 1, "prompt_version": "v1", "validator_version": "v2", "config_version": "v5"
        }))
        self.prompt_path = self.tmp / "derivations" / "prompts" / "generate_derivation.md"
        self.prompt_path.parent.mkdir(parents=True, exist_ok=True)
        self.prompt_path.write_bytes(b"# original prompt\n")

        self.reports_dir = self.tmp / "derivations" / "reports" / "epoch_001"
        self.reports_dir.mkdir(parents=True)
        self.proposal = self.reports_dir / "proposal_01_prompt_fix.md"
        self.proposal.write_text("**Kind**: PROMPT_UPDATE\n**Affected rule**: none\n")

        self.cfg = {
            "runner": {
                "auto_promote": {"min_lift_fraction": 0.4, "revert_on_holdout_regression": True},
                "epoch": {"max_proposals_per_epoch": 5, "stop_on_first_failed_promotion": False},
            }
        }
        self.state_path = self.tmp / "derivations" / "_epoch_state.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_phase(self, promote_rc: int) -> dict:
        state = {"phase": "IMPLEMENT", "proposals_handled": []}

        def fake_save_state(cfg, s):
            self.state_path.write_text(json.dumps(s))

        def fake_run(cmd, **kw):
            result = MagicMock()
            cmd_str = " ".join(str(c) for c in cmd)
            if "promote_prompt.sh" in cmd_str:
                result.returncode = promote_rc
                if promote_rc == 0:
                    # Simulate prompt modification + version bump
                    self.prompt_path.write_bytes(b"# original prompt\n\n## Addendum\nnew rule\n")
                    d = json.loads(self.state_json.read_text())
                    d["prompt_version"] = "v2"
                    self.state_json.write_text(json.dumps(d, indent=2))
            else:
                result.returncode = 0
            return result

        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "run", side_effect=fake_run), \
             patch.object(ae, "epoch_num", return_value=1), \
             patch.object(ae, "_state_json_path", lambda: self.state_json), \
             patch.object(ae, "_state_path", lambda c: self.state_path), \
             patch.object(ae, "save_state", side_effect=fake_save_state):
            ae.phase_implement(self.cfg, state)
        return state

    def test_successful_prompt_promotion(self) -> None:
        state = self._run_phase(promote_rc=0)
        self.assertIn("proposal_01_prompt_fix.md", state["proposals_handled"])
        self.assertEqual(state["phase"], "CLOSE")
        # Prompt was modified (not reverted)
        self.assertIn(b"Addendum", self.prompt_path.read_bytes())

    def test_denied_prompt_proposal_reverts(self) -> None:
        # Simulate promote_prompt.sh modifying the prompt then returning DENIED (rc=2)
        def fake_run(cmd, **kw):
            result = MagicMock()
            cmd_str = " ".join(str(c) for c in cmd)
            if "promote_prompt.sh" in cmd_str:
                self.prompt_path.write_bytes(b"# modified before denial\n")
                d = json.loads(self.state_json.read_text())
                d["prompt_version"] = "v2"
                self.state_json.write_text(json.dumps(d, indent=2))
                result.returncode = 2
            else:
                result.returncode = 0
            return result

        state = {"phase": "IMPLEMENT", "proposals_handled": []}

        def fake_save_state(cfg, s):
            self.state_path.write_text(json.dumps(s))

        with patch.object(ae, "PROJECT_ROOT", self.tmp), \
             patch.object(ae, "run", side_effect=fake_run), \
             patch.object(ae, "epoch_num", return_value=1), \
             patch.object(ae, "_state_json_path", lambda: self.state_json), \
             patch.object(ae, "_state_path", lambda c: self.state_path), \
             patch.object(ae, "save_state", side_effect=fake_save_state):
            ae.phase_implement(self.cfg, state)

        self.assertIn("proposal_01_prompt_fix.md", state["proposals_handled"])
        self.assertEqual(self.prompt_path.read_bytes(), b"# original prompt\n")

    def test_quota_pause_during_prompt_promotion(self) -> None:
        state = self._run_phase(promote_rc=75)
        self.assertEqual(state["phase"], "PAUSED_QUOTA")
        self.assertEqual(state["resume_phase"], "IMPLEMENT")
        # Prompt should be reverted
        self.assertEqual(self.prompt_path.read_bytes(), b"# original prompt\n")


if __name__ == "__main__":
    unittest.main()
