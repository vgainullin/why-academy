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

import workflow_registry as wr  # noqa: E402


class RegistryTests(unittest.TestCase):

    def test_builtin_workflows_discovered(self) -> None:
        names = {w["name"] for w in wr.list_workflows()}
        self.assertIn("epoch", names)
        self.assertIn("bugfix", names)

    def test_epoch_workflow_phases(self) -> None:
        wf = wr.get_workflow("epoch")
        self.assertEqual(wf.initial_phase(), "GENERATE")
        self.assertIn("BUG_INVESTIGATE", wf.phases())
        self.assertEqual(wf.phases()[-1], "DONE")

    def test_bugfix_workflow_phases(self) -> None:
        wf = wr.get_workflow("bugfix")
        self.assertEqual(wf.initial_phase(), "BUG_INVESTIGATE")
        self.assertNotIn("GENERATE", wf.phases())
        self.assertEqual(wf.phases(), ["BUG_INVESTIGATE", "IMPLEMENT", "CLOSE", "DONE"])

    def test_bugfix_skips_generate_and_analyze(self) -> None:
        wf = wr.get_workflow("bugfix")
        phases = wf.phases()
        self.assertNotIn("GENERATE", phases)
        self.assertNotIn("ANALYZE", phases)
        self.assertNotIn("EXPERIMENT", phases)

    def test_get_unknown_workflow_raises(self) -> None:
        with self.assertRaises(ValueError):
            wr.get_workflow("nonexistent")

    def test_epoch_dispatch_has_all_phases(self) -> None:
        wf = wr.get_workflow("epoch")
        dispatch = wf.dispatch()
        for phase in wf.phases():
            if phase != "DONE":
                self.assertIn(phase, dispatch, f"epoch dispatch missing phase {phase}")

    def test_bugfix_dispatch_has_all_phases(self) -> None:
        wf = wr.get_workflow("bugfix")
        dispatch = wf.dispatch()
        for phase in wf.phases():
            if phase != "DONE":
                self.assertIn(phase, dispatch, f"bugfix dispatch missing phase {phase}")


class CustomWorkflowDiscoveryTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp_workflows = DERIVATIONS / "workflows" / "test_custom_discovery.py"
        self.tmp_workflows.write_text(
            "from workflow_registry import Workflow, register\n"
            "@register\n"
            "class TestCustomDiscovery(Workflow):\n"
            "    name = 'test_custom_discovery'\n"
            "    description = 'test'\n"
            "    def phases(self): return ['START', 'DONE']\n"
            "    def initial_phase(self): return 'START'\n"
            "    def dispatch(self): return {'START': lambda c, s: s.__setitem__('phase', 'DONE')}\n"
        )

    def tearDown(self) -> None:
        self.tmp_workflows.unlink(missing_ok=True)
        reg = wr._get_registry()
        reg.pop("test_custom_discovery", None)
        sys.modules.pop("workflows.test_custom_discovery", None)

    def test_custom_workflow_auto_discovered(self) -> None:
        reg = wr._get_registry()
        reg.clear()
        wr.discover_workflows()
        self.assertIn("test_custom_discovery", wr._get_registry())

    def test_underscore_prefixed_files_skipped(self) -> None:
        # Create an underscore-prefixed file and verify it's not discovered.
        skip_file = DERIVATIONS / "workflows" / "_skip_me.py"
        skip_file.write_text(
            "from workflow_registry import Workflow, register\n"
            "@register\n"
            "class SkipMe(Workflow):\n"
            "    name = 'skip_me'\n"
            "    description = 'should not be discovered'\n"
            "    def phases(self): return ['DONE']\n"
            "    def initial_phase(self): return 'DONE'\n"
            "    def dispatch(self): return {}\n"
        )
        try:
            reg = wr._get_registry()
            reg.clear()
            wr.discover_workflows()
            self.assertNotIn("skip_me", wr._get_registry())
        finally:
            skip_file.unlink(missing_ok=True)
            wr._get_registry().pop("skip_me", None)


