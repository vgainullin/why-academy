#!/usr/bin/env python3
"""Verify a derivation graph.

v0 contract:
  - Parse every node's sympy_srepr under `from sympy import *` + standard symbols.
  - Per node: classify as TRUE (identity), FALSE (non-identity equation), NA (not an Eq), ERROR (parse failed).
  - Per edge: run the rule-specific validator if registered; otherwise fall back to
    truth-preservation between Eq endpoints. Truth-preserving + no validator -> WEAK_PASS.
    Validator says no -> FAIL. Non-truth-preserving + no validator -> FAIL. No Eq endpoints
    and no validator -> UNCOVERED.
  - Emit <problem>.verifier.json sidecar with machine-readable per-edge results.
  - Print the structured summary that generate_derivation.md expects.

This file is read-only from the LLM's point of view; the inner-loop prompt forbids modifying it.
"""
from __future__ import annotations
import importlib.util
import json
import os
import sys
import datetime
from pathlib import Path

from sympy import Eq, simplify, solve

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability_eval import assert_safe_validator_source  # noqa: E402
from json_inner import known_rule_names  # noqa: E402
from rule_contracts import build_contract_validators  # noqa: E402
from sympy_eval import parse_srepr  # noqa: E402

VERIFIER_VERSION = "0.2"
BASE_VALIDATORS_DIR = Path(__file__).resolve().parent / "validators"


def node_truth(expr) -> str:
    """TRUE if identity, FALSE if non-identity equation, NA if not an Eq, ERROR on exception."""
    try:
        if isinstance(expr, Eq):
            return "TRUE" if simplify(expr.lhs - expr.rhs) == 0 else "FALSE"
        return "NA"
    except Exception:
        return "ERROR"


def truth_preserves(a: Eq, b: Eq) -> bool:
    """Both equations describe the same solution set, by cheap heuristics first."""
    try:
        da = simplify(a.lhs - a.rhs)
        db = simplify(b.lhs - b.rhs)
        if simplify(da - db) == 0:
            return True
        ratio = simplify(da / db)
        if ratio.is_constant() and ratio != 0 and ratio.is_finite:
            return True
        free = a.free_symbols | b.free_symbols
        if len(free) == 1:
            v = next(iter(free))
            return set(solve(a, v)) == set(solve(b, v))
    except Exception:
        return False
    return False


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _validator_dirs() -> list[Path]:
    extra = [
        Path(p)
        for p in os.environ.get("DERIVATION_VALIDATOR_DIRS", "").split(os.pathsep)
        if p.strip()
    ]
    if _truthy_env("DERIVATION_VALIDATOR_PREPEND"):
        return extra + [BASE_VALIDATORS_DIR]
    return [BASE_VALIDATORS_DIR] + extra


