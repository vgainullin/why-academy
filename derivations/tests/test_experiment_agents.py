from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import experiment_agents as ea  # noqa: E402


class ExperimentAgentsTests(unittest.TestCase):
    def test_manifest_has_required_gate_groups(self) -> None:
        manifest = ea.load_manifest()

        self.assertIn("prebuild", manifest["groups"])
        self.assertIn("build", manifest["groups"])
        self.assertIn("postbuild", manifest["groups"])
        self.assertEqual(
            ea.expand_roles(manifest, ["prebuild"]),
            ["code_review_gate", "test_gate_design", "integration_design"],
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
        )

        for role_id in ea.expand_roles(manifest, ["all"]):
            prompt, metadata = ea.render_role(manifest, role_id, ctx)
            self.assertNotRegex(prompt, ea.PLACEHOLDER_RE)
            self.assertIn("Do not request permissions or approvals.", prompt)
            self.assertIn("typed tactics reduce fused edges", prompt)
            self.assertIn("/tmp/batch_metrics.json", prompt)
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
            self.assertEqual([r["role_id"] for r in packet["roles"]], [
                "code_review_gate",
                "implementation",
            ])
            for role in packet["roles"]:
                prompt = Path(role["prompt_path"]).read_text()
                self.assertIn("If a needed command would require approval, skip it", prompt)
                self.assertIn("/tmp/worktree", prompt)
                self.assertIn("/tmp/evidence.json", prompt)


if __name__ == "__main__":
    unittest.main()
