#!/usr/bin/env python3
"""Convert a verified derivation graph into a canvas-derive lesson block.

Input: derivations/problems/<id>.json (the format produced by the inner loop).
Output: a canvas-derive block JSON consumable by renderCanvasDerive in app.js.
  - starting_equation:   LaTeX of root_node
  - target_equation:     LaTeX of goal_node
  - valid_forms:         LaTeX of every node in the graph (dedup, root first)
  - vars:                LaTeX of free symbols across all nodes
  - title / prompt:      auto-generated defaults; intended to be edited by hand

Use --lesson to wrap the block in a minimal lesson stub instead of emitting just the block.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import sympy as _sp
from sympy import Eq, Limit, latex
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from sympy_eval import parse_srepr  # noqa: E402


def parse(s: str):
    return parse_srepr(s)


def _two_side_limits(expr):
    """sympy's default Limit direction is '+', which renders as `\\to 0^+` (one-sided).
    Students write two-sided `\\to 0`. Rewrite all Limit nodes to use direction '+-'
    purely for display; this is a printer-level concern, not a math change for a
    sympy expression that's already truth-checked elsewhere."""
    return expr.replace(
        lambda e: isinstance(e, Limit),
        lambda e: Limit(e.args[0], e.args[1], e.args[2], '+-'),
    )


def eq_to_latex(expr) -> str:
    """LaTeX for an Eq: 'lhs = rhs' (canvas-derive matches against '='-equations)."""
    expr = _two_side_limits(expr)
    if isinstance(expr, Eq):
        return f"{latex(expr.lhs)} = {latex(expr.rhs)}"
    return latex(expr)


def collect_vars(exprs) -> list[str]:
    """All Symbol atoms with valid-identifier names. Includes bound variables
    (limits, integrals, sums) because students write them on the canvas.
    Excludes internal sympy markers like Symbol('+') (limit-direction sentinel)."""
    syms = set()
    for e in exprs:
        syms |= e.atoms(_sp.Symbol)
    syms = {s for s in syms if s.name and s.name[0].isalpha()}
    return sorted({latex(s) for s in syms})


def make_block(problem_path: Path, block_id: str | None = None) -> dict:
    problem = json.loads(problem_path.read_text())
    pid = problem["id"]
    parsed_by_id = {n["id"]: parse(n["sympy_srepr"]) for n in problem["nodes"]}
    root = parsed_by_id[problem["root_node"]]
    goal = parsed_by_id[problem["goal_node"]]

    seen: set = set()
    valid_forms: list[str] = []
    for n in problem["nodes"]:
        s = eq_to_latex(parsed_by_id[n["id"]])
        if s not in seen:
            valid_forms.append(s)
            seen.add(s)

    return {
        "id": block_id or f"DERIVE-{pid.upper().replace('_', '-')}",
        "type": "canvas-derive",
        "title": f"Derive: {pid.replace('_', ' ')}",
        "prompt": (
            "Work the derivation on the canvas. Each line you write is OCR'd and "
            "matched against the chain of valid forms. Green dot = on the path; "
            "gray = off-path (wandering is fine). Finish when one of your lines "
            "reaches the target."
        ),
        "starting_equation": eq_to_latex(root),
        "target_equation": eq_to_latex(goal),
        "vars": collect_vars(parsed_by_id.values()),
        "valid_forms": valid_forms,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("problem", help="path to derivations/problems/<id>.json")
    ap.add_argument("--out", help="output path (default: <problem>.canvas.json)")
    ap.add_argument("--lesson", action="store_true",
                    help="wrap as a full lesson stub instead of a bare block")
    args = ap.parse_args()

    problem_path = Path(args.problem)
    block = make_block(problem_path)

    if args.lesson:
        pid = json.loads(problem_path.read_text())["id"]
        out_obj = {
            "lesson_id": f"L-DERIVE-{pid.upper().replace('_', '-')}",
            "title": block["title"],
            "description": f"Auto-generated derivation lesson for {pid}.",
            "prerequisites": [],
            "blocks": [block],
        }
    else:
        out_obj = block

    out_path = Path(args.out) if args.out else problem_path.with_suffix(".canvas.json")
    out_path.write_text(json.dumps(out_obj, indent=2))
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
