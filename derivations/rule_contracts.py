#!/usr/bin/env python3
"""Declarative rule contracts for the derivation verifier.

Python validators are still supported for special cases, but common edge
families should live here as data plus a small set of reusable contract kinds.
That keeps capability growth from becoming one file per observed failure mode.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import sympy as sp
from sympy import Derivative, Eq, Limit, Symbol, simplify, solve, sqrt

from sympy_eval import align_symbols_to, expr_equal_zero, parse_arg, strip_symbol_assumptions


ROOT = Path(__file__).resolve().parent
RULE_LIBRARY = ROOT / "rule_library"

BUILTIN_CONTRACT_SPECS: dict[str, dict[str, Any]] = {
    "simplify_expression": {
        "schema_version": "rule_contract.v1",
        "rule_name": "simplify_expression",
        "kind": "symbolic_equivalence",
        "args_prompt": "{}",
        "safety": "only for equivalence-preserving local rewrites; split side operations into their specific rules",
        "_source": "rule_contracts:builtin",
        "_rule_name": "simplify_expression",
    },
    "expand_expression": {
        "schema_version": "rule_contract.v1",
        "rule_name": "expand_expression",
        "kind": "symbolic_equivalence",
        "args_prompt": "{}",
        "safety": "only for equivalence-preserving local expansion rewrites",
        "_source": "rule_contracts:builtin",
        "_rule_name": "expand_expression",
    },
    "factor_expression": {
        "schema_version": "rule_contract.v1",
        "rule_name": "factor_expression",
        "kind": "symbolic_equivalence",
        "args_prompt": "{}",
        "safety": "only for equivalence-preserving local factorization rewrites",
        "_source": "rule_contracts:builtin",
        "_rule_name": "factor_expression",
    },
}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def load_contract_specs(base: Path = RULE_LIBRARY) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {name: dict(spec) for name, spec in BUILTIN_CONTRACT_SPECS.items()}
    if not base.exists():
        return specs
    for path in sorted(base.glob("*.json")):
        spec = _read_json(path)
        if not isinstance(spec, dict):
            continue
        names = [spec.get("rule_name"), *spec.get("aliases", [])]
        for name in names:
            if isinstance(name, str) and name:
                specs[name] = {**spec, "_source": str(path), "_rule_name": name}
    return specs


def _eq_zero(expr) -> bool:
    return expr_equal_zero(expr)


def _truth_preserves_eq(a: Eq, b: Eq) -> bool:
    try:
        da = simplify(a.lhs - a.rhs)
        db = simplify(b.lhs - b.rhs)
        if _eq_zero(da - db):
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


def _parse_symbol(value):
    if isinstance(value, Symbol):
        return value
    if isinstance(value, str):
        try:
            parsed = parse_arg(value)
            if isinstance(parsed, Symbol):
                return parsed
        except Exception:
            pass
        if value and all(ch.isalnum() or ch == "_" for ch in value) and not value[0].isdigit():
            return Symbol(value)
    return None


def _parse_substitution_pattern(value):
    if isinstance(value, str):
        try:
            return parse_arg(value)
        except Exception:
            if value and all(ch.isalnum() or ch == "_" for ch in value) and not value[0].isdigit():
                return Symbol(value)
            raise
    return parse_arg(value)


def _required_arg(args: dict, keys: list[str], label: str):
    for key in keys:
        if key in args:
            return key, args[key]
    return None, f"missing required arg {label} (accepted keys: {', '.join(keys)})"


def validate_sidewise(from_expr, to_expr, args: dict, spec: dict[str, Any]) -> tuple[str, str]:
    if not (isinstance(from_expr, Eq) and isinstance(to_expr, Eq)):
        return ("FAIL", "both endpoints must be Eq")
    if not isinstance(args, dict):
        return ("FAIL", "rule_args must be an object")
    arg_spec = spec.get("arg") or {}
    keys = [arg_spec.get("name"), *arg_spec.get("aliases", [])]
    keys = [k for k in keys if isinstance(k, str) and k]
    used_key, raw = _required_arg(args, keys, keys[0] if keys else "value")
    if used_key is None:
        return ("FAIL", raw)
    try:
        value = parse_arg(raw)
        value = align_symbols_to(from_expr, value)
    except Exception as e:
        return ("FAIL", f"could not parse rule_args.{used_key}: {e}")

    op = spec.get("operation")
    if op == "add":
        expected_lhs, expected_rhs = from_expr.lhs + value, from_expr.rhs + value
    elif op == "subtract":
        expected_lhs, expected_rhs = from_expr.lhs - value, from_expr.rhs - value
    elif op == "multiply":
        expected_lhs, expected_rhs = from_expr.lhs * value, from_expr.rhs * value
    elif op == "divide":
        expected_lhs, expected_rhs = from_expr.lhs / value, from_expr.rhs / value
    else:
        return ("FAIL", f"unknown sidewise operation: {op}")

    if _eq_zero(to_expr.lhs - expected_lhs) and _eq_zero(to_expr.rhs - expected_rhs):
        return ("PASS", f"{op} both sides by {value} (arg key '{used_key}')")
    return (
        "FAIL",
        f"{op} by {value} should give Eq({expected_lhs}, {expected_rhs}); "
        f"got Eq({to_expr.lhs}, {to_expr.rhs})",
    )


def validate_substitute(from_expr, to_expr, args: dict, spec: dict[str, Any]) -> tuple[str, str]:
    if not (isinstance(from_expr, Eq) and isinstance(to_expr, Eq)):
        return ("FAIL", "both endpoints must be Eq")
    if not isinstance(args, dict):
        return ("FAIL", "rule_args must be an object")
    if "symbol" not in args or "replacement" not in args:
        return ("FAIL", "missing required args: symbol, replacement")
    try:
        pattern = _parse_substitution_pattern(args["symbol"])
        replacement = parse_arg(args["replacement"])
        pattern = align_symbols_to(from_expr, pattern)
        replacement = align_symbols_to(from_expr, replacement)
    except Exception as e:
        return ("FAIL", f"could not parse substitution args: {e}")
    if pattern is None:
        return ("FAIL", "rule_args.symbol must be a symbol name, Symbol('name'), or SymPy expression")
    if not from_expr.has(pattern):
        return ("FAIL", f"substitution pattern {pattern} not present in from_expr")
    expected_lhs = from_expr.lhs.subs(pattern, replacement)
    expected_rhs = from_expr.rhs.subs(pattern, replacement)
    if expected_lhs == from_expr.lhs and expected_rhs == from_expr.rhs:
        return ("FAIL", "substitution made no change")
    if _eq_zero(to_expr.lhs - expected_lhs) and _eq_zero(to_expr.rhs - expected_rhs):
        return ("PASS", f"substituted {pattern} -> {replacement} with side orientation preserved")
    return ("FAIL", "to_expr is not exactly from_expr with the requested substitution")


def validate_principal_sqrt(from_expr, to_expr, args: dict, spec: dict[str, Any]) -> tuple[str, str]:
    if not (isinstance(from_expr, Eq) and isinstance(to_expr, Eq)):
        return ("FAIL", "both endpoints must be Eq")
    if not isinstance(args, dict):
        return ("FAIL", "rule_args must be an object")
    if args.get("assume_nonnegative") is not True:
        return ("FAIL", "missing required arg assume_nonnegative=true")
    try:
        var = _parse_symbol(args.get("var"))
        if var is not None:
            var = align_symbols_to(from_expr, var)
    except Exception as e:
        return ("FAIL", f"could not parse rule_args.var: {e}")
    if var is None:
        return ("FAIL", "missing/invalid rule_args.var symbol")

    radicand = None
    if _eq_zero(from_expr.lhs - var**2):
        radicand = from_expr.rhs
    elif _eq_zero(from_expr.rhs - var**2):
        radicand = from_expr.lhs
    else:
        return ("FAIL", "from_expr must be Eq(var**2, radicand) with either side orientation")

    expected_rhs = sqrt(radicand)
    if _eq_zero(to_expr.lhs - var) and _eq_zero(to_expr.rhs - expected_rhs):
        return ("PASS", "took principal square root with explicit nonnegative assumption")
    return ("FAIL", "to_expr must be Eq(var, sqrt(radicand)) preserving solved-variable orientation")


def validate_swap_sides(from_expr, to_expr, args: dict, spec: dict[str, Any]) -> tuple[str, str]:
    if not (isinstance(from_expr, Eq) and isinstance(to_expr, Eq)):
        return ("FAIL", "both endpoints must be Eq")
    if _eq_zero(to_expr.lhs - from_expr.rhs) and _eq_zero(to_expr.rhs - from_expr.lhs):
        return ("PASS", "swapped equation sides")
    return ("FAIL", "to_expr must be Eq(from_expr.rhs, from_expr.lhs)")


def validate_symbolic_equivalence(from_expr, to_expr, args: dict, spec: dict[str, Any]) -> tuple[str, str]:
    if not (isinstance(from_expr, Eq) and isinstance(to_expr, Eq)):
        return ("FAIL", "both endpoints must be Eq")
    if not isinstance(args, dict):
        return ("FAIL", "rule_args must be an object")
    if args:
        return ("FAIL", "rule_args must be empty for symbolic equivalence rules")
    if _truth_preserves_eq(from_expr, to_expr):
        return ("PASS", f"{spec.get('rule_name', 'rule')} proof obligation discharged by symbolic equivalence")
    return ("FAIL", "symbolic equivalence proof obligation failed")


def _unique_limit_side(eq: Eq) -> str | None:
    sides = [name for name in ("lhs", "rhs") if isinstance(getattr(eq, name), Limit)]
    return sides[0] if len(sides) == 1 else None


def _limit_args(limit: Limit):
    body, var, point = limit.args[0], limit.args[1], limit.args[2]
    direction = limit.args[3] if len(limit.args) > 3 else Symbol("+")
    return body, var, point, direction


def validate_limit_definition(from_expr, to_expr, args: dict, spec: dict[str, Any]) -> tuple[str, str]:
    """to_expr must be from_expr with one Derivative replaced by its literal
    difference quotient: Limit((f(var+h) - f(var))/h, h, 0) with a fresh h.

    The body comparison is structural on purpose: a pre-simplified quotient
    (e.g. 2*x + h) is algebraically equal but skips the rewrite steps this
    rule exists to make visible, so it must arrive via rewrite edges instead.
    """
    if not (isinstance(from_expr, Eq) and isinstance(to_expr, Eq)):
        return ("FAIL", "both endpoints must be Eq")
    derivs = sorted(from_expr.atoms(Derivative), key=sp.default_sort_key)
    if not derivs:
        return ("FAIL", "from_expr contains no unevaluated Derivative")
    new_limits = [lim for lim in to_expr.atoms(Limit) if lim not in from_expr.atoms(Limit)]
    if len(new_limits) != 1:
        return ("FAIL", "to_expr must introduce exactly one new Limit")
    limit = new_limits[0]
    body, lvar, point, _direction = _limit_args(limit)
    if point != 0:
        return ("FAIL", "difference-quotient limit must approach 0")
    if not isinstance(lvar, Symbol):
        return ("FAIL", "limit variable must be a Symbol")
    if from_expr.has(lvar):
        return ("FAIL", f"limit variable {lvar} must be fresh (it already appears in from_expr)")
    stripped_body = strip_symbol_assumptions(body)
    for deriv in derivs:
        if len(deriv.variables) != 1:
            continue
        var = deriv.variables[0]
        e = deriv.expr
        expected_body = (e.subs(var, var + lvar) - e) / lvar
        expected_body = strip_symbol_assumptions(expected_body)
        if stripped_body != expected_body and strip_symbol_assumptions(sp.together(body)) != expected_body:
            continue
        expected = strip_symbol_assumptions(from_expr.xreplace({deriv: limit}))
        if expected == strip_symbol_assumptions(to_expr):
            return ("PASS", f"replaced {deriv} by its literal difference quotient in {lvar} -> 0")
    return (
        "FAIL",
        "to_expr must be from_expr with one Derivative replaced by the literal "
        "difference quotient Limit((f(var+h) - f(var))/h, h, 0); do not pre-expand or pre-cancel",
    )


def validate_limit_rewrite(from_expr, to_expr, args: dict, spec: dict[str, Any]) -> tuple[str, str]:
    """Rewrite only the body of a Limit; variable, point, direction, and the
    other equation side must stay fixed. Bodies must be equal as symbolic
    expressions (equality on a punctured neighborhood, so removable points
    such as cancelling h from (2*x*h + h**2)/h are allowed)."""
    if not (isinstance(from_expr, Eq) and isinstance(to_expr, Eq)):
        return ("FAIL", "both endpoints must be Eq")
    side = _unique_limit_side(from_expr)
    if side is None:
        return ("FAIL", "from_expr must have exactly one side that is an unevaluated Limit")
    other = "rhs" if side == "lhs" else "lhs"
    to_side = getattr(to_expr, side)
    if not isinstance(to_side, Limit):
        return ("FAIL", f"the {side} of to_expr must remain an unevaluated Limit")
    if not _eq_zero(getattr(to_expr, other) - getattr(from_expr, other)):
        return ("FAIL", "the non-limit side must stay unchanged")
    f_body, f_var, f_point, f_dir = _limit_args(getattr(from_expr, side))
    t_body, t_var, t_point, t_dir = _limit_args(to_side)
    if strip_symbol_assumptions(t_var) != strip_symbol_assumptions(f_var):
        return ("FAIL", "limit variable must stay unchanged")
    if not _eq_zero(t_point - f_point):
        return ("FAIL", "limit point must stay unchanged")
    if str(t_dir) != str(f_dir):
        return ("FAIL", "limit direction must stay unchanged")
    if strip_symbol_assumptions(f_body) == strip_symbol_assumptions(t_body):
        return ("FAIL", "rewrite made no change")
    if _eq_zero(f_body - t_body):
        return ("PASS", "limit bodies are equal on a punctured neighborhood of the limit point")
    return ("FAIL", "limit bodies are not symbolically equal")


def validate_limit_evaluate(from_expr, to_expr, args: dict, spec: dict[str, Any]) -> tuple[str, str]:
    """Evaluate a Limit by direct substitution. Only valid when the body is
    continuous at the point: the substitution must be defined and must agree
    with the computed limit. A 0/0 form fails -- cancel inside the limit first."""
    if not (isinstance(from_expr, Eq) and isinstance(to_expr, Eq)):
        return ("FAIL", "both endpoints must be Eq")
    side = _unique_limit_side(from_expr)
    if side is None:
        return ("FAIL", "from_expr must have exactly one side that is an unevaluated Limit")
    other = "rhs" if side == "lhs" else "lhs"
    if not _eq_zero(getattr(to_expr, other) - getattr(from_expr, other)):
        return ("FAIL", "the non-limit side must stay unchanged")
    to_side = getattr(to_expr, side)
    if to_side.has(Limit):
        return ("FAIL", f"the {side} of to_expr must be the evaluated limit, not another Limit")
    limit = getattr(from_expr, side)
    body, var, point, _direction = _limit_args(limit)
    try:
        substituted = body.subs(var, point)
    except Exception as e:
        return ("FAIL", f"could not substitute the limit point: {type(e).__name__}: {e}")
    if substituted.has(sp.nan, sp.zoo, sp.oo, sp.S.NegativeInfinity):
        return (
            "FAIL",
            "body is not continuous at the limit point (substitution is undefined); "
            "rewrite/cancel inside the limit first",
        )
    try:
        computed = limit.doit()
    except Exception as e:
        return ("FAIL", f"could not certify the limit value: {type(e).__name__}: {e}")
    if computed.has(Limit):
        return ("FAIL", "could not certify the limit value (limit did not evaluate)")
    if not _eq_zero(computed - substituted):
        return ("FAIL", "direct substitution does not agree with the limit; the body is not continuous at the point")
    if _eq_zero(to_side - substituted):
        return ("PASS", f"evaluated limit by substitution at {var} = {point} (continuity certified)")
    return ("FAIL", f"to_expr's {side} must equal the limit value {substituted}")


CONTRACT_VALIDATORS = {
    "sidewise": validate_sidewise,
    "substitute": validate_substitute,
    "principal_sqrt": validate_principal_sqrt,
    "swap_sides": validate_swap_sides,
    "symbolic_equivalence": validate_symbolic_equivalence,
    "limit_definition": validate_limit_definition,
    "limit_rewrite": validate_limit_rewrite,
    "limit_evaluate": validate_limit_evaluate,
}


def build_contract_validators(specs: dict[str, dict[str, Any]] | None = None) -> tuple[dict, dict]:
    specs = specs or load_contract_specs()
    validators: dict = {}
    sources: dict = {}
    for rule, spec in specs.items():
        kind = spec.get("kind")
        fn = CONTRACT_VALIDATORS.get(kind)
        if not fn:
            continue

        def _make_validator(local_fn, local_spec):
            def _validate(from_expr, to_expr, args):
                try:
                    return local_fn(from_expr, to_expr, args or {}, local_spec)
                except Exception as e:
                    return ("FAIL", f"contract validator raised: {type(e).__name__}: {e}")
            return _validate

        validators[rule] = _make_validator(fn, spec)
        sources[rule] = spec.get("_source", "rule_contracts")
    return validators, sources


def known_rule_names() -> list[str]:
    return sorted(load_contract_specs())


def prompt_contract_lines() -> list[str]:
    lines = []
    seen_sources = set()
    for rule, spec in sorted(load_contract_specs().items()):
        source = spec.get("_source")
        source_key = f"{source}:{rule}" if source == "rule_contracts:builtin" else source
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        aliases = [a for a in spec.get("aliases", []) if isinstance(a, str)]
        alias_text = f" (aliases: {', '.join(f'`{a}`' for a in aliases)})" if aliases else ""
        args = spec.get("args_prompt") or "{}"
        safety = spec.get("safety") or ""
        line = f"- `{spec.get('rule_name', rule)}`{alias_text}: rule_args `{args}`"
        if safety:
            line += f"; {safety}"
        lines.append(line)
    return lines
