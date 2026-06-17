#!/usr/bin/env python3
"""Deterministic executor for opt-in derivation rule plans."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sympy as sp
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from sympy import Derivative, Eq, Limit, sqrt

from json_inner import ProblemJsonError, extract_json_object, known_rule_names
from substitution_structural_check import (
    expr_to_srepr,
    expected_immediate_substitution,
)
from sympy_eval import align_symbols_to, expr_equal_zero, parse_arg, parse_srepr


ROOT = Path(__file__).resolve().parent
PROMPT = ROOT / "prompts" / "generate_derivation_rule_plan.md"
EXECUTOR_VERSION = "rule_executor.v1"

SIDEWISE_ARG_KEYS = {
    "add_constant_to_both_sides": ("constant",),
    "subtract_constant_from_both_sides": ("constant",),
    "multiply_both_sides": ("multiplier",),
    "divide_both_sides": ("divisor", "factor", "constant"),
}

SUPPORTED_RULES = {
    *SIDEWISE_ARG_KEYS,
    "substitute_value",
    "substitute_expression",
    "swap_sides",
    "simplify_expression",
    "expand_expression",
    "factor_expression",
    "take_positive_square_root",
    "limit_definition_of_derivative",
    "apply_limit_definition_of_derivative",
    "rewrite_within_limit",
    "expand_within_limit",
    "cancel_within_limit",
    "simplify_within_limit",
    "evaluate_limit",
    "evaluate_limit_by_substitution",
    "take_limit",
}

RULE_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "root_ref", "goal_ref", "facts", "steps"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "root_ref": {"type": "string", "minLength": 1},
        "goal_ref": {"type": "string", "minLength": 1},
        "facts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ref", "expr"],
                "properties": {
                    "ref": {"type": "string", "minLength": 1},
                    "expr": {"type": "string", "minLength": 1},
                },
            },
        },
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "from", "rule"],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "from": {"type": "string", "minLength": 1},
                    "rule": {"type": "string", "minLength": 1},
                    "rule_args": {"type": "object"},
                },
            },
        },
    },
}

RULE_PLAN_VALIDATOR = Draft202012Validator(RULE_PLAN_SCHEMA)


class RulePlanError(ValueError):
    pass


@dataclass
class RuleExecutorError(RuntimeError):
    message: str
    failure_class: str
    report: dict

    def __str__(self) -> str:
        return self.message


class RuleExecutorCoverageGap(RuleExecutorError):
    pass


class RuleExecutorExecutionError(RuleExecutorError):
    pass


def _schema_path(error: ValidationError) -> str:
    if not error.path:
        return "$"
    parts = ["$"]
    for part in error.path:
        parts.append(f"[{part}]" if isinstance(part, int) else f".{part}")
    return "".join(parts)


def _validate_schema(plan: Any) -> None:
    errors = sorted(RULE_PLAN_VALIDATOR.iter_errors(plan), key=lambda e: tuple(str(p) for p in e.path))
    if errors:
        error = errors[0]
        raise RulePlanError(f"schema validation failed at {_schema_path(error)}: {error.message}")


def validate_rule_plan(plan: dict[str, Any], *, problem_id: str) -> dict[str, Any]:
    _validate_schema(plan)
    if plan.get("id") != problem_id:
        raise RulePlanError(f"id must be {problem_id!r}, got {plan.get('id')!r}")

    refs = set()
    fact_refs = set()
    for i, fact in enumerate(plan["facts"]):
        ref = fact["ref"]
        if ref in refs:
            raise RulePlanError(f"duplicate ref: {ref}")
        refs.add(ref)
        fact_refs.add(ref)
        try:
            expr = parse_srepr(fact["expr"])
        except Exception as e:
            raise RulePlanError(f"facts[{i}].expr failed to parse: {type(e).__name__}: {e}") from e
        if not isinstance(expr, Eq):
            raise RulePlanError(f"facts[{i}].expr must parse to Eq")

    step_refs = set()
    step_from: dict[str, str] = {}
    for i, step in enumerate(plan["steps"]):
        sid = step["id"]
        if sid in refs:
            raise RulePlanError(f"duplicate ref: {sid}")
        if step["from"] not in refs:
            raise RulePlanError(f"steps[{i}].from references unknown ref {step['from']!r}")
        if "rule_args" in step and not isinstance(step["rule_args"], dict):
            raise RulePlanError(f"steps[{i}].rule_args must be an object")
        refs.add(sid)
        step_refs.add(sid)
        step_from[sid] = step["from"]

    root_ref = plan["root_ref"]
    goal_ref = plan["goal_ref"]
    if root_ref not in fact_refs:
        raise RulePlanError("root_ref must reference an initial fact")
    if goal_ref not in refs:
        raise RulePlanError("goal_ref references unknown ref")
    if goal_ref not in step_refs:
        raise RulePlanError("goal_ref must reference a derived step, not an initial fact")

    cursor = goal_ref
    seen = set()
    while cursor in step_from:
        if cursor in seen:
            raise RulePlanError("goal_ref derivation contains a cycle")
        seen.add(cursor)
        cursor = step_from[cursor]
    if cursor != root_ref:
        raise RulePlanError("goal_ref must be derived from root_ref")
    return plan


def plan_from_response(text: str, *, problem_id: str) -> dict[str, Any]:
    try:
        value = extract_json_object(text)
    except ProblemJsonError as e:
        raise RulePlanError(str(e)) from e
    return validate_rule_plan(value, problem_id=problem_id)


def render_rule_executor_prompt(template: str, *, target: str, problem_id: str) -> str:
    return (
        template
        .replace("<<TARGET>>", target)
        .replace("<<PROBLEM_ID>>", problem_id)
        .replace("<<KNOWN_RULES>>", "\n".join(f"- `{name}`" for name in known_rule_names()))
        .replace("<<SUPPORTED_EXECUTOR_RULES>>", "\n".join(f"- `{name}`" for name in sorted(SUPPORTED_RULES)))
    )


def _arg(args: dict, keys: tuple[str, ...], label: str):
    for key in keys:
        if key in args:
            return key, args[key]
    raise ValueError(f"missing required arg {label} (accepted keys: {', '.join(keys)})")


def _sidewise(expr: Eq, rule: str, args: dict):
    key, raw = _arg(args, SIDEWISE_ARG_KEYS[rule], SIDEWISE_ARG_KEYS[rule][0])
    value = align_symbols_to(expr, parse_arg(raw))
    if rule == "add_constant_to_both_sides":
        lhs, rhs = expr.lhs + value, expr.rhs + value
    elif rule == "subtract_constant_from_both_sides":
        lhs, rhs = expr.lhs - value, expr.rhs - value
    elif rule == "multiply_both_sides":
        lhs, rhs = expr.lhs * value, expr.rhs * value
    else:
        lhs, rhs = expr.lhs / value, expr.rhs / value
    return Eq(lhs, rhs, evaluate=False), {key: raw}


def _symbolic(expr: Eq, rule: str, args: dict):
    if args:
        raise ValueError(f"{rule} takes empty rule_args")
    if rule == "simplify_expression":
        return Eq(sp.simplify(expr.lhs), sp.simplify(expr.rhs), evaluate=False)
    if rule == "expand_expression":
        return Eq(sp.expand(expr.lhs), sp.expand(expr.rhs), evaluate=False)
    if rule == "factor_expression":
        return Eq(sp.factor(expr.lhs), sp.factor(expr.rhs), evaluate=False)
    raise ValueError(f"unsupported symbolic rule {rule}")


def _positive_sqrt(expr: Eq, args: dict):
    if args.get("assume_nonnegative") is not True:
        raise ValueError("missing required arg assume_nonnegative=true")
    var = align_symbols_to(expr, parse_arg(args.get("var")))
    if not isinstance(var, sp.Symbol):
        raise ValueError("rule_args.var must parse to a Symbol")
    if expr_equal_zero(expr.lhs - var**2):
        radicand = expr.rhs
    elif expr_equal_zero(expr.rhs - var**2):
        radicand = expr.lhs
    else:
        raise ValueError("from expression must be Eq(var**2, radicand)")
    return Eq(var, sqrt(radicand), evaluate=False)


def _limit_args(limit: Limit):
    body, var, point = limit.args[0], limit.args[1], limit.args[2]
    direction = limit.args[3] if len(limit.args) > 3 else sp.Symbol("+")
    return body, var, point, direction


def _limit_side(expr: Eq) -> str:
    sides = [name for name in ("lhs", "rhs") if isinstance(getattr(expr, name), Limit)]
    if len(sides) != 1:
        raise ValueError("from expression must have exactly one Limit side")
    return sides[0]


def _limit_definition(expr: Eq, args: dict):
    if args:
        raise ValueError("limit_definition_of_derivative takes empty rule_args")
    derivs = sorted(expr.atoms(Derivative), key=sp.default_sort_key)
    if not derivs:
        raise ValueError("from expression contains no Derivative")
    deriv = derivs[0]
    if len(deriv.variables) != 1:
        raise ValueError("only one-variable derivatives are supported")
    var = deriv.variables[0]
    base = "h"
    used = {s.name for s in expr.free_symbols}
    h_name = base
    n = 1
    while h_name in used:
        h_name = f"h{n}"
        n += 1
    h = sp.Symbol(h_name)
    body = (deriv.expr.subs(var, var + h) - deriv.expr) / h
    limit = Limit(body, h, 0)
    return expr.xreplace({deriv: limit})


def _rewrite_limit(expr: Eq, args: dict, rule: str):
    side = _limit_side(expr)
    limit = getattr(expr, side)
    body, var, point, direction = _limit_args(limit)
    operation = args.get("operation")
    if not operation:
        if rule == "expand_within_limit":
            operation = "expand"
        elif rule == "cancel_within_limit":
            operation = "cancel"
        else:
            operation = "simplify"
    if operation == "expand":
        new_body = sp.expand(body)
    elif operation == "cancel":
        new_body = sp.cancel(body)
    elif operation == "together":
        new_body = sp.together(body)
    elif operation == "simplify":
        new_body = sp.simplify(body)
    else:
        raise ValueError(f"unsupported limit rewrite operation {operation!r}")
    new_limit = Limit(new_body, var, point, direction)
    return Eq(new_limit, expr.rhs, evaluate=False) if side == "lhs" else Eq(expr.lhs, new_limit, evaluate=False)


def _evaluate_limit(expr: Eq, args: dict):
    if args:
        raise ValueError("evaluate_limit takes empty rule_args")
    side = _limit_side(expr)
    limit = getattr(expr, side)
    value = limit.doit()
    if value.has(Limit):
        raise ValueError("limit did not evaluate")
    return Eq(value, expr.rhs, evaluate=False) if side == "lhs" else Eq(expr.lhs, value, evaluate=False)


def execute_rule(from_expr: Eq, rule: str, args: dict):
    if not isinstance(from_expr, Eq):
        raise ValueError("source ref must be Eq")
    args = args or {}
    if rule in SIDEWISE_ARG_KEYS:
        return _sidewise(from_expr, rule, args)
    if rule in ("substitute_value", "substitute_expression"):
        return expected_immediate_substitution(from_expr, args), args
    if rule == "swap_sides":
        if args:
            raise ValueError("swap_sides takes empty rule_args")
        return Eq(from_expr.rhs, from_expr.lhs, evaluate=False), args
    if rule in ("simplify_expression", "expand_expression", "factor_expression"):
        return _symbolic(from_expr, rule, args), args
    if rule == "take_positive_square_root":
        return _positive_sqrt(from_expr, args), args
    if rule in ("limit_definition_of_derivative", "apply_limit_definition_of_derivative"):
        return _limit_definition(from_expr, args), {}
    if rule in ("rewrite_within_limit", "expand_within_limit", "cancel_within_limit", "simplify_within_limit"):
        return _rewrite_limit(from_expr, args, rule), args
    if rule in ("evaluate_limit", "evaluate_limit_by_substitution", "take_limit"):
        return _evaluate_limit(from_expr, args), {}
    raise ValueError(f"unsupported executor rule {rule}")


def _node_id(i: int) -> str:
    return f"n{i}"


def _graph_rule(rule: str) -> str:
    aliases = {
        "apply_limit_definition_of_derivative": "limit_definition_of_derivative",
        "expand_within_limit": "rewrite_within_limit",
        "cancel_within_limit": "rewrite_within_limit",
        "simplify_within_limit": "rewrite_within_limit",
        "evaluate_limit_by_substitution": "evaluate_limit",
        "take_limit": "evaluate_limit",
    }
    return aliases.get(rule, rule)


def execute_plan(plan: dict[str, Any], *, problem_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = validate_rule_plan(plan, problem_id=problem_id)
    report = {
        "executor_version": EXECUTOR_VERSION,
        "problem_id": problem_id,
        "status": "PASS",
        "supported_rules": sorted(SUPPORTED_RULES),
        "step_results": [],
        "ref_to_node_id": {},
    }

    refs: dict[str, Any] = {}
    nodes: list[dict[str, str]] = []
    edges: list[dict[str, Any]] = []

    for fact in plan["facts"]:
        node_id = _node_id(len(nodes))
        expr = parse_srepr(fact["expr"])
        refs[fact["ref"]] = expr
        report["ref_to_node_id"][fact["ref"]] = node_id
        nodes.append({"id": node_id, "sympy_srepr": expr_to_srepr(expr)})

    for step in plan["steps"]:
        rule = step["rule"]
        result = {
            "id": step["id"],
            "from": step["from"],
            "rule": rule,
            "status": "ERROR",
        }
        if rule not in SUPPORTED_RULES:
            result["status"] = "COVERAGE_GAP"
            result["reason"] = f"unsupported executor rule {rule!r}"
            report["status"] = "COVERAGE_GAP"
            report["step_results"].append(result)
            raise RuleExecutorCoverageGap(result["reason"], "rule_executor_coverage_gap", report)
        try:
            from_expr = refs[step["from"]]
            to_expr, graph_args = execute_rule(from_expr, rule, step.get("rule_args") or {})
        except Exception as e:
            result["reason"] = f"{type(e).__name__}: {e}"
            report["status"] = "FAIL"
            report["step_results"].append(result)
            raise RuleExecutorExecutionError(result["reason"], "rule_executor_fail", report) from e

        node_id = _node_id(len(nodes))
        refs[step["id"]] = to_expr
        report["ref_to_node_id"][step["id"]] = node_id
        nodes.append({"id": node_id, "sympy_srepr": expr_to_srepr(to_expr)})
        edge = {
            "from": report["ref_to_node_id"][step["from"]],
            "to": node_id,
            "rule": _graph_rule(rule),
            "rule_args": graph_args or {},
        }
        edges.append(edge)
        result.update({
            "status": "PASS",
            "edge": edge,
            "from_sympy_srepr": expr_to_srepr(from_expr),
            "to_sympy_srepr": expr_to_srepr(to_expr),
        })
        report["step_results"].append(result)

    problem = {
        "id": problem_id,
        "root_node": report["ref_to_node_id"][plan["root_ref"]],
        "goal_node": report["ref_to_node_id"][plan["goal_ref"]],
        "nodes": nodes,
        "edges": edges,
    }
    return problem, report


def _safe_problem_id_from_path(path: Path) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_]", "_", path.stem)
    return stem or "rule_plan"


def main() -> int:
    import argparse
    import sys

    ap = argparse.ArgumentParser()
    ap.add_argument("plan_json")
    ap.add_argument("--problem-id", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    path = Path(args.plan_json)
    problem_id = args.problem_id or _safe_problem_id_from_path(path)
    try:
        plan = validate_rule_plan(json.loads(path.read_text()), problem_id=problem_id)
        problem, report = execute_plan(plan, problem_id=problem_id)
    except RulePlanError as e:
        print(f"rule plan invalid: {e}", file=sys.stderr)
        return 2
    except RuleExecutorError as e:
        print(json.dumps(e.report, indent=2), file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else path.with_suffix(".problem.json")
    out.write_text(json.dumps(problem, indent=2) + "\n")
    out.with_suffix(".rule_executor.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
