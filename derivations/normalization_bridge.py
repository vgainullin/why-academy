#!/usr/bin/env python3
"""Opt-in rule-executor normalization bridge.

The legacy normalizer is expression-oriented. This bridge gives it the extra
contract it needs for rule-executor experiments: executor step edges that
perform real structural work must survive normalization as separate edges.
No-op executor edges may still collapse so canvas duplicate checks can pass.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from graph_normalize import _edge_identity, normalize_problem  # noqa: E402
from substitution_structural_check import check_problem, structural_key  # noqa: E402
from sympy_eval import parse_srepr  # noqa: E402


BRIDGE_VERSION = "normalization_bridge.v1"
NORMALIZATION_MODE = "preserve-executor-boundaries"


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _same_path(a: Path, b: Path) -> bool:
    return a.resolve() == b.resolve()


def _node_sreprs(problem: dict[str, Any]) -> dict[str, str]:
    out = {}
    for node in problem.get("nodes", []):
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            out[node["id"]] = str(node.get("sympy_srepr", ""))
    return out


def _noop_key(raw_srepr: str) -> Any:
    return structural_key(parse_srepr(raw_srepr))


def _is_canonical_noop(from_srepr: str | None, to_srepr: str | None) -> bool:
    if not isinstance(from_srepr, str) or not isinstance(to_srepr, str):
        return False
    try:
        return _noop_key(from_srepr) == _noop_key(to_srepr)
    except Exception:
        return False


def _executor_step_edges(executor_report: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for step in executor_report.get("step_results", []):
        if not isinstance(step, dict) or step.get("status") != "PASS":
            continue
        edge = step.get("edge")
        if not isinstance(edge, dict):
            continue
        out.append({
            "step_id": step.get("id"),
            "step_from_ref": step.get("from"),
            "step_rule": step.get("rule"),
            "from_sympy_srepr": step.get("from_sympy_srepr"),
            "to_sympy_srepr": step.get("to_sympy_srepr"),
            "edge": {
                "from": edge.get("from"),
                "to": edge.get("to"),
                "rule": edge.get("rule"),
                "rule_args": edge.get("rule_args", {}),
            },
        })
    return out


def build_bridge_artifacts(
    raw_problem: dict[str, Any],
    executor_report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw_edges = {_edge_identity(edge) for edge in raw_problem.get("edges", []) if isinstance(edge, dict)}
    raw_sreprs = _node_sreprs(raw_problem)
    protected_records = []
    allowed_noop_drops = []
    contract_mismatches = []

    for record in _executor_step_edges(executor_report):
        edge = record["edge"]
        if _edge_identity(edge) not in raw_edges:
            contract_mismatches.append({
                "reason": "executor_edge_missing_from_raw_problem",
                **record,
            })
            continue
        from_srepr = raw_sreprs.get(edge.get("from"))
        to_srepr = raw_sreprs.get(edge.get("to"))
        if _is_canonical_noop(from_srepr, to_srepr):
            allowed_noop_drops.append({
                "reason": "raw_step_noop" if from_srepr == to_srepr else "canonical_step_noop",
                **record,
            })
            continue
        protected_records.append(record)

    protected_edges = [
        {
            **record["edge"],
            "step_id": record.get("step_id"),
            "step_rule": record.get("step_rule"),
        }
        for record in protected_records
    ]
    normalized, normalizer_report = normalize_problem(raw_problem, protected_edges=protected_edges)

    id_map = normalizer_report.get("id_map", {})
    normalized_edges = {
        _edge_identity(edge)
        for edge in normalized.get("edges", [])
        if isinstance(edge, dict)
    }
    preserved_edges = []
    boundary_violations = []
    for record in protected_records:
        edge = record["edge"]
        mapped = {
            "from": id_map.get(edge.get("from"), edge.get("from")),
            "to": id_map.get(edge.get("to"), edge.get("to")),
            "rule": edge.get("rule"),
            "rule_args": edge.get("rule_args", {}),
        }
        if mapped["from"] == mapped["to"]:
            boundary_violations.append({
                "reason": "protected_edge_collapsed",
                "mapped_edge": mapped,
                **record,
            })
        elif _edge_identity(mapped) not in normalized_edges:
            boundary_violations.append({
                "reason": "protected_edge_missing_after_normalization",
                "mapped_edge": mapped,
                **record,
            })
        else:
            preserved_edges.append({
                "mapped_edge": mapped,
                **record,
            })

    raw_substitution = check_problem(raw_problem)
    normalized_substitution = check_problem(normalized)
    raw_pass_normalized_substitution_fail = (
        raw_substitution.get("status") == "PASS"
        and normalized_substitution.get("status") != "PASS"
    )
    if raw_pass_normalized_substitution_fail:
        boundary_violations.append({
            "reason": "raw_pass_normalized_substitution_fail",
            "raw_status": raw_substitution.get("status"),
            "normalized_status": normalized_substitution.get("status"),
        })

    if contract_mismatches:
        status = "normalization_contract_mismatch"
    elif boundary_violations:
        status = "normalization_boundary_fail"
    else:
        status = "PASS"

    bridge_report = {
        "bridge_version": BRIDGE_VERSION,
        "normalization_mode": NORMALIZATION_MODE,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "problem_id": raw_problem.get("id"),
        "status": status,
        "protected_edges": protected_records,
        "preserved_edges": preserved_edges,
        "node_map": id_map,
        "blocked_merges": normalizer_report.get("blocked_merges", []),
        "allowed_drops": allowed_noop_drops,
        "allowed_noop_drops": allowed_noop_drops,
        "boundary_violations": boundary_violations,
        "contract_mismatches": contract_mismatches,
        "raw_substitution_status": raw_substitution.get("status"),
        "normalized_substitution_status": normalized_substitution.get("status"),
        "raw_substitution": raw_substitution,
        "normalized_substitution": normalized_substitution,
        "metrics": {
            "protected_edges": len(protected_records),
            "preserved_edges": len(preserved_edges),
            "collapsed_protected_edges": sum(
                1 for item in boundary_violations
                if item.get("reason") == "protected_edge_collapsed"
            ),
            "blocked_merges": len(normalizer_report.get("blocked_merges", [])),
            "allowed_noop_drops": len(allowed_noop_drops),
            "raw_pass_normalized_substitution_fail": int(raw_pass_normalized_substitution_fail),
        },
    }
    return normalized, normalizer_report, bridge_report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("problem", help="raw rule-executor problem JSON")
    ap.add_argument("--executor-report", required=True, help="problem.rule_executor.json path")
    ap.add_argument("--out", help="normalized output path; defaults to overwriting input")
    ap.add_argument("--normalizer-report", help="normalizer report path")
    ap.add_argument("--bridge-report", help="bridge report path")
    args = ap.parse_args()

    problem_path = Path(args.problem)
    out_path = Path(args.out) if args.out else problem_path
    normalizer_report_path = (
        Path(args.normalizer_report)
        if args.normalizer_report
        else out_path.with_name(out_path.stem + ".normalizer.json")
    )
    bridge_report_path = (
        Path(args.bridge_report)
        if args.bridge_report
        else out_path.with_name(out_path.stem + ".normalization_bridge.json")
    )

    raw_problem = _read_json_object(problem_path)
    executor_report = _read_json_object(Path(args.executor_report))
    try:
        normalized, normalizer_report, bridge_report = build_bridge_artifacts(raw_problem, executor_report)
    except Exception as e:
        if not _same_path(out_path, problem_path):
            out_path.unlink(missing_ok=True)
        bridge_report = {
            "bridge_version": BRIDGE_VERSION,
            "normalization_mode": NORMALIZATION_MODE,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "problem_id": raw_problem.get("id"),
            "status": "normalization_bridge_fail",
            "error": f"{type(e).__name__}: {e}",
        }
        bridge_report_path.write_text(json.dumps(bridge_report, indent=2) + "\n")
        print(json.dumps(bridge_report, indent=2), file=sys.stderr)
        return 1

    normalizer_report_path.write_text(json.dumps(normalizer_report, indent=2) + "\n")
    bridge_report_path.write_text(json.dumps(bridge_report, indent=2) + "\n")
    candidate_path = None
    if bridge_report["status"] == "PASS":
        out_path.write_text(json.dumps(normalized, indent=2) + "\n")
    else:
        if not _same_path(out_path, problem_path):
            out_path.unlink(missing_ok=True)
        candidate_path = out_path.with_name(out_path.stem + ".normalization_bridge_candidate.json")
        candidate_path.write_text(json.dumps(normalized, indent=2) + "\n")
    print(json.dumps({
        "problem_id": bridge_report.get("problem_id"),
        "status": bridge_report["status"],
        "protected_edges": bridge_report["metrics"]["protected_edges"],
        "preserved_edges": bridge_report["metrics"]["preserved_edges"],
        "blocked_merges": bridge_report["metrics"]["blocked_merges"],
        "allowed_noop_drops": bridge_report["metrics"]["allowed_noop_drops"],
        "out": str(out_path) if bridge_report["status"] == "PASS" else None,
        "candidate": str(candidate_path) if candidate_path else None,
        "normalizer_report": str(normalizer_report_path),
        "bridge_report": str(bridge_report_path),
    }, indent=2))
    return 0 if bridge_report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
