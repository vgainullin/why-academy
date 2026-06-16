from __future__ import annotations

import json
import argparse
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import experiment_agents as ea  # noqa: E402


class ExperimentAgentsTests(unittest.TestCase):
    def write_json(self, path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def make_ab_batch(self, root: Path, name: str, *, treatment: bool = False) -> Path:
        batch = root / name
        self.write_json(batch / "checkpoint.json", {
            "batch_id": name,
            "experiment_id": "exp_ab",
            "inner_mode": "rule_executor" if treatment else "json",
        })
        self.write_json(batch / "batch_metrics.json", {
            "batch_id": name,
            "experiment_id": "exp_ab",
            "n_targets": 1,
            "n_accepted": 0,
        })
        target = batch / "targets" / "target_000"
        self.write_json(target / "target.json", {"target_index": 0, "target": "solve x"})
        self.write_json(target / "target_metrics.json", {
            "target_index": 0,
            "accepted": False,
            "first_try_pass": False,
            "n_iterations": 1,
            "failure_reason": "verify_fail_iter_0",
        })
        (target / "FAILED.txt").write_text("verify_fail_iter_0")
        iter0 = target / "iter_00"
        iter0.mkdir(parents=True)
        (iter0 / "status.txt").write_text("verify_fail")
        self.write_json(iter0 / "problem.verifier.json", {"edge_summary": {"FAIL": 1}})
        self.write_json(iter0 / "failure_diagnosis.json", {"failure_class": "rule_fail"})
        if treatment:
            self.write_json(iter0 / "rule_executor_error.json", {
                "failure_class": "substitution_structural_fail",
            })
            self.write_json(iter0 / "problem.substitution_check.json", {"status": "FAIL"})
        return batch

    def test_manifest_has_required_gate_groups(self) -> None:
        manifest = ea.load_manifest()

        self.assertIn("prebuild", manifest["groups"])
        self.assertIn("build", manifest["groups"])
        self.assertIn("postbuild", manifest["groups"])
        self.assertIn("reporting", manifest["groups"])
        self.assertEqual(
            ea.expand_roles(manifest, ["prebuild"]),
            ["code_review_gate", "test_gate_design", "integration_design"],
        )
        self.assertEqual(
            ea.expand_roles(manifest, ["reporting"]),
            ["report_writer", "report_review_gate"],
        )

    def test_all_role_templates_render_without_unresolved_placeholders(self) -> None:
        manifest = ea.load_manifest()
        ctx = ea.RenderContext(
            experiment_id="tactic_inner_mode",
            hypothesis="typed tactics reduce fused edges",
            repo_root=ROOT,
            worktree="/tmp/worktree",
            prototype_worktree="/tmp/prototype",
            evidence_paths=["/tmp/batch_metrics.json", "/tmp/introspection.json"],
            report_path="derivations/experiments/test_report.md",
        )

        for role_id in ea.expand_roles(manifest, ["all"]):
            prompt, metadata = ea.render_role(manifest, role_id, ctx)
            self.assertNotRegex(prompt, ea.PLACEHOLDER_RE)
            self.assertIn("Do not request permissions or approvals.", prompt)
            self.assertIn("typed tactics reduce fused edges", prompt)
            self.assertIn("/tmp/batch_metrics.json", prompt)
            if role_id in {"report_writer", "report_review_gate"}:
                self.assertIn("derivations/experiments/test_report.md", prompt)
            self.assertEqual(role_id, metadata["role_id"])

    def test_render_packet_writes_self_contained_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ea.RenderContext(
                experiment_id="exp1",
                hypothesis="h",
                repo_root=ROOT,
                worktree="/tmp/worktree",
                prototype_worktree="",
                evidence_paths=["/tmp/evidence.json"],
                report_path="derivations/experiments/exp1.md",
            )
            packet = ea.write_packet(
                ctx,
                ["code_review_gate", "implementation"],
                Path(tmp),
            )

            packet_path = Path(tmp) / "packet.json"
            self.assertTrue(packet_path.exists())
            loaded = json.loads(packet_path.read_text())
            self.assertEqual(loaded["schema_version"], "experiment_agent_packet.v1")
            self.assertEqual(loaded["report_path"], "derivations/experiments/exp1.md")
            self.assertIn("evidence_sha256", loaded)
            self.assertEqual([r["role_id"] for r in packet["roles"]], [
                "code_review_gate",
                "implementation",
            ])
            for role in packet["roles"]:
                prompt = Path(role["prompt_path"]).read_text()
                self.assertEqual(ea.sha256_text(prompt), role["prompt_sha256"])
                self.assertIn("If a needed command would require approval, skip it", prompt)
                self.assertIn("/tmp/worktree", prompt)
                self.assertIn("/tmp/evidence.json", prompt)

    def test_verify_packet_detects_prompt_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = ea.RenderContext(
                experiment_id="exp1",
                hypothesis="h",
                repo_root=ROOT,
                worktree="/tmp/worktree",
                prototype_worktree="",
                evidence_paths=["/tmp/evidence.json"],
            )
            packet = ea.write_packet(ctx, ["ab_analysis"], root)
            packet_path = root / "packet.json"

            _loaded, issues = ea.verify_packet(packet_path)
            self.assertEqual([], issues)

            prompt_path = Path(packet["roles"][0]["prompt_path"])
            prompt_path.write_text(prompt_path.read_text() + "\nextra\n")
            _loaded, issues = ea.verify_packet(packet_path)

            self.assertEqual("prompt_sha256_mismatch", issues[0]["issue"])

    def test_ab_analysis_evidence_collects_comparison_and_failure_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = self.make_ab_batch(root, "control")
            treatment = self.make_ab_batch(root, "treatment", treatment=True)
            self.write_json(treatment / "ab_comparison.json", {
                "experiment_id": "exp_ab",
                "paired": {"n_pairs": 1},
            })

            evidence, issues = ea.collect_ab_analysis_evidence(control, treatment)

            self.assertEqual([], issues)
            joined = "\n".join(evidence)
            self.assertIn("ab_comparison.json", joined)
            self.assertIn("control", joined)
            self.assertIn("treatment", joined)
            self.assertIn("problem.verifier.json", joined)
            self.assertIn("rule_executor_error.json", joined)
            self.assertIn("problem.substitution_check.json", joined)

    def test_ab_analysis_requires_comparison_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = self.make_ab_batch(root, "control")
            treatment = self.make_ab_batch(root, "treatment", treatment=True)

            _evidence, issues = ea.collect_ab_analysis_evidence(control, treatment)

            self.assertTrue(any("ab_comparison.json" in issue for issue in issues))

    def test_render_ab_analysis_packet_uses_discovered_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            control = self.make_ab_batch(root, "control")
            treatment = self.make_ab_batch(root, "treatment", treatment=True)
            self.write_json(treatment / "ab_comparison.json", {
                "experiment_id": "exp_ab",
                "paired": {"n_pairs": 1},
            })
            out_dir = root / "packet"

            packet, issues = ea.write_ab_analysis_packet(
                control_dir=control,
                treatment_dir=treatment,
                experiment_id=None,
                hypothesis="executor reduces fused edges",
                worktree="/tmp/worktree",
                prototype_worktree="",
                report_path="",
                out_dir=out_dir,
            )

            self.assertEqual([], issues)
            self.assertIsNotNone(packet)
            loaded = json.loads((out_dir / "packet.json").read_text())
            self.assertEqual(["ab_analysis"], [r["role_id"] for r in loaded["roles"]])
            self.assertEqual("exp_ab", loaded["experiment_id"])
            self.assertGreater(loaded["evidence_paths"].index(str(treatment / "ab_comparison.json")), -1)
            prompt = (out_dir / "prompts" / "ab_analysis.md").read_text()
            self.assertIn("executor reduces fused edges", prompt)
            self.assertIn("ab_comparison.json", prompt)

    def test_next_step_packet_uses_analysis_and_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            analysis = root / "ab_analysis_result.txt"
            comparison = root / "ab_comparison.json"
            analysis.write_text("step_in_right_direction: inconclusive\n")
            self.write_json(comparison, {"paired": {"n_pairs": 2}})

            packet, issues = ea.write_next_step_packet(
                analysis_paths=[str(analysis)],
                extra_evidence=[str(comparison)],
                experiment_id="exp_next",
                hypothesis="derive next falsifiable blocker",
                worktree="/tmp/worktree",
                prototype_worktree="",
                report_path="",
                out_dir=root / "packet",
            )

            self.assertEqual([], issues)
            self.assertIsNotNone(packet)
            loaded = json.loads((root / "packet" / "packet.json").read_text())
            self.assertEqual(["next_step_derivation"], [r["role_id"] for r in loaded["roles"]])
            self.assertIn(str(analysis), loaded["evidence_paths"])
            prompt = (root / "packet" / "prompts" / "next_step_derivation.md").read_text()
            self.assertIn("derive next falsifiable blocker", prompt)
            self.assertIn("step", prompt.lower())
            self.assertEqual(
                ea.sha256_text(prompt),
                loaded["roles"][0]["prompt_sha256"],
            )
            _verified, verify_issues = ea.verify_packet(root / "packet" / "packet.json")
            self.assertEqual([], verify_issues)

    def test_parse_next_step_decision_json_block(self) -> None:
        text = """Analysis text.

```json
{
  "decision_tags": ["graph_normalization", "edge_preservation"],
  "selected_next_hypothesis": "normalization is dropping executor steps",
  "minimum_experiment_design": "compare raw executor graphs to normalized graphs",
  "required_artifacts_and_agents": ["pilot_runner"],
  "success_criteria": ["normalized graph preserves one operation per edge"],
  "failure_criteria": ["normalized graph still fuses steps"],
  "next_step_ready": "yes"
}
```
"""

        decision = ea.parse_next_step_decision(text)

        self.assertEqual("ok", decision["parse_status"])
        self.assertEqual("yes", decision["next_step_ready"])
        self.assertIn("normalization", decision["selected_next_hypothesis"])
        self.assertIn("graph_normalization", decision["decision_tags"])

    def test_compare_next_step_outputs_accepts_similar_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "run_01.txt"
            second = root / "run_02.txt"
            first.write_text("""```json
{
  "decision_tags": ["graph_normalization", "edge_preservation", "production_gate_equivalence"],
  "selected_next_hypothesis": "graph normalization is dropping rule executor steps",
  "minimum_experiment_design": "compare raw executor output with normalized graph output on the same failing targets",
  "required_artifacts_and_agents": ["pilot_runner"],
  "success_criteria": ["raw and normalized graphs preserve each executor step"],
  "failure_criteria": ["normalization still fuses or drops a step"],
  "next_step_ready": "yes"
}
```""")
            second.write_text("""```json
{
  "decision_tags": ["graph_normalization", "edge_preservation", "production_gate_equivalence"],
  "selected_next_hypothesis": "graph normalization is dropping rule executor steps",
  "minimum_experiment_design": "compare raw executor output with normalized graph output on the same failing targets",
  "required_artifacts_and_agents": ["pilot_runner", "ab_analysis"],
  "success_criteria": ["normalized graphs keep each executor step"],
  "failure_criteria": ["a normalized graph fuses or drops a step"],
  "next_step_ready": "yes"
}
```""")

            report = ea.compare_next_step_outputs([first, second])

            self.assertTrue(report["decision_reproducible"])
            self.assertEqual([], report["issues"])

    def test_compare_next_step_outputs_canonicalizes_decision_tag_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "run_01.txt"
            second = root / "run_02.txt"
            first.write_text("""```json
{
  "decision_tags": ["normalization_boundary_blocker", "production_gate_coverage", "paired_ab_required"],
  "selected_next_hypothesis": "Normalization boundary loss blocks the rule executor pipeline",
  "minimum_experiment_design": "Run a paired replay with equivalent production gates",
  "required_artifacts_and_agents": ["test_agent"],
  "success_criteria": ["production gates match"],
  "failure_criteria": ["normalization still fails"],
  "next_step_ready": "yes"
}
```""")
            second.write_text("""```json
{
  "decision_tags": ["normalization_blocker", "edge_boundary", "gate_equivalence_required", "frozen_replay"],
  "selected_next_hypothesis": "Graph normalization blocks the same rule executor pipeline",
  "minimum_experiment_design": "Run the frozen replay through the same gates",
  "required_artifacts_and_agents": ["test_agent"],
  "success_criteria": ["production gates match"],
  "failure_criteria": ["normalization still fails"],
  "next_step_ready": "yes"
}
```""")

            report = ea.compare_next_step_outputs([first, second])

            self.assertTrue(report["decision_reproducible"])
            self.assertEqual([], report["issues"])

    def test_compare_next_step_outputs_rejects_divergent_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "run_01.txt"
            second = root / "run_02.txt"
            first.write_text("""```json
{
  "decision_tags": ["graph_normalization", "edge_preservation", "production_gate_equivalence"],
  "selected_next_hypothesis": "graph normalization is dropping rule executor steps",
  "minimum_experiment_design": "compare raw executor output with normalized graph output on the same failing targets",
  "required_artifacts_and_agents": ["pilot_runner"],
  "success_criteria": ["normalized graph preserves steps"],
  "failure_criteria": ["normalized graph fuses steps"],
  "next_step_ready": "yes"
}
```""")
            second.write_text("""```json
{
  "decision_tags": ["larger_workload"],
  "selected_next_hypothesis": "run a much larger derivation workload before changing anything",
  "minimum_experiment_design": "execute fifty fresh derivation targets and inspect aggregate acceptance",
  "required_artifacts_and_agents": ["pilot_runner"],
  "success_criteria": ["acceptance improves"],
  "failure_criteria": ["acceptance does not improve"],
  "next_step_ready": "yes"
}
```""")

            report = ea.compare_next_step_outputs([first, second])

            self.assertFalse(report["decision_reproducible"])
            self.assertTrue(any(
                issue["issue"] == "decision_tags_diverged"
                for issue in report["issues"]
            ))

    def test_run_role_dry_run_builds_codex_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = ea.RenderContext(
                experiment_id="exp1",
                hypothesis="h",
                repo_root=ROOT,
                worktree="/tmp/worktree",
                prototype_worktree="",
                evidence_paths=["/tmp/evidence.json"],
            )
            packet = ea.write_packet(ctx, ["ab_analysis"], root)
            args = argparse.Namespace(
                worktree=None,
                sandbox="read-only",
                model="gpt-5.5",
                reasoning_effort="xhigh",
                ephemeral=True,
                codex_bin="codex",
            )

            command = ea.codex_run_command(
                args,
                packet,
                packet["roles"][0],
                root / "ab_analysis_result.txt",
            )

            self.assertEqual(command[:4], ["codex", "exec", "-C", "/tmp/worktree"])
            self.assertIn("--sandbox", command)
            self.assertIn("read-only", command)
            self.assertIn("--model", command)
            self.assertIn("gpt-5.5", command)
            self.assertIn("model_reasoning_effort=\"xhigh\"", command)
            self.assertEqual("-", command[-1])

    def test_reporting_prompts_enforce_report_only_workflow(self) -> None:
        manifest = ea.load_manifest()
        ctx = ea.RenderContext(
            experiment_id="reporting",
            hypothesis="reports are agent-generated and reviewed",
            repo_root=ROOT,
            worktree="/tmp/worktree",
            prototype_worktree="",
            evidence_paths=["/tmp/comparison.json", "/tmp/ab_output.json"],
            report_path="derivations/experiments/reporting.md",
        )

        writer, _ = ea.render_role(manifest, "report_writer", ctx)
        reviewer, _ = ea.render_role(manifest, "report_review_gate", ctx)

        self.assertIn("Edit only `derivations/experiments/reporting.md`", writer)
        self.assertIn("Every factual claim must cite an artifact path", writer)
        self.assertIn("Prior report-review artifacts are revision feedback", writer)
        self.assertIn("Do not edit files.", reviewer)
        self.assertIn("unsupported claims", reviewer)
        self.assertIn("This run is the current review gate", reviewer)
        self.assertIn("report_supported: yes|no", reviewer)


if __name__ == "__main__":
    unittest.main()