def _load_validators() -> tuple[dict, dict]:
    """Auto-discover validators/*.py. Each file must export RULE_NAME (str) and
    validate(from_expr, to_expr, args) -> (status, reason)."""
    out: dict = {}
    sources: dict = {}
    for vdir in _validator_dirs():
        if not vdir.exists():
            continue
        for f in sorted(vdir.glob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                if vdir != BASE_VALIDATORS_DIR:
                    assert_safe_validator_source(f)
                spec = importlib.util.spec_from_file_location(f"validator_{len(sources)}_{f.stem}", f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except Exception as e:
                print(f"[verify] WARN: failed to load validator {f}: {e}", file=sys.stderr)
                continue
            name = getattr(mod, "RULE_NAME", None)
            fn = getattr(mod, "validate", None)
            if not (isinstance(name, str) and callable(fn)):
                print(f"[verify] WARN: validator {f} missing RULE_NAME or validate()", file=sys.stderr)
                continue
            if name in out:
                print(f"[verify] WARN: duplicate validator for rule {name}; keeping first", file=sys.stderr)
                continue
            out[name] = fn
            sources[name] = str(f)
    contract_validators, contract_sources = build_contract_validators()
    for name, fn in contract_validators.items():
        if name in out:
            continue
        out[name] = fn
        sources[name] = contract_sources.get(name, "rule_contracts")
    return out, sources


VALIDATORS, VALIDATOR_SOURCES = _load_validators()
KNOWN_RULES = set(known_rule_names())


def verify_edge(from_expr, to_expr, rule: str, args: dict) -> tuple[str, str]:
    validator = VALIDATORS.get(rule)
    if validator is not None:
        try:
            return validator(from_expr, to_expr, args or {})
        except Exception as e:
            return ("FAIL", f"validator raised: {e}")
    if rule not in KNOWN_RULES:
        return ("FAIL", f"unknown rule {rule!r}; use registered rules from the prompt/rule library")
    if not (isinstance(from_expr, Eq) and isinstance(to_expr, Eq)):
        return ("UNCOVERED", "non-Eq endpoints and no specific validator")
    if truth_preserves(from_expr, to_expr):
        return ("WEAK_PASS", "truth-preserving; no specific validator registered")
    return ("FAIL", "not truth-preserving and no specific validator to defer to")


def verify(problem_path: Path) -> int:
    problem = json.loads(problem_path.read_text())
    pid = problem["id"]
    nodes = problem["nodes"]
    edges = problem["edges"]

    parsed: dict = {}
    parse_errors: list = []
    for node in nodes:
        try:
            parsed[node["id"]] = parse_srepr(node["sympy_srepr"])
        except Exception as e:
            parse_errors.append((node["id"], f"{type(e).__name__}: {e}"))

    truth = {"TRUE": 0, "FALSE": 0, "ERROR": 0, "NA": 0}
    for _nid, expr in parsed.items():
        truth[node_truth(expr)] += 1
    truth["ERROR"] += len(parse_errors)

    edge_results = []
    for edge in edges:
        f, t = edge["from"], edge["to"]
        if f not in parsed or t not in parsed:
            edge_results.append({
                "from": f, "to": t, "rule": edge["rule"],
                "status": "ERROR",
                "reason": "endpoint failed to parse",
            })
            continue
        status, reason = verify_edge(parsed[f], parsed[t], edge["rule"], edge.get("rule_args"))
        edge_results.append({
            "from": f, "to": t, "rule": edge["rule"],
            "status": status, "reason": reason,
        })

    edge_summary = {"PASS": 0, "FAIL": 0, "UNCOVERED": 0, "WEAK_PASS": 0, "ERROR": 0}
    for r in edge_results:
        edge_summary[r["status"]] += 1

    out_count: dict = {}
    for e in edges:
        out_count[e["from"]] = out_count.get(e["from"], 0) + 1
    branching = sorted([nid for nid, c in out_count.items() if c > 1])
    rules_used = sorted({e["rule"] for e in edges})

    record = {
        "problem_id": pid,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "verifier_version": VERIFIER_VERSION,
        "n_nodes": len(nodes),
        "n_edges": len(edges),
        "parsed_nodes": len(parsed),
        "parse_errors": [{"node": nid, "error": err} for nid, err in parse_errors],
        "node_truth": truth,
        "rules_used": rules_used,
        "validator_sources": {r: VALIDATOR_SOURCES[r] for r in rules_used if r in VALIDATOR_SOURCES},
        "branching_nodes": branching,
        "edge_results": edge_results,
        "edge_summary": edge_summary,
    }
    sidecar = problem_path.with_suffix(".verifier.json")
    sidecar.write_text(json.dumps(record, indent=2))

    print(f"GRAPH:       {pid}")
    print(f"NODES:       {len(nodes)}")
    print(f"EDGES:       {len(edges)}")
    print(f"RULES USED:  {len(rules_used)}")
    print(f"BRANCHING:   {', '.join(branching) if branching else 'none'}")
    print()
    print("VERIFIER:")
    print(f"  PARSE:     {len(parsed)}/{len(nodes)}")
    print(f"  NODE TRUTH: TRUE={truth['TRUE']}  FALSE={truth['FALSE']}  ERROR={truth['ERROR']}")
    es = edge_summary
    print(f"  EDGES:     PASS={es['PASS']}  FAIL={es['FAIL']}  UNCOVERED={es['UNCOVERED']}  WEAK_PASS={es['WEAK_PASS']}  ERROR={es['ERROR']}")
    failures = [r for r in edge_results if r["status"] == "FAIL"]
    if failures:
        print()
        print("FAILURES:")
        for r in failures:
            print(f"  {r['from']}->{r['to']}  {r['rule']}  {r['reason']}")

    return 0 if edge_summary["FAIL"] == 0 and edge_summary["ERROR"] == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: verify.py <problem.json>", file=sys.stderr)
        sys.exit(2)
    sys.exit(verify(Path(sys.argv[1])))
