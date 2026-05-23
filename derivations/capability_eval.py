#!/usr/bin/env python3
"""Evaluate a generated validator candidate in an isolated proposal package."""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from sympy import Eq
from sympy.core.relational import Equality

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from sympy_eval import parse_srepr  # noqa: E402


SAFE_IMPORT_MODULES = {"sympy", "sympy_eval"}
SAFE_FUTURE_IMPORTS = {"annotations"}
SAFE_DUNDER_ATTRIBUTES = {"__name__"}
DANGEROUS_NAMES = {
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "globals",
    "input",
    "locals",
    "open",
}
DANGEROUS_MODULES = {"os", "pathlib", "shutil", "socket", "subprocess", "sys"}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def assert_safe_validator_source(path: Path) -> None:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] not in SAFE_IMPORT_MODULES:
                    raise ValueError(f"unsafe import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".", 1)[0]
            if module == "__future__":
                unsafe = [alias.name for alias in node.names if alias.name not in SAFE_FUTURE_IMPORTS]
                if unsafe:
                    raise ValueError(f"unsafe future import: {', '.join(unsafe)}")
                continue
            if module not in SAFE_IMPORT_MODULES:
                raise ValueError(f"unsafe import-from: {node.module}")
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in DANGEROUS_NAMES:
                raise ValueError(f"unsafe call: {fn.id}")
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                if fn.value.id in DANGEROUS_MODULES:
                    raise ValueError(f"unsafe module call: {fn.value.id}.{fn.attr}")
        elif isinstance(node, ast.Name) and node.id in DANGEROUS_NAMES:
            raise ValueError(f"unsafe name: {node.id}")
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError(f"unsafe dunder name: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr not in SAFE_DUNDER_ATTRIBUTES:
            raise ValueError(f"unsafe dunder attribute: {node.attr}")


def load_candidate(path: Path):
    assert_safe_validator_source(path)
    spec = importlib.util.spec_from_file_location("capability_candidate_validator", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"could not load spec for {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not isinstance(getattr(mod, "RULE_NAME", None), str):
        raise ValueError("candidate missing string RULE_NAME")
    if not callable(getattr(mod, "validate", None)):
        raise ValueError("candidate missing validate(from_expr, to_expr, args)")
    return mod


def iter_cases(tests: dict[str, Any]) -> list[dict[str, Any]]:
    cases = []
    for polarity in ("positive", "negative"):
        for case in tests.get(polarity, []):
            merged = dict(case)
            merged["polarity"] = polarity
            if "expected" not in merged:
                merged["expected"] = "PASS" if polarity == "positive" else "FAIL"
            cases.append(merged)
    return cases


def iter_evidence_cases(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    cases = []
    rule_name = proposal["rule_name"]
    for idx, evidence in enumerate(proposal.get("evidence") or []):
        edge = evidence.get("edge") or {}
        if edge.get("rule") != rule_name:
            continue
        cases.append({
            "description": (
                f"{evidence.get('batch_id', 'unknown_batch')} "
                f"{evidence.get('problem_id', 'unknown_problem')} "
                f"{evidence.get('iter', 'unknown_iter')} "
                f"{edge.get('from', '?')}->{edge.get('to', '?')}"
            ),
            "from_srepr": edge.get("from_srepr"),
            "to_srepr": edge.get("to_srepr"),
            "args": edge.get("rule_args") or {},
            "expected": "PASS",
            "polarity": "closure",
            "reason": edge.get("reason"),
        })
    return cases


def run_case(mod, case: dict[str, Any]) -> dict[str, Any]:
    try:
        from_expr = parse_srepr(case["from_srepr"])
        to_expr = parse_srepr(case["to_srepr"])
        status, reason = mod.validate(from_expr, to_expr, case.get("args") or {})
    except Exception as e:
        status, reason = "ERROR", f"{type(e).__name__}: {e}"
    expected = case.get("expected")
    ok = status == expected
    return {
        "description": case.get("description", ""),
        "polarity": case.get("polarity"),
        "expected": expected,
        "actual": status,
        "ok": ok,
        "reason": reason,
    }


def orientation_guard_enabled(rule_name: str) -> bool:
    lowered = rule_name.lower()
    return "swap" not in lowered and "commute" not in lowered


def run_orientation_guard(mod, case: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from_expr = parse_srepr(case["from_srepr"])
        to_expr = parse_srepr(case["to_srepr"])
        if not isinstance(to_expr, Equality):
            return None
        if to_expr.lhs == to_expr.rhs:
            return None
        swapped = Eq(to_expr.rhs, to_expr.lhs, evaluate=False)
        status, reason = mod.validate(from_expr, swapped, case.get("args") or {})
    except Exception as e:
        status, reason = "ERROR", f"{type(e).__name__}: {e}"
    ok = status != "PASS"
    return {
        "description": f"{case.get('description', '')} [orientation guard]",
        "polarity": "orientation_guard",
        "expected": "not PASS",
        "actual": status,
        "ok": ok,
        "reason": reason,
    }


def evaluate(proposal_dir: Path) -> tuple[int, dict[str, Any]]:
    proposal = read_json(proposal_dir / "proposal.json")
    candidate_dir = proposal_dir / "candidate"
    validator_path = candidate_dir / "validator.py"
    tests_path = candidate_dir / "tests.json"
    if not validator_path.exists():
        rejected_path = candidate_dir / "rejected.json"
        if rejected_path.exists():
            rejected = read_json(rejected_path)
            return 1, {
                "schema_version": "capability_eval.v1",
                "proposal_dir": str(proposal_dir),
                "rule_name": proposal["rule_name"],
                "status": "REJECTED",
                "reason": rejected.get("reason", "candidate synthesis rejected this proposal"),
                "rejected": rejected,
            }
        return 2, {"status": "ERROR", "reason": f"missing {validator_path}"}
    if not tests_path.exists():
        return 2, {"status": "ERROR", "reason": f"missing {tests_path}"}

    tests = read_json(tests_path)
    mod = load_candidate(validator_path)
    if mod.RULE_NAME != proposal["rule_name"]:
        return 2, {
            "status": "ERROR",
            "reason": f"RULE_NAME mismatch: {mod.RULE_NAME!r} != {proposal['rule_name']!r}",
        }

    cases = iter_cases(tests)
    positives = [c for c in cases if c.get("polarity") == "positive"]
    negatives = [c for c in cases if c.get("polarity") == "negative"]
    results = [run_case(mod, c) for c in cases]
    unit_ok = all(r["ok"] for r in results) and bool(positives) and bool(negatives)

    closure_cases = iter_evidence_cases(proposal)
    closure_results = [run_case(mod, c) for c in closure_cases]
    closure_ok = bool(closure_cases) and all(r["ok"] for r in closure_results)

    orientation_results = []
    if orientation_guard_enabled(proposal["rule_name"]):
        for case in positives + closure_cases:
            guard = run_orientation_guard(mod, case)
            if guard is not None:
                orientation_results.append(guard)
    orientation_ok = all(r["ok"] for r in orientation_results)
    ok = unit_ok and closure_ok and orientation_ok
    payload = {
        "schema_version": "capability_eval.v1",
        "proposal_dir": str(proposal_dir),
        "rule_name": proposal["rule_name"],
        "status": "PASS" if ok else "FAIL",
        "unit_status": "PASS" if unit_ok else "FAIL",
        "closure_status": "PASS" if closure_ok else "FAIL",
        "orientation_status": "PASS" if orientation_ok else "FAIL",
        "n_cases": len(cases),
        "n_positive": len(positives),
        "n_negative": len(negatives),
        "n_failed": sum(1 for r in results if not r["ok"]),
        "results": results,
        "n_closure": len(closure_cases),
        "n_closure_failed": sum(1 for r in closure_results if not r["ok"]),
        "closure_results": closure_results,
        "n_orientation": len(orientation_results),
        "n_orientation_failed": sum(1 for r in orientation_results if not r["ok"]),
        "orientation_results": orientation_results,
    }
    return (0 if ok else 1), payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("proposal_dir")
    args = ap.parse_args()
    proposal_dir = Path(args.proposal_dir)
    try:
        rc, payload = evaluate(proposal_dir)
    except Exception as e:
        rc, payload = 2, {"status": "ERROR", "reason": f"{type(e).__name__}: {e}"}
    out = proposal_dir / "candidate" / "eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
