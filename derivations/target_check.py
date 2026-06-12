#!/usr/bin/env python3
"""Deterministic check that a graph goal reaches the requested target.

This is intentionally narrower than the verifier. The verifier checks whether
edges are truth-preserving; this gate checks whether the final `goal_node`
matches the requested result instead of an easier intermediate relation.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from sympy_eval import parse_srepr  # noqa: E402


TARGET_CHECK_VERSION = "0.2"

TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)
KNOWN_FUNCS = {
    "sqrt": sp.sqrt,
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "sec": sp.Function("sec"),
    "exp": sp.exp,
    "log": sp.log,
    "pi": sp.pi,
    "E": sp.E,
    "oo": sp.oo,
    "Rational": sp.Rational,
    "Derivative": sp.Derivative,
    "Limit": sp.Limit,
}
STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "ball",
    "by",
    "completing",
    "constant",
    "conservation",
    "derive",
    "drop",
    "eliminating",
    "equation",
    "evaluate",
    "factor",
    "for",
    "frequency",
    "from",
    "get",
    "given",
    "height",
    "minimum",
    "momentum",
    "of",
    "period",
    "relation",
    "result",
    "solve",
    "system",
    "the",
    "to",
    "using",
    "where",
    "with",
    "write",
}


def normalize_text(text: str) -> str:
    text = (
        text.replace("ω", "omega")
        .replace("π", "pi")
        .replace("θ", "theta")
        .replace("−", "-")
        .replace("√", "sqrt")
    )
    return re.sub(r"\bd\s*/\s*d([A-Za-z]\w*)\s*\(([^()]+)\)", r"Derivative(\2, \1)", text)


def local_dict_for(text: str) -> dict:
    names = set(re.findall(r"[A-Za-z_]\w*", text))
    local = dict(KNOWN_FUNCS)
    for name in names:
        if name not in local:
            local[name] = sp.Symbol(name, real=True)
    return local


def parse_math_expr(text: str):
    text = normalize_text(text.strip().strip(",.;:"))
    if not text:
        raise ValueError("empty expression")
    expr = parse_expr(
        text,
        local_dict=local_dict_for(text),
        transformations=TRANSFORMS,
        evaluate=False,
    )
    bad_symbols = {s.name for s in expr.free_symbols if s.name.lower() in STOPWORDS}
    if bad_symbols:
        raise ValueError(f"non-math words in expression: {sorted(bad_symbols)}")
    return expr


def candidate_suffixes(text: str) -> list[str]:
    toks = text.strip().split()
    return [" ".join(toks[i:]) for i in range(len(toks))]


def candidate_prefixes(text: str) -> list[str]:
    toks = text.strip().split()
    return [" ".join(toks[:i]) for i in range(len(toks), 0, -1)]


def first_parseable(candidates: list[str]):
    errors = []
    for cand in candidates:
        try:
            return parse_math_expr(cand), cand
        except Exception as e:
            errors.append(f"{cand!r}: {e}")
    raise ValueError("; ".join(errors[:5]))


def equation_from_text(text: str) -> tuple[sp.Equality, str] | None:
    if "=" not in text:
        return None
    left_text, right_text = text.split("=", 1)
    left, left_src = first_parseable(candidate_suffixes(left_text))
    right, right_src = first_parseable(candidate_prefixes(right_text))
    return sp.Eq(left, right, evaluate=False), f"{left_src} = {right_src}"


def goal_phrase(target: str) -> str:
    target = normalize_text(target)
    lower = target.lower()
    if lower.startswith("derive "):
        text = target[len("derive ") :]
    elif lower.startswith("compute "):
        text = target[len("compute ") :]
    elif lower.startswith("evaluate "):
        text = target[len("evaluate ") :]
    else:
        text = target

    cut_markers = [" from ", " using ", " given ", ", given ", " where "]
    positions = [text.lower().find(m) for m in cut_markers if text.lower().find(m) >= 0]
    if positions:
        text = text[: min(positions)]
    return text.strip()


def solve_goal(target: str) -> list[tuple[sp.Equality, str]]:
    m = re.search(r"\bsolve\s+(.+?)\s+for\s+([A-Za-z_]\w*)\b", normalize_text(target), re.I)
    if not m:
        return []
    equation_text = re.split(r"\s+by\s+", m.group(1), maxsplit=1, flags=re.I)[0].strip()
    variable_name = m.group(2)
    if "=" not in equation_text:
        return []
    parsed = equation_from_text(equation_text)
    if not parsed:
        return []
    eq, src = parsed
    var = sp.Symbol(variable_name, real=True)
    try:
        sols = sp.solve(eq, var)
    except Exception:
        return []
    return [(sp.Eq(var, sol, evaluate=False), f"{src}; solve for {variable_name}") for sol in sols]


def factor_goal(target: str) -> list[tuple[sp.Equality, str]]:
    text = normalize_text(target)
    m = re.search(r"\bfactor\s+(.+?)\s+(?:as|to get)\s+(.+?)(?:\s+using\b|$)", text, re.I)
    if not m:
        return []
    try:
        lhs = parse_math_expr(m.group(1))
        rhs = parse_math_expr(m.group(2))
    except Exception:
        return []
    return [(sp.Eq(lhs, rhs, evaluate=False), f"{m.group(1)} = {m.group(2)}")]


def expected_goals(target: str) -> list[tuple[sp.Equality, str]]:
    goals = solve_goal(target)
    if goals:
        return goals
    goals = factor_goal(target)
    if goals:
        return goals

    phrase = goal_phrase(target)
    found: list[tuple[sp.Equality, str]] = []
    if "=" in phrase:
        try:
            parsed = equation_from_text(phrase)
            if parsed:
                found.append(parsed)
        except Exception:
            pass
    return found


def given_phrase(target: str) -> str:
    text = normalize_text(target)
    lower = text.lower()
    markers = [" given ", ", given ", " from ", " using "]
    positions = [(lower.find(m), m) for m in markers if lower.find(m) >= 0]
    if not positions:
        return ""
    pos, marker = min(positions, key=lambda x: x[0])
    return text[pos + len(marker):].strip()


def candidate_given_chunks(text: str) -> list[str]:
    if not text:
        return []
    normalized = re.sub(r"\(\d+\)", ";", text)
    normalized = re.sub(r"\band the\b", ";", normalized, flags=re.I)
    normalized = re.sub(r"\band\b", ";", normalized, flags=re.I)
    normalized = normalized.replace(",", ";")
    return [chunk.strip() for chunk in normalized.split(";") if "=" in chunk]


def expected_givens(target: str) -> list[tuple[sp.Equality, str]]:
    found: list[tuple[sp.Equality, str]] = []
    for chunk in candidate_given_chunks(given_phrase(target)):
        try:
            parsed = equation_from_text(chunk)
            if parsed:
                found.append(parsed)
        except Exception:
            continue
    deduped: list[tuple[sp.Equality, str]] = []
    seen = set()
    for eq, source in found:
        key = sp.srepr(canonical(eq))
        if key not in seen:
            seen.add(key)
            deduped.append((eq, source))
    return deduped


def canonical(expr):
    repl = {sym: sp.Symbol(sym.name, real=True) for sym in expr.free_symbols}
    return expr.xreplace(repl)


def expr_equiv(a, b) -> bool:
    a = canonical(a)
    b = canonical(b)
    try:
        diff = sp.simplify(a - b)
        if diff == 0:
            return True
        equals = diff.equals(0)
        return bool(equals)
    except Exception:
        return False


def eq_matches(goal, expected) -> bool:
    if not isinstance(goal, sp.Equality) or not isinstance(expected, sp.Equality):
        return False
    return (
        expr_equiv(goal.lhs, expected.lhs)
        and expr_equiv(goal.rhs, expected.rhs)
    ) or (
        expr_equiv(goal.lhs, expected.rhs)
        and expr_equiv(goal.rhs, expected.lhs)
    )


def check(problem_path: Path, target: str) -> tuple[int, dict]:
    try:
        problem = json.loads(problem_path.read_text())
        nodes = {n["id"]: n for n in problem.get("nodes", [])}
        parsed_nodes = []
        for node in problem.get("nodes", []):
            try:
                parsed_nodes.append((node["id"], parse_srepr(node["sympy_srepr"])))
            except Exception:
                pass
        goal_id = problem.get("goal_node")
        goal_node = nodes.get(goal_id)
        if not goal_node:
            raise ValueError(f"goal_node {goal_id!r} not found")
        goal_expr = parse_srepr(goal_node["sympy_srepr"])
    except Exception as e:
        return 2, {
            "target_check_version": TARGET_CHECK_VERSION,
            "target": target,
            "status": "ERROR",
            "reason": f"could not load goal node: {e}",
        }

    expected = expected_goals(target)
    givens = expected_givens(target)
    expected_payload = [
        {"source": source, "sympy_srepr": repr(eq)}
        for eq, source in expected
    ]
    given_payload = [
        {"source": source, "sympy_srepr": repr(eq)}
        for eq, source in givens
    ]
    missing_givens = []
    matched_givens = []
    for given_eq, source in givens:
        match = next((nid for nid, expr in parsed_nodes if eq_matches(expr, given_eq)), None)
        if match:
            matched_givens.append({"source": source, "node": match})
        else:
            missing_givens.append(source)
    base = {
        "target_check_version": TARGET_CHECK_VERSION,
        "problem_id": problem.get("id"),
        "target": target,
        "goal_node": goal_id,
        "goal_sympy_srepr": goal_node.get("sympy_srepr"),
        "expected_goals": expected_payload,
        "expected_givens": given_payload,
        "matched_givens": matched_givens,
        "missing_givens": missing_givens,
    }
    if missing_givens:
        return 1, {
            **base,
            "status": "FAIL",
            "goal_status": "unchecked",
            "given_status": "FAIL",
            "reason": "target givens are not visible as graph nodes: " + "; ".join(missing_givens),
        }
    if not expected:
        return 0, {
            **base,
            "status": "SKIP",
            "given_status": "PASS" if givens else "SKIP",
            "reason": "no deterministic expected goal could be extracted from target text",
        }

    for eq, source in expected:
        if eq_matches(goal_expr, eq):
            return 0, {
                **base,
                "status": "PASS",
                "goal_status": "PASS",
                "given_status": "PASS" if givens else "SKIP",
                "matched_source": source,
                "reason": "goal_node matches extracted target goal",
            }

    return 1, {
        **base,
        "status": "FAIL",
        "goal_status": "FAIL",
        "given_status": "PASS" if givens else "SKIP",
        "reason": "goal_node does not match the requested target goal",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("problem_json")
    ap.add_argument("--target", required=True)
    ap.add_argument("--out-suffix", default=".target_check.json")
    args = ap.parse_args()

    problem_path = Path(args.problem_json)
    rc, payload = check(problem_path, args.target)
    out_path = problem_path.with_name(problem_path.stem + args.out_suffix)
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
