#!/usr/bin/env python3
"""Deterministic canvas-derive integration check.

The browser's canvas-derive matches student handwriting against valid_forms by:
  student_latex  -> canonicalize -> parse_latex -> expr_S
  valid_form_i   -> canonicalize -> parse_latex -> expr_V
  match iff _eq(expr_S, expr_V)  (sign-symmetric simplify-the-difference)

So the question canvas_check actually has to answer per-graph is:
  (a) Can every node's rendered LaTeX be parse_latex'd at all?
  (b) Do any two distinct nodes parse_latex to EQUIVALENT expressions?
      Those would silently collapse on canvas (same valid_form twice), which
      is almost always a sign of sympy auto-simplification eating an intended
      pedagogical step (e.g. 2(x+3) -> 2x+6 during srepr eval).

We deliberately do NOT compare each node's srepr-eval'd expression against
its parse_latex round-trip: sympy.latex / parse_latex aren't inverse for
accented symbols (Symbol('xddot') -> '\\ddot{x}' -> Mul(Symbol('ddot'), Symbol('x'))),
and the asymmetry is harmless because BOTH the valid_form AND student OCR
pass through the same parse_latex, so they parse identically.

Writes <problem>.canvas_check.json. Exits 0 iff all nodes parse cleanly and
no two parse to equivalent expressions.
"""
from __future__ import annotations
import argparse
import json
import sys
import warnings
from pathlib import Path

import sympy as _sp
from sympy import Eq, Symbol, simplify
from sympy.parsing.latex import parse_latex


def _strip_assumptions(expr):
    """Replace every Symbol with an assumption-free Symbol of the same name.

    Necessary because verify.py / to_canvas.py pre-declare symbols as real, while
    parse_latex creates assumption-free symbols. simplify() treats two Symbols
    with the same name but different assumption signatures as distinct, so
    simplify(k_real / m_real  -  k / m) does NOT cancel to 0. The browser
    doesn't hit this because both valid_forms and student OCR pass through
    parse_latex (both assumption-free); the asymmetry is a canvas_check
    artifact, not a canvas-runtime concern.
    """
    return expr.xreplace({s: Symbol(s.name) for s in expr.atoms(Symbol)})

warnings.filterwarnings("ignore", message=".*antlr4.*")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from to_canvas import parse as parse_srepr, eq_to_latex  # noqa: E402

CHECK_VERSION = "0.1"


def _eq(a, b) -> bool:
    """Predicate from lib/shared-core.js _eq(), with assumption stripping (see
    _strip_assumptions). Sign-symmetric for Eq nodes."""
    a = _strip_assumptions(a)
    b = _strip_assumptions(b)
    if isinstance(a, Eq) and isinstance(b, Eq):
        d1 = simplify((a.lhs - a.rhs) - (b.lhs - b.rhs))
        d2 = simplify((a.lhs - a.rhs) + (b.lhs - b.rhs))
        return d1 == 0 or d2 == 0
    if isinstance(a, Eq) or isinstance(b, Eq):
        return False
    return simplify(a - b) == 0


def check_node(srepr_str: str):
    """(status, rendered_latex, parsed_back, reason).

    status: OK | PARSE_ERROR_IN | RENDER_ERROR | PARSE_ERROR_OUT
    parsed_back is the parse_latex result (the expression the browser will see)
    or None on any failure.
    """
    try:
        original = parse_srepr(srepr_str)
    except Exception as e:
        return ("PARSE_ERROR_IN", "", None, f"could not eval srepr: {type(e).__name__}: {e}")
    try:
        rendered = eq_to_latex(original)
    except Exception as e:
        return ("RENDER_ERROR", "", None, f"sympy.latex raised: {type(e).__name__}: {e}")
    try:
        parsed_back = parse_latex(rendered)
    except Exception as e:
        return ("PARSE_ERROR_OUT", rendered, None,
                f"parse_latex(rendered) raised: {type(e).__name__}: {e}")
    return ("OK", rendered, parsed_back, "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("problem", help="path to a derivation problem JSON")
    args = ap.parse_args()

    problem_path = Path(args.problem)
    problem = json.loads(problem_path.read_text())
    pid = problem["id"]

    node_results = []
    seen_rendered: dict = {}  # rendered LaTeX -> first node id that produced it
    duplicates: list = []
    for node in problem["nodes"]:
        status, rendered, _parsed_back, reason = check_node(node["sympy_srepr"])
        if status == "OK":
            # Duplicates here means: two distinct srepr inputs render to
            # bit-identical LaTeX. That's how sympy auto-simplification surfaces
            # (e.g. Mul(2, Add(x,3)) and Add(Mul(2,x), 6) both -> "2 x + 6").
            # Algebraically-equivalent-but-different LaTeX (e.g. "x + 2 = 5"
            # vs "x = 3") is NOT a duplicate -- those are real derivation steps.
            if rendered in seen_rendered:
                duplicates.append({
                    "first": seen_rendered[rendered], "second": node["id"],
                    "latex": rendered,
                })
            else:
                seen_rendered[rendered] = node["id"]
        node_results.append({
            "id": node["id"],
            "status": status,
            "rendered_latex": rendered,
            "reason": reason,
        })

    summary = {"OK": 0, "PARSE_ERROR_IN": 0, "RENDER_ERROR": 0, "PARSE_ERROR_OUT": 0}
    for r in node_results:
        summary[r["status"]] += 1

    record = {
        "problem_id": pid,
        "check_version": CHECK_VERSION,
        "n_nodes": len(node_results),
        "summary": summary,
        "n_duplicates": len(duplicates),
        "duplicates": duplicates,
        "nodes": node_results,
    }
    out_path = problem_path.with_name(problem_path.stem + ".canvas_check.json")
    out_path.write_text(json.dumps(record, indent=2))

    failing = (summary["PARSE_ERROR_IN"] + summary["RENDER_ERROR"] + summary["PARSE_ERROR_OUT"]) > 0
    ok = not failing and len(duplicates) == 0

    print(f"CANVAS CHECK: {pid}")
    print(f"  NODES:      {len(node_results)}")
    print(f"  OK:         {summary['OK']}")
    print(f"  RENDER_ERR: {summary['RENDER_ERROR']}")
    print(f"  PARSE_OUT:  {summary['PARSE_ERROR_OUT']}")
    print(f"  PARSE_IN:   {summary['PARSE_ERROR_IN']}")
    print(f"  DUPLICATES: {len(duplicates)}")
    if not ok:
        print()
        print("FAILURES:")
        for r in node_results:
            if r["status"] != "OK":
                print(f"  {r['id']}  {r['status']}  {r['reason']}")
        for d in duplicates:
            preview = d["latex"][:80] + ("..." if len(d["latex"]) > 80 else "")
            print(f"  DUPLICATE  {d['first']} == {d['second']}  ({preview})")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
