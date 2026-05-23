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

from sympy import Eq, Symbol, sqrt

from sympy_eval import align_symbols_to, expr_equal_zero, parse_arg


ROOT = Path(__file__).resolve().parent
RULE_LIBRARY = ROOT / "rule_library"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def load_contract_specs(base: Path = RULE_LIBRARY) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
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


CONTRACT_VALIDATORS = {
    "sidewise": validate_sidewise,
    "substitute": validate_substitute,
    "principal_sqrt": validate_principal_sqrt,
    "swap_sides": validate_swap_sides,
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
        if source in seen_sources:
            continue
        seen_sources.add(source)
        aliases = [a for a in spec.get("aliases", []) if isinstance(a, str)]
        alias_text = f" (aliases: {', '.join(f'`{a}`' for a in aliases)})" if aliases else ""
        args = spec.get("args_prompt") or "{}"
        safety = spec.get("safety") or ""
        line = f"- `{spec.get('rule_name', rule)}`{alias_text}: rule_args `{args}`"
        if safety:
            line += f"; {safety}"
        lines.append(line)
    return lines
