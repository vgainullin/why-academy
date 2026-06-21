#!/usr/bin/env python3
"""General workflow registry with auto-discovery.

Each workflow is a Python module in ``derivations/workflows/`` that defines a
``Workflow`` subclass. The registry auto-discovers all such modules at import
time, mirroring how ``verify.py`` auto-discovers validators from
``derivations/validators/``.

A workflow implements a phased state machine: it declares its phases, a
dispatch table mapping phase names to handler functions, and an initial
phase. The registry provides the run loop (signal handling, wall-clock cap,
pause/resume, error capture) so workflows only define phase handlers.

Built-in workflows (auto-discovered):
  epoch   — full GENERATE -> ANALYZE -> BUG_INVESTIGATE -> EXPERIMENT -> IMPLEMENT -> CLOSE
  bugfix  — standalone BUG_INVESTIGATE -> IMPLEMENT -> CLOSE (reads existing logs)

CLI:
  workflow_registry.py list                          — list discovered workflows
  workflow_registry.py run <name> [--queue <file>] [--reset]  — run a workflow
  workflow_registry.py auto-detect                   — detect workflow from config/state
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import signal
import sys
import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DERIVATIONS = Path(__file__).resolve().parent
WORKFLOWS_DIR = DERIVATIONS / "workflows"


def _reexec_with_derivation_python() -> None:
    if os.environ.get("WORKFLOW_REGISTRY_REEXECED") == "1":
        return
    candidates: list[Path] = []
    configured = os.environ.get("DERIVATION_PYTHON")
    if configured:
        candidates.append(Path(configured))
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "derivations" / ".venv" / "bin" / "python")
        candidates.append(parent / ".venv" / "bin" / "python")
    current = Path(sys.executable).resolve()
    for candidate in candidates:
        if candidate.exists() and candidate.resolve() != current:
            os.environ["WORKFLOW_REGISTRY_REEXECED"] = "1"
            os.execv(str(candidate), [str(candidate), *sys.argv])


# ── Workflow protocol ────────────────────────────────────────────────────


class Workflow(ABC):
    """Base class for registered workflows.

    A workflow declares its phases and provides a handler for each. The
    registry's run loop drives the state machine: load state, dispatch to
    the handler for the current phase, persist state, repeat until DONE or
    a pause state.

    Subclasses must set ``name`` and implement ``phases()``,
    ``initial_phase()``, and ``dispatch()``.
    """

    name: str = "base"
    description: str = ""

    @abstractmethod
    def phases(self) -> list[str]:
        """Return the ordered list of phase names for this workflow."""
        ...

    @abstractmethod
    def initial_phase(self) -> str:
        """Return the phase to start at on a fresh run."""
        ...

    @abstractmethod
    def dispatch(self) -> dict[str, Callable[[dict, dict], None]]:
        """Return a mapping of phase name -> handler function.

        Each handler takes (cfg, state) and mutates state in place (setting
        ``state["phase"]`` to the next phase). The registry's run loop
        persists state after each handler call.
        """
        ...

    def terminal_phases(self) -> set[str]:
        """Phases that end the run loop (override for custom pause states)."""
        return {"DONE", "PAUSED_QUOTA", "PAUSED_ERROR", "PAUSED_SIGNAL",
                "PAUSED_WALLCLOCK"}

    def resume_phases(self) -> set[str]:
        """Pause states that should resume from a recorded resume_phase."""
        return {"PAUSED_QUOTA", "PAUSED_ERROR", "PAUSED_SIGNAL", "PAUSED_WALLCLOCK"}

    def prepare(self, cfg: dict, state: dict, args: Any) -> None:
        """Hook called once before the run loop starts. Override for setup."""
        pass


# ── Registry ─────────────────────────────────────────────────────────────


WORKFLOWS: dict[str, type[Workflow]] = {}


def register(workflow_cls: type[Workflow]) -> type[Workflow]:
    """Register a workflow class. Usable as a decorator.

    Stores on the Workflow class itself so registration survives the
    __main__ vs workflow_registry module-name split.
    """
    if not hasattr(Workflow, "_registry"):
        Workflow._registry = {}  # type: ignore
    Workflow._registry[workflow_cls.name] = workflow_cls  # type: ignore
    WORKFLOWS[workflow_cls.name] = workflow_cls
    return workflow_cls


def _get_registry() -> dict[str, type[Workflow]]:
    return getattr(Workflow, "_registry", WORKFLOWS)


def discover_workflows() -> dict[str, type[Workflow]]:
    """Auto-discover workflow modules in derivations/workflows/*.py."""
    if not WORKFLOWS_DIR.exists():
        return _get_registry()

    for py in sorted(WORKFLOWS_DIR.glob("*.py")):
        if py.name.startswith("_"):
            continue
        mod_name = f"workflows.{py.stem}"
        if str(DERIVATIONS) not in sys.path:
            sys.path.insert(0, str(DERIVATIONS))
        try:
            mod = importlib.import_module(f"workflows.{py.stem}")
        except Exception:
            spec = importlib.util.spec_from_file_location(mod_name, py)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)

        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (isinstance(attr, type) and issubclass(attr, Workflow)
                    and attr is not Workflow and attr.name not in _get_registry()):
                register(attr)

    return _get_registry()


def get_workflow(name: str) -> Workflow:
    """Get an instantiated workflow by name. Discovers if needed."""
    reg = _get_registry()
    if not reg:
        discover_workflows()
        reg = _get_registry()
    if name not in reg:
        available = ", ".join(sorted(reg))
        raise ValueError(f"unknown workflow: {name} (available: {available})")
    return reg[name]()


def list_workflows() -> list[dict[str, str]]:
    """Return metadata for all discovered workflows."""
    reg = _get_registry()
    if not reg:
        discover_workflows()
        reg = _get_registry()
    return [
        {"name": w.name, "description": w.description, "phases": "->".join(w().phases())}
        for w in sorted(reg.values(), key=lambda w: w.name)
    ]


# ── Run loop ─────────────────────────────────────────────────────────────


RESUMABLE_PAUSE_STATES = {"PAUSED_QUOTA", "PAUSED_ERROR", "PAUSED_SIGNAL", "PAUSED_WALLCLOCK"}


def _load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text())
    except Exception:
        return {}


def _save_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))


def _resume_from_pause(state: dict, resume_phases: set[str]) -> None:
    if state.get("phase") in resume_phases:
        resume = state.pop("resume_phase", None)
        if resume:
            state["phase"] = resume
        state.pop("error", None)
        state.pop("paused_at", None)


def _write_pause_state(state: dict, pause_phase: str, resume_phase: str | None = None,
                       error: str | None = None) -> None:
    state["phase"] = pause_phase
    if resume_phase:
        state["resume_phase"] = resume_phase
    if error:
        state["error"] = error
    state["paused_at"] = datetime.now(timezone.utc).isoformat()


def run_workflow(workflow: Workflow, cfg: dict, state_path: Path,
                 *, reset: bool = False, args: Any = None,
                 max_wall_s: float = 7200) -> int:
    """Drive a workflow's state machine to completion.

    Handles signal-based pause, wall-clock cap, error capture, and state
    persistence. Returns 0 on success or graceful pause, non-zero on
    unexpected errors.
    """
    if reset and state_path.exists():
        state_path.unlink()

    state = _load_state(state_path)
    if not state:
        state = {"phase": workflow.initial_phase(),
                 "started_at": datetime.now(timezone.utc).isoformat()}

    _resume_from_pause(state, workflow.resume_phases())

    workflow.prepare(cfg, state, args)

    dispatch = workflow.dispatch()
    terminal = workflow.terminal_phases()

    epoch_start_wall = time.time()
    _signal_received = None

    def _signal_handler(signum, frame):
        nonlocal _signal_received
        _signal_received = signum

    prev_term = signal.signal(signal.SIGTERM, _signal_handler)
    prev_int = signal.signal(signal.SIGINT, _signal_handler)

    try:
        while state.get("phase") not in terminal:
            if _signal_received is not None:
                sig_name = signal.Signals(_signal_received).name
                print(f"[runner] received {sig_name}; writing PAUSED_SIGNAL and exiting",
                      file=sys.stderr)
                _write_pause_state(state, "PAUSED_SIGNAL",
                                   resume_phase=state.get("phase", workflow.initial_phase()),
                                   error=f"signal: {sig_name}")
                _save_state(state_path, state)
                return 0

            phase = state.get("phase", workflow.initial_phase())
            handler = dispatch.get(phase)
            if handler is None:
                print(f"[runner] unknown phase {phase!r}; exiting", file=sys.stderr)
                _write_pause_state(state, "PAUSED_ERROR",
                                   resume_phase=state.get("phase", workflow.initial_phase()),
                                   error=f"unknown phase: {phase}")
                _save_state(state_path, state)
                return 2

            print(f"[runner] {workflow.name}: phase={phase}", file=sys.stderr)
            handler(cfg, state)
            _save_state(state_path, state)

            if state.get("phase") in RESUMABLE_PAUSE_STATES:
                break

            if time.time() - epoch_start_wall > max_wall_s:
                print(f"[runner] wall-clock cap ({max_wall_s}s) exceeded; pausing",
                      file=sys.stderr)
                _write_pause_state(state, "PAUSED_WALLCLOCK",
                                   resume_phase=state.get("phase", workflow.initial_phase()))
                _save_state(state_path, state)
                return 0
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[runner] UNEXPECTED ERROR in phase={state.get('phase')}; "
              f"writing PAUSED_ERROR", file=sys.stderr)
        print(tb, file=sys.stderr)
        _write_pause_state(state, "PAUSED_ERROR",
                           resume_phase=state.get("phase", workflow.initial_phase()),
                           error=f"{type(e).__name__}: {e}\n{tb}")
        _save_state(state_path, state)
        return 0
    finally:
        signal.signal(signal.SIGTERM, prev_term)
        signal.signal(signal.SIGINT, prev_int)

    print(f"[runner] phase={state.get('phase')}; exiting 0", file=sys.stderr)
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────


def main() -> int:
    _reexec_with_derivation_python()

    ap = argparse.ArgumentParser(description="General workflow registry")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("run")
    r.add_argument("name", help="workflow name")
    r.add_argument("--queue", default="derivations/targets/cohort_v1.txt")
    r.add_argument("--reset", action="store_true")
    sub.add_parser("auto-detect")

    args = ap.parse_args()

    if args.cmd == "list":
        for w in list_workflows():
            print(f"  {w['name']:12s} {w['phases']}")
            if w["description"]:
                print(f"               {w['description']}")
        return 0

    if args.cmd == "auto-detect":
        from config import load_config
        cfg, _ = load_config()
        # If bug_investigate is enabled and there are existing logs, suggest bugfix.
        bi = cfg.get("runner", {}).get("bug_investigate", {})
        logs_dir = PROJECT_ROOT / "derivations" / "logs"
        has_logs = logs_dir.exists() and any(logs_dir.iterdir())
        if bi.get("enabled") and has_logs:
            print("bugfix")
        else:
            print("epoch")
        return 0

    if args.cmd == "run":
        from config import load_config
        cfg, _ = load_config()
        state_path = PROJECT_ROOT / cfg.get("runner", {}).get(
            "state_file", "derivations/_epoch_state.json")

        workflow = get_workflow(args.name)
        max_wall = float(cfg.get("runner", {}).get("epoch", {}).get(
            "max_wall_clock_s_per_epoch", 7200))

        return run_workflow(workflow, cfg, state_path,
                            reset=args.reset, args=args, max_wall_s=max_wall)

    return 2


if __name__ == "__main__":
    # When run as a script, re-import ourselves as a module so that workflow
    # files (which do `from workflow_registry import ...`) see the same module
    # object and registry. Running directly as __main__ would create a second
    # copy of Workflow/register that doesn't share state with the imported module.
    import workflow_registry as _self
    _self._reexec_with_derivation_python()
    raise SystemExit(_self.main())
