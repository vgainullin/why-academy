#!/usr/bin/env python3
"""Deterministic candidate used only to exercise the frozen pilot harness."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sympy as sp


def rat(value: dict[str, int]) -> sp.Rational:
    return sp.Rational(value["numerator"], value["denominator"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--metadata-out", required=True)
    parser.add_argument("--model-cwd", required=True)
    parser.add_argument("--engine")
    parser.add_argument("--model")
    args = parser.parse_args()
    task = json.loads(Path(args.task).read_text())
    givens = task["givens"]
    a = rat(givens["lhs"]["coefficient"])
    b = rat(givens["lhs"]["constant"])
    c = rat(givens["rhs"]["coefficient"])
    d = rat(givens["rhs"]["constant"])
    x = sp.Symbol("x")
    root = sp.Eq(a * x + b, c * x + d, evaluate=False)
    divisor = a - c
    nodes = [{"id": "n0", "sympy_srepr": sp.srepr(root)}]
    edges = []
    current = root
    next_index = 1
    if c != 0:
        current = sp.Eq(current.lhs - c * x, current.rhs - c * x, evaluate=False)
        nodes.append({"id": f"n{next_index}", "sympy_srepr": sp.srepr(current)})
        edges.append({"from": f"n{next_index - 1}", "to": f"n{next_index}", "rule": "subtract_constant_from_both_sides", "rule_args": {"constant": sp.sstr(c * x)}})
        next_index += 1
    if b != 0:
        current = sp.Eq(current.lhs - b, current.rhs - b, evaluate=False)
        nodes.append({"id": f"n{next_index}", "sympy_srepr": sp.srepr(current)})
        edges.append({"from": f"n{next_index - 1}", "to": f"n{next_index}", "rule": "subtract_constant_from_both_sides", "rule_args": {"constant": sp.sstr(b)}})
        next_index += 1
    goal = sp.Eq(current.lhs / divisor, current.rhs / divisor, evaluate=False)
    nodes.append({"id": f"n{next_index}", "sympy_srepr": sp.srepr(goal)})
    edges.append({"from": f"n{next_index - 1}", "to": f"n{next_index}", "rule": "divide_both_sides", "rule_args": {"divisor": sp.sstr(divisor)}})
    graph = {
        "id": task["id"],
        "root_node": "n0",
        "goal_node": f"n{next_index}",
        "nodes": nodes,
        "edges": edges,
    }
    Path(args.out).write_text(json.dumps(graph, indent=2) + "\n")
    Path(args.metadata_out).write_text(json.dumps({"candidate_only": True, "task_id": task["id"]}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