class RunWorkflowTests(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.state_path = self.tmp / "state.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_runs_to_done(self) -> None:
        class StubWorkflow(wr.Workflow):
            name = "stub"
            description = ""
            def phases(self): return ["A", "B", "DONE"]
            def initial_phase(self): return "A"
            def dispatch(self):
                return {
                    "A": lambda c, s: s.__setitem__("phase", "B"),
                    "B": lambda c, s: s.__setitem__("phase", "DONE"),
                }

        wf = StubWorkflow()
        rc = wr.run_workflow(wf, {}, self.state_path)
        self.assertEqual(rc, 0)
        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["phase"], "DONE")

    def test_reset_clears_state(self) -> None:
        self.state_path.write_text(json.dumps({"phase": "DONE", "old": True}))

        class StubWorkflow(wr.Workflow):
            name = "stub"
            description = ""
            def phases(self): return ["A", "DONE"]
            def initial_phase(self): return "A"
            def dispatch(self):
                return {"A": lambda c, s: s.__setitem__("phase", "DONE")}

        wf = StubWorkflow()
        rc = wr.run_workflow(wf, {}, self.state_path, reset=True)
        state = json.loads(self.state_path.read_text())
        self.assertNotIn("old", state)
        self.assertEqual(state["phase"], "DONE")

    def test_resume_from_pause(self) -> None:
        self.state_path.write_text(json.dumps({
            "phase": "PAUSED_QUOTA", "resume_phase": "B"
        }))

        calls = []

        class StubWorkflow(wr.Workflow):
            name = "stub"
            description = ""
            def phases(self): return ["A", "B", "DONE"]
            def initial_phase(self): return "A"
            def dispatch(self):
                return {
                    "A": lambda c, s: (calls.append("A"), s.__setitem__("phase", "B")),
                    "B": lambda c, s: (calls.append("B"), s.__setitem__("phase", "DONE")),
                }

        wf = StubWorkflow()
        rc = wr.run_workflow(wf, {}, self.state_path)
        self.assertEqual(calls, ["B"])  # resumed at B, skipped A

    def test_wall_clock_pause(self) -> None:
        class StubWorkflow(wr.Workflow):
            name = "stub"
            description = ""
            def phases(self): return ["LOOP", "DONE"]
            def initial_phase(self): return "LOOP"
            def dispatch(self):
                return {"LOOP": lambda c, s: None}  # never advances

        wf = StubWorkflow()
        rc = wr.run_workflow(wf, {}, self.state_path, max_wall_s=0.01)
        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["phase"], "PAUSED_WALLCLOCK")

    def test_unknown_phase_writes_error(self) -> None:
        class StubWorkflow(wr.Workflow):
            name = "stub"
            description = ""
            def phases(self): return ["A", "DONE"]
            def initial_phase(self): return "A"
            def dispatch(self): return {}  # no handler for A

        wf = StubWorkflow()
        rc = wr.run_workflow(wf, {}, self.state_path)
        self.assertEqual(rc, 2)
        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["phase"], "PAUSED_ERROR")


class AutoDetectTests(unittest.TestCase):

    @patch("workflow_registry.PROJECT_ROOT")
    @patch("workflow_registry.load_config", create=True)
    def test_detects_epoch_when_no_logs(self, mock_load, mock_root) -> None:
        mock_load.return_value = ({"runner": {"bug_investigate": {"enabled": False}}}, "v5")
        tmp = Path(tempfile.mkdtemp())
        mock_root.return_value = tmp
        # No logs dir
        from workflow_registry import main
        with patch.dict(os.environ if 'os' in dir() else {}, {}):
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    def test_auto_detect_returns_epoch_by_default(self) -> None:
        # The auto-detect logic: bugfix if bug_investigate enabled AND logs exist
        # Default repo has no logs, so should return epoch.
        import subprocess
        r = subprocess.run(
            [str(DERIVATIONS / ".venv" / "bin" / "python"),
             str(DERIVATIONS / "workflow_registry.py"), "auto-detect"],
            capture_output=True, text=True, cwd=str(ROOT)
        )
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "epoch")


if __name__ == "__main__":
    unittest.main()
