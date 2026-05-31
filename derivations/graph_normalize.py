#!/usr/bin/env python3
"""Normalize generated derivation graphs before presentation gates.

This is deliberately mechanical: it canonicalizes parseable node expressions,
merges duplicate node forms, rewrites edge endpoints, and drops self/repeated
edges. It does not try to prove new algebraic equivalences.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import sympy as sp

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from sympy_eval import parse_srepr  # noqa: E402
from to_canvas import eq_to_latex  # noqa: E402


NORMALIZER_VERSION = "0.2"


def _json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _canonical_srepr(expr, fallback: str) -> str:
    candidate = sp.srepr(expr)
    try:
        reparsed = parse_srepr(candidate)
        if isinstance(expr, sp.Equality) and not isinstance(reparsed, sp.Equality):
            return fallback
        return candidate
    except Exception:
        return fallback


def _canonical_node(expr, fallback: str):
    canonical_srepr = _canonical_srepr(expr, fallback)
    try:
        canonical_expr = parse_srepr(canonical_srepr)
        if isinstance(expr, sp.Equality) and not isinstance(canonical_expr, sp.Equality):
            return expr, fallback
        return canonical_expr, canonical_srepr
    except Exception:
        return expr, fallback


def _node_keys(expr) -> list[tuple[str, str]]:
    keys = [("srepr", sp.srepr(expr))]
    try:
        keys.append(("latex", eq_to_latex(expr)))
    except Exception:
        pass
    return keys


def normalize_problem(problem: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    nodes = problem.get("nodes", [])
    edges = problem.get("edges", [])

    key_owner: dict[tuple[str, str], str] = {}
    id_map: dict[str, str] = {}
    retained_nodes: list[dict[str, str]] = []
    retained_ids: set[str] = set()
    merges: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []

    for node in nodes:
        node_id = node.get("id")
        raw = node.get("sympy_srepr")
        if not isinstance(node_id, str) or not isinstance(raw, str):
            continue
        try:
            expr = parse_srepr(raw)
            canonical_expr, canonical_srepr = _canonical_node(expr, raw)
            keys = _node_keys(canonical_expr)
            owner = next((key_owner[k] for k in keys if k in key_owner), None)
            if owner is None:
                owner = node_id
                retained_ids.add(node_id)
                retained_nodes.append({
                    "id": node_id,
                    "sympy_srepr": canonical_srepr,
                })
                for key in keys:
                    key_owner.setdefault(key, owner)
            else:
                first_key = next((k for k in keys if k in key_owner and key_owner[k] == owner), keys[0])
                merges.append({
                    "from": node_id,
                    "to": owner,
                    "reason": first_key[0],
                    "key": first_key[1],
                })
            id_map[node_id] = owner
        except Exception as e:
            parse_errors.append({
                "node": node_id,
                "error": f"{type(e).__name__}: {e}",
            })
            id_map[node_id] = node_id
            retained_ids.add(node_id)
            retained_nodes.append({"id": node_id, "sympy_srepr": raw})

    dropped_edges: list[dict[str, Any]] = []
    retained_edges: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        new_edge = dict(edge)
        new_edge["from"] = id_map.get(edge.get("from"), edge.get("from"))
        new_edge["to"] = id_map.get(edge.get("to"), edge.get("to"))
        if new_edge.get("from") == new_edge.get("to"):
            dropped_edges.append({"reason": "self_edge_after_merge", "edge": new_edge})
            continue
        edge_key = _json_key({
            "from": new_edge.get("from"),
            "to": new_edge.get("to"),
            "rule": new_edge.get("rule"),
            "rule_args": new_edge.get("rule_args", {}),
        })
        if edge_key in seen_edges:
            dropped_edges.append({"reason": "duplicate_edge", "edge": new_edge})
            continue
        seen_edges.add(edge_key)
        retained_edges.append(new_edge)

    root_before = problem.get("root_node")
    goal_before = problem.get("goal_node")
    normalized = dict(problem)
    normalized["root_node"] = id_map.get(root_before, root_before)
    normalized["goal_node"] = id_map.get(goal_before, goal_before)
    normalized["nodes"] = retained_nodes
    normalized["edges"] = retained_edges

    report = {
        "normalizer_version": NORMALIZER_VERSION,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "problem_id": problem.get("id"),
        "n_nodes_before": len(nodes),
        "n_nodes_after": len(retained_nodes),
        "n_edges_before": len(edges),
        "n_edges_after": len(retained_edges),
        "root_node_before": root_before,
        "root_node_after": normalized.get("root_node"),
        "goal_node_before": goal_before,
        "goal_node_after": normalized.get("goal_node"),
        "node_merges": merges,
        "dropped_edges": dropped_edges,
        "parse_errors": parse_errors,
    }
    return normalized, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("problem", help="input problem JSON")
    ap.add_argument("--out", help="output path; defaults to overwriting input")
    ap.add_argument("--report", help="report path; defaults to <output>.normalizer.json")
    args = ap.parse_args()

    problem_path = Path(args.problem)
    out_path = Path(args.out) if args.out else problem_path
    problem = json.loads(problem_path.read_text())
    normalized, report = normalize_problem(problem)
    out_path.write_text(json.dumps(normalized, indent=2) + "\n")

    report_path = Path(args.report) if args.report else out_path.with_name(out_path.stem + ".normalizer.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "problem_id": normalized.get("id"),
        "nodes": [report["n_nodes_before"], report["n_nodes_after"]],
        "edges": [report["n_edges_before"], report["n_edges_after"]],
        "merges": len(report["node_merges"]),
        "dropped_edges": len(report["dropped_edges"]),
        "parse_errors": len(report["parse_errors"]),
        "out": str(out_path),
        "report": str(report_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
