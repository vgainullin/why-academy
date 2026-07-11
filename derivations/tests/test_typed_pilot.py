from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import typed_pilot  # noqa: E402
from frozen_task_store import FrozenTaskStore  # noqa: E402


class TypedPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = DERIVATIONS / "practice" / "algebra_linear_8th_grade_summer.json"
        cls.bundle_sha256 = hashlib.sha256(cls.bundle.read_bytes()).hexdigest()
        cls.store = FrozenTaskStore.load(cls.bundle, cls.bundle_sha256)
        cls.contract = cls.store.get_task("alg8-lin-001")

    def test_public_envelope_excludes_private_correctness_fields(self) -> None:
        public = typed_pilot.public_task_envelope(self.contract)

        self.assertEqual("derivation_task_public.v2", public["schema_version"])
        self.assertEqual(
            {"schema_version", "id", "task_type", "display", "givens", "requirements"},
            set(public),
        )
        self.assertNotIn("expected", public)
        self.assertNotIn("answer", json.dumps(public))
        self.assertNotIn("contract_digest", public)

    def test_generation_failure_is_error_and_never_accepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            record = {
                "bundle_sha256": "sha256:" + self.bundle_sha256,
                "selected_task_list_sha256": self.store.selected_task_list_digest([self.contract["id"]]),
                "oracle": {"commit": "frozen"},
                "evaluator_version": "test",
            }
            acceptance = typed_pilot.run_task(
                contract=self.contract,
                task_index=0,
                out_dir=out,
                candidate_root=out / "candidate-without-generator",
                candidate_python="/missing/python",
                trusted_python=sys.executable,
                engine="fixture",
                model="fixture",
                judge_engine="fixture",
                judge_model="fixture",
                generation_timeout=1,
                gate_timeout=1,
                run_record=record,
                resume=False,
            )
            self.assertEqual("ERROR", acceptance["status"])
            self.assertFalse((out / "tasks" / "task_000_alg8-lin-001" / "ACCEPTED.txt").exists())
            self.assertEqual("ERROR", json.loads(
                (out / "tasks" / "task_000_alg8-lin-001" / "acceptance.json").read_text()
            )["status"])

    def test_resume_provenance_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            record = {"schema_version": "typed_derivation_pilot.v1", "task_ids": ["a"]}
            typed_pilot._prepare_run_dir(out, record, resume=False)
            with self.assertRaises(typed_pilot.TypedPilotError):
                typed_pilot._prepare_run_dir(
                    out,
                    {"schema_version": "typed_derivation_pilot.v1", "task_ids": ["b"]},
                    resume=True,
                )

    def test_deterministic_candidate_reaches_trusted_oracle_and_canvas(self) -> None:
        fixture_root = DERIVATIONS / "tests" / "fixtures" / "typed_candidate_root"
        venv_python = "/Users/vlad/projects/why-academy/derivations/.venv/bin/python"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            record = {
                "bundle_sha256": "sha256:" + self.bundle_sha256,
                "selected_task_list_sha256": self.store.selected_task_list_digest([self.contract["id"]]),
                "oracle": {"commit": "frozen"},
                "evaluator_version": "test",
            }
            real_run_logged = typed_pilot._run_logged
            generation_seen = False

            def run_logged(cmd, **kwargs):
                nonlocal generation_seen
                if any(str(part).endswith("generate_typed_graph.py") for part in cmd):
                    generation_seen = True
                    self.assertEqual(DERIVATIONS / "generate_typed_graph.py", Path(cmd[1]))
                    self.assertEqual("read-only", kwargs["env"]["CODEX_SANDBOX"])
                    self.assertEqual("1", kwargs["env"]["CODEX_SKIP_GIT_REPO_CHECK"])
                    self.assertNotIn("DEEPSEEK_API_KEY", kwargs["env"])
                    fixture_generator = fixture_root / "derivations" / "generate_typed_graph.py"
                    return real_run_logged([cmd[0], str(fixture_generator), *cmd[2:]], **kwargs)
                if any(str(part).endswith("judge.py") for part in cmd):
                    submission = Path(cmd[2])
                    submission.with_name(submission.stem + ".judge.json").write_text(json.dumps({
                        "overall": "PASS",
                        "adversarial": {"status": "upheld"},
                    }))
                    return 0, None
                return real_run_logged(cmd, **kwargs)

            with patch.object(typed_pilot, "_run_logged", side_effect=run_logged):
                acceptance = typed_pilot.run_task(
                    contract=self.contract,
                    task_index=0,
                    out_dir=out,
                    candidate_root=fixture_root,
                    candidate_python=venv_python,
                    trusted_python=venv_python,
                    engine="fixture",
                    model="fixture",
                    judge_engine="fixture",
                    judge_model="fixture",
                    generation_timeout=30,
                    gate_timeout=30,
                    run_record=record,
                    resume=False,
                )

            self.assertEqual("PASS", acceptance["status"], acceptance)
            self.assertTrue(generation_seen)
            self.assertEqual("PASS", acceptance["gates"]["typed_oracle"]["status"])
            self.assertEqual("PASS", acceptance["gates"]["canvas"]["status"])


if __name__ == "__main__":
    unittest.main()
