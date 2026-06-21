"""Epoch workflow: full GENERATE -> ANALYZE -> BUG_INVESTIGATE -> EXPERIMENT -> IMPLEMENT -> CLOSE.

This wraps the existing autonomous_epoch.py phase functions into a registered
workflow. The phase handlers are the same functions that the old if-elif
dispatch in main() called; they mutate state["phase"] to advance.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import sys
import os

# Ensure derivations/ is importable when this module is loaded by the registry.
_DERIVATIONS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _DERIVATIONS not in sys.path:
    sys.path.insert(0, _DERIVATIONS)

from workflow_registry import Workflow, register  # noqa: E402


@register
class EpochWorkflow(Workflow):
    name = "epoch"
    description = "Full autonomous epoch: generate, analyze, bug-investigate, experiment, implement, close"

    def phases(self) -> list[str]:
        return ["GENERATE", "ANALYZE", "BUG_INVESTIGATE", "EXPERIMENT",
                "IMPLEMENT", "CLOSE", "DONE"]

    def initial_phase(self) -> str:
        return "GENERATE"

    def dispatch(self) -> dict[str, Callable[[dict, dict], None]]:
        from autonomous_epoch import (  # noqa: E402
            phase_generate, phase_analyze, phase_bug_investigate,
            phase_experiment, phase_implement, phase_close,
        )

        def _generate(cfg, state):
            queue = state.get("_queue", "derivations/targets/cohort_v1.txt")
            phase_generate(cfg, state, Path(queue))

        return {
            "GENERATE": _generate,
            "ANALYZE": phase_analyze,
            "BUG_INVESTIGATE": phase_bug_investigate,
            "EXPERIMENT": lambda cfg, state: phase_experiment(cfg, state, Path(state.get("_queue", "derivations/targets/cohort_v1.txt"))),
            "IMPLEMENT": phase_implement,
            "CLOSE": phase_close,
        }

    def prepare(self, cfg: dict, state: dict, args: Any) -> None:
        if args and hasattr(args, "queue"):
            state["_queue"] = args.queue
