"""Bugfix workflow: standalone BUG_INVESTIGATE -> IMPLEMENT -> CLOSE.

Runs only the bug investigation and fix path against existing epoch logs.
Does NOT generate new derivations or run the outer analysis loop. Designed
for iterating on bug fixes when logs from a prior GENERATE epoch already
exist on disk.

Starting this workflow with --reset sets the phase to BUG_INVESTIGATE;
without --reset it resumes from the saved _epoch_state.json.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Callable

_DERIVATIONS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _DERIVATIONS not in sys.path:
    sys.path.insert(0, _DERIVATIONS)

from workflow_registry import Workflow, register  # noqa: E402


@register
class BugfixWorkflow(Workflow):
    name = "bugfix"
    description = "Standalone bug investigation and fix: reads existing logs, no generation"

    def phases(self) -> list[str]:
        return ["BUG_INVESTIGATE", "IMPLEMENT", "CLOSE", "DONE"]

    def initial_phase(self) -> str:
        return "BUG_INVESTIGATE"

    def dispatch(self) -> dict[str, Callable[[dict, dict], None]]:
        from autonomous_epoch import (  # noqa: E402
            phase_bug_investigate, phase_implement, phase_close,
        )

        return {
            "BUG_INVESTIGATE": phase_bug_investigate,
            "IMPLEMENT": phase_implement,
            "CLOSE": phase_close,
        }

    def prepare(self, cfg: dict, state: dict, args: Any) -> None:
        # Clear any stale bug_seeds_processed so seeds are re-evaluated against
        # the current logs on a fresh --reset run.
        if args and getattr(args, "reset", False):
            state.pop("bug_seeds_processed", None)
            state.pop("proposals_handled", None)
