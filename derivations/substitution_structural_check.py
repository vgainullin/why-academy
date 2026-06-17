#!/usr/bin/env python3
"""Opt-in structural check for immediate substitution edges.

The verifier proves the substitution is algebraically valid. This treatment
check is stricter: a substitution edge must stop at the immediate replaced
tree, and any arithmetic simplification must be a later edge.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import sympy as sp
from sympy import Eq

from sympy_eval import align_symbols_to, parse_arg, parse_srepr


CHECK_VERSION = "substitution_structural_check.v1"
SUBSTITUTION_RULES = {"substitute_value", "substitute_expression"}


def structural_key(expr) -> Any:
    """Stable structural key that ignores Symbol assumptions."""
    if isinstance(expr, sp.Symbol):
        return ("Symbol", expr.name)
    if isinstance(expr, sp.Integer):
        return ("Integer", int(expr))
    if isinstance(expr, sp.Rational):
        return ("Rational", int(expr.p), int(expr.q))
    if isinstance(expr, sp.Float):
        return ("Float", str(expr))
    if isinstance(expr, Eq):
        return ("Eq", structural_key(expr.lhs), structural_key(expr.rhs))
    return (expr.func.__name__, tuple(structural_key(a) for a in expr.args))


def expr_to_srepr(expr) -> str:
    """Serialize a SymPy tree into this repo's parseable expression subset.

    SymPy's own srepr omits evaluate=False and can re-collapse the tree on
    parse. This serializer preserves Add/Mul/Pow/Eq grouping for immediate
    substitution artifacts.
    """
    if expr is sp.S.true:
        return "true"
    if expr is sp.S.false:
        return "false"
    if expr == sp.oo:
        return "oo"
    if expr == -sp.oo:
        return "-oo"
    if expr == sp.pi:
        return "pi"
    if expr == sp.E:
        return "E"
    if isinstance(expr, sp.Symbol):
        return f"Symbol({expr.name!r})"
    if isinstance(expr, sp.Integer):
        return f"Integer({int(expr)})"
    if isinstance(expr, sp.Rational):
        return f"Rational({int(expr.p)}, {int(expr.q)})"
    if isinstance(expr, sp.Float):
        return f"Float({str(expr)!r})"
    if isinstance(expr, Eq):
        return f"Eq({expr_to_srepr(expr.lhs)}, {expr_to_srepr(expr.rhs)}, evaluate=False)"
    if isinstance(expr, sp.Add):
        return "Add(" + ", ".join(expr_to_srepr(a) for a in expr.args) + ", evaluate=False)"
    if isinstance(expr, sp.Mul):
        return "Mul(" + ", ".join(expr_to_srepr(a) for a in expr.args) + ", evaluate=False)"
    if isinstance(expr, sp.Pow):
        return f"Pow({expr_to_srepr(expr.args[0])}, {expr_to_srepr(expr.args[1])}, evaluate=False)"
    if isinstance(expr, sp.Limit):
        return "Limit(" + ", ".join(expr_to_srepr(a) for a in expr.args) + ")"
    if isinstance(expr, sp.Derivative):
        return "Derivative(" + ", ".join(expr_to_srepr(a) for a in expr.args) + ")"
    if isinstance(expr, sp.Function):
        return f"{expr.func.__name__}(" + ", ".join(expr_to_srepr(a) for a in expr.args) + ")"
    return sp.srepr(expr)


def _rebuild(expr, args: tuple):
    if isinstance(expr, Eq):
        return Eq(args[0], args[1], evaluate=False)
    if isinstance(expr, sp.Add):
        return sp.Add(*args, evaluate=False)
    if isinstance(expr, sp.Mul):
        return sp.Mul(*args, evaluate=False)
    if isinstance(expr, sp.Pow):
        return sp.Pow(args[0], args[1], evaluate=False)
    try:
        return expr.func(*args, evaluate=False)
    except TypeError:
        return expr.func(*args)


def immediate_substitute(expr, pattern, replacement):
    """Return expr with immediate structural replacements and no simplification."""
    if structural_key(expr) == structural_key(pattern):
        return replacement, True
    if not expr.args:
        return expr, False

    changed = False
    new_args = []
    for arg in expr.args:
        new_arg, did_change = immediate_substitute(arg, pattern, replacement)
        changed = changed or did_change
        new_args.append(new_arg)
    if not changed:
        return expr, False
    return _rebuild(expr, tuple(new_args)), True


def expected_immediate_substitution(from_expr, args: dict):
    if not isinstance(from_expr, Eq):
        raise ValueError("from expression must be Eq")
    if not isinstance(args, dict):
        raise ValueError("rule_args must be an object")
    if "symbol" not in args or "replacement" not in args:
        raise ValueError("missing required args: symbol, replacement")
    pattern = parse_arg(args["symbol"])
    replacement = parse_arg(args["replacement"])
    pattern = align_symbols_to(from_expr, pattern)
    replacement = align_symbols_to(from_expr, replacement)
    expected, changed = immediate_substitute(from_expr, pattern, replacement)
    if not changed:
        raise ValueError(f"substitution pattern {pattern} not present in from expression")
    return expected


def check_problem(problem: dict) -> dict:
    parsed = {}
    parse_errors = []
    for node in problem.get("nodes", []):
        try:
            parsed[node["id"]] = parse_srepr(node["sympy_srepr"])
        except Exception as e:
            parse_errors.append({"node": node.get("id"), "error": f"{type(e).__name__}: {e}"})

    inspected = []
    failures = []
    for edge in problem.get("edges", []):
        rule = edge.get("rule")
        if rule not in SUBSTITUTION_RULES:
            continue
        item = {
            "edge": {"from": edge.get("from"), "to": edge.get("to"), "rule": rule},
            "status": "ERROR",
            "reason": "",
        }
        from_expr = parsed.get(edge.get("from"))
        to_expr = parsed.get(edge.get("to"))
        if from_expr is None or to_expr is None:
            item["reason"] = "edge endpoint failed to parse"
            inspected.append(item)
            failures.append(item)
            continue
        try:
            expected = expected_immediate_substitution(from_expr, edge.get("rule_args") or {})
        except Exception as e:
            item["reason"] = f"{type(e).__name__}: {e}"
            inspected.append(item)
            failures.append(item)
            continue

        item.update({
            "expected_sympy_srepr": expr_to_srepr(expected),
            "actual_sympy_srepr": expr_to_srepr(to_expr),
        })
        if structural_key(expected) == structural_key(to_expr):
            item["status"] = "PASS"
            item["reason"] = "substitution edge stops at the immediate replaced form"
        else:
            item["status"] = "FAIL"
            item["reason"] = "substitution edge also simplified or otherwise rewrote the immediate form"
            failures.append(item)
        inspected.append(item)

    status = "ERROR" if parse_errors else ("FAIL" if failures else "PASS")
    return {
        "check_version": CHECK_VERSION,
        "problem_id": problem.get("id"),
        "status": status,
        "n_inspected": len(inspected),
        "parse_errors": parse_errors,
        "inspected_edges": inspected,
        "failures": failures,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("problem_json")
    args = ap.parse_args()
    path = Path(args.problem_json)
    problem = json.loads(path.read_text())
    report = check_problem(problem)
    path.with_suffix(".substitution_check.json").write_text(json.dumps(report, indent=2))
    if report["status"] != "PASS":
        print(json.dumps(report["failures"][:3] or report["parse_errors"][:3], indent=2), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
