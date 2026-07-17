from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

from domains.derivation_graph import (  # noqa: E402
    load_target_evidence,
    target_identity,
    write_target_evidence,
)
from evolution.protocols import ProtocolError  # noqa: E402


def write_iteration(target_dir: Path, index: int, status: str, *, problem: dict | None = None) -> None:
    iter_dir = target_dir / f"iter_{index:02d}"
    iter_dir.mkdir(parents=True)
    (iter_dir / "status.txt").write_text(status)
    if problem is not None:
        (iter_dir / "problem.json").write_text(json.dumps(problem))


class DerivationBatchEvidenceTests(unittest.TestCase):
    def test_writes_one_neutral_record_per_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / "batch" / "targets" / "target_000"
            write_iteration(target_dir, 0, "verify_fail", problem={"id": "first"})
            write_iteration(target_dir, 1, "PASS", problem={"id": "second"})
            checkpoint = {
                "batch_id": "treatment-batch",
                "experiment_id": "mixed-ab",
                "treatment_id": "new-runner",
                "inner_mode": "rule_executor",
            }

            written = write_target_evidence(
                target_dir,
                target="solve x + 2 = 5",
                target_index=0,
                n_iterations=2,
                accepted=True,
                checkpoint=checkpoint,
            )
            restored = load_target_evidence(target_dir)

            self.assertEqual(written, restored)
            self.assertEqual(["FAIL", "PASS"], [record.status for record in restored])
            self.assertEqual([0, 1], [record.attempt_index for record in restored])
            self.assertEqual({"new-runner"}, {record.arm for record in restored})
            self.assertEqual({"mixed-ab"}, {record.cohort_id for record in restored})
            self.assertTrue(all(record.plugin_id == "derivation_graph" for record in restored))
            expected_task_id, expected_digest = target_identity("solve x + 2 = 5", 0)
            self.assertEqual({expected_task_id}, {record.task_id for record in restored})
            self.assertEqual({expected_digest}, {record.task_digest for record in restored})

            self.assertEqual(
                written,
                write_target_evidence(
                    target_dir,
                    target="solve x + 2 = 5",
                    target_index=0,
                    n_iterations=2,
                    accepted=True,
                    checkpoint=checkpoint,
                ),
            )

    def test_infrastructure_status_becomes_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / "batch" / "targets" / "target_003"
            write_iteration(target_dir, 0, "worker_error: disconnected")

            records = write_target_evidence(
                target_dir,
                target="derive a result",
                target_index=3,
                n_iterations=1,
                accepted=False,
                checkpoint={"batch_id": "batch", "inner_mode": "json"},
            )

            self.assertEqual("ERROR", records[0].status)
            self.assertEqual("worker_error: disconnected", records[0].gates[0].metrics["legacy_status"])

    def test_refuses_acceptance_disagreement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / "batch" / "targets" / "target_000"
            write_iteration(target_dir, 0, "PASS")

            with self.assertRaisesRegex(ProtocolError, "acceptance mismatch"):
                write_target_evidence(
                    target_dir,
                    target="solve x",
                    target_index=0,
                    n_iterations=1,
                    accepted=False,
                    checkpoint={"batch_id": "batch", "inner_mode": "json"},
                )


if __name__ == "__main__":
    unittest.main()
