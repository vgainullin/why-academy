from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import meta_model_compare as mmc  # noqa: E402


class MetaModelCompareTests(unittest.TestCase):
    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def write_json(self, path: Path, data: object) -> Path:
        return self.write(path, json.dumps(data, indent=2) + "\n")

    def make_project(self, tmp: Path) -> dict[str, Path]:
        project = tmp / "repo"
        prompt = self.write(
            project / "derivations" / "reports" / "epoch_008" / "run_meta.prompt.md",
            "Analyze derivations/logs/epoch_008 and write analysis_decision.json\n",
        )
        log_a = self.write(
            project / "derivations" / "logs" / "epoch_008" / "batch_epoch_008_a.jsonl",
            '{"problem_id":"a","overall":"FAIL"}\n',
        )
        log_b = self.write(
            project / "derivations" / "logs" / "epoch_008" / "batch_epoch_008_b.jsonl",
            '{"problem_id":"b","overall":"PASS"}\n',
        )
        self.write(
            project / "derivations" / "logs" / "epoch_008" / "batch_later_contaminant.jsonl",
            '{"problem_id":"late","overall":"FAIL"}\n',
        )
        self.write_json(
            project / "derivations" / "state.json",
            {
                "epoch": 9,
                "prompt_version": "v1",
                "validator_version": "v4",
                "config_version": "v5",
            },
        )
        (project / "derivations" / "logs" / "epoch_008" / "batch").mkdir(parents=True)
        baseline_decision = self.write_json(
            project / "derivations" / "reports" / "epoch_008" / "analysis_decision.json",
            {
                "route": "IMPLEMENT",
                "rationale": "baseline",
                "confidence": "medium",
                "candidate": None,
                "proposal_paths": [],
                "experiment_spec": None,
                "success_criteria": {},
                "failure_policy": "NONE",
                "fallback_route": "CONTINUE_EPOCH",
            },
        )
        baseline_console = self.write(
            project / "derivations" / "reports" / "epoch_008" / "run_meta.console.log",
            "model: gpt-5.5\nreasoning effort: none\n",
        )
        return {
            "project": project,
            "prompt": prompt,
            "log_a": log_a,
            "log_b": log_b,
            "baseline_decision": baseline_decision,
            "baseline_console": baseline_console,
        }

    def freeze(self, paths: dict[str, Path], out_root: Path) -> Path:
        mmc.freeze_packet(
            name="epoch_008_meta",
            prompt=paths["prompt"],
            logs=[paths["log_a"], paths["log_b"]],
            baseline_console=paths["baseline_console"],
            baseline_decision=paths["baseline_decision"],
            out_root=out_root,
            project_root=paths["project"],
            copy_tracked=False,
        )
        return out_root / "epoch_008_meta" / "packet.json"

    def test_freeze_packet_copies_only_selected_epoch_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_project(Path(tmp))
            packet_path = self.freeze(paths, Path(tmp) / "packets")
            packet, issues = mmc.verify_packet(packet_path)

            self.assertEqual([], issues)
            self.assertEqual("epoch_008", packet["epoch_dir"])
            self.assertEqual(
                ["batch_epoch_008_a.jsonl", "batch_epoch_008_b.jsonl"],
                packet["input"]["selected_epoch_log_names"],
            )
            self.assertIn("batch_later_contaminant.jsonl", packet["input"]["excluded_source_epoch_entries"])
            self.assertIn("batch", packet["input"]["excluded_source_epoch_entries"])
            workspace_logs = packet_path.parent / "workspace" / "derivations" / "logs" / "epoch_008"
            self.assertEqual(
                ["batch_epoch_008_a.jsonl", "batch_epoch_008_b.jsonl"],
                sorted(p.name for p in workspace_logs.iterdir()),
            )
            self.assertEqual(
                "derivations/reports/epoch_008/run_meta.prompt.md",
                packet["input"]["prompt"]["source_path"],
            )
            self.assertEqual(9, packet["checkpoint_state"]["source_epoch"])
            self.assertEqual(8, packet["checkpoint_state"]["checkpoint_epoch"])
            frozen_state = json.loads(
                (
                    packet_path.parent
                    / "workspace"
                    / packet["checkpoint_state"]["workspace_path"]
                ).read_text()
            )
            self.assertEqual(8, frozen_state["epoch"])

    def test_verify_packet_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_project(Path(tmp))
            packet_path = self.freeze(paths, Path(tmp) / "packets")
            frozen_log = (
                packet_path.parent
                / "workspace"
                / "derivations"
                / "logs"
                / "epoch_008"
                / "batch_epoch_008_a.jsonl"
            )
            frozen_log.write_text('{"problem_id":"tampered"}\n')

            _packet, issues = mmc.verify_packet(packet_path)

            issue_names = {issue["issue"] for issue in issues}
            self.assertIn("input_sha256_mismatch", issue_names)
            self.assertIn("workspace_manifest_sha256_mismatch", issue_names)

    def test_codex_command_requires_explicit_high_reasoning_config(self) -> None:
        command = mmc.build_codex_command(
            codex_bin="codex",
            workspace=Path("/tmp/workspace"),
            sandbox="workspace-write",
            model="gpt-5.5",
            reasoning_effort="xhigh",
            output=Path("/tmp/out.txt"),
        )

        self.assertEqual(command[:4], ["codex", "exec", "-C", "/tmp/workspace"])
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("--model", command)
        self.assertIn("gpt-5.5", command)
        self.assertIn('model_reasoning_effort="xhigh"', command)
        with self.assertRaises(ValueError):
            mmc.build_codex_command(
                codex_bin="codex",
                workspace=Path("/tmp/workspace"),
                sandbox="workspace-write",
                model="gpt-5.5",
                reasoning_effort="",
                output=Path("/tmp/out.txt"),
            )

    def test_run_dry_run_has_no_packet_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_project(Path(tmp))
            packet_path = self.freeze(paths, Path(tmp) / "packets")
            args = argparse.Namespace(
                packet=str(packet_path),
                arm="dry_arm",
                engine="codex",
                model="gpt-5.5",
                reasoning_effort="xhigh",
                sandbox="workspace-write",
                timeout=1,
                codex_bin="codex",
                overwrite=False,
                dry_run=True,
            )

            with contextlib.redirect_stdout(io.StringIO()):
                rc = mmc.run_arm(args)

            self.assertEqual(0, rc)
            self.assertFalse((packet_path.parent / "runs" / "dry_arm").exists())

    def test_score_run_validates_decision_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_project(Path(tmp))
            packet_path = self.freeze(paths, Path(tmp) / "packets")
            run_dir = packet_path.parent / "runs" / "gpt55_xhigh"
            shutil.copytree(packet_path.parent / "workspace", run_dir / "workspace")
            decision_path = run_dir / "workspace" / "derivations" / "reports" / "epoch_008" / "analysis_decision.json"
            proposal = run_dir / "workspace" / "derivations" / "reports" / "epoch_008" / "proposal_01.md"
            self.write(proposal, "# Proposal\n")
            self.write(run_dir / "workspace" / "derivations" / "reports" / "epoch_008" / "summary.md", "summary\n")
            self.write_json(
                decision_path,
                {
                    "route": "IMPLEMENT",
                    "rationale": "enough evidence",
                    "confidence": "medium",
                    "candidate": None,
                    "proposal_paths": ["derivations/reports/epoch_008/proposal_01.md"],
                    "experiment_spec": None,
                    "success_criteria": {},
                    "failure_policy": "NONE",
                    "fallback_route": "CONTINUE_EPOCH",
                },
            )
            run_record = {
                "arm": "gpt55_xhigh",
                "engine": "codex",
                "model": "gpt-5.5",
                "reasoning_effort": "xhigh",
                "input_digest": mmc.load_packet(packet_path)["input"]["input_digest"],
                "returncode": 0,
            }

            score = mmc.score_run(packet_path, run_dir, run_record)

            self.assertEqual([], score["issues"])
            self.assertEqual(1.0, score["objective_score"])
            self.assertEqual("IMPLEMENT", score["decision_summary"]["route"])
            self.assertTrue(score["decision_summary"]["baseline_route_match"])

    def test_score_run_rejects_contaminated_workspace_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_project(Path(tmp))
            packet_path = self.freeze(paths, Path(tmp) / "packets")
            run_dir = packet_path.parent / "runs" / "gpt55_xhigh"
            shutil.copytree(packet_path.parent / "workspace", run_dir / "workspace")
            self.write(
                run_dir / "workspace" / "derivations" / "logs" / "epoch_008" / "batch_extra.jsonl",
                "{}\n",
            )
            run_record = {
                "arm": "gpt55_xhigh",
                "engine": "codex",
                "model": "gpt-5.5",
                "reasoning_effort": "xhigh",
                "input_digest": mmc.load_packet(packet_path)["input"]["input_digest"],
                "returncode": 0,
            }

            score = mmc.score_run(packet_path, run_dir, run_record)

            self.assertFalse(score["objective_checks"]["epoch_logs_exact"])
            self.assertTrue(any(issue["issue"] == "run_epoch_log_listing_mismatch" for issue in score["issues"]))


if __name__ == "__main__":
    unittest.main()
