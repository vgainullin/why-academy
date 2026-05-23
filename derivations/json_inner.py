#!/usr/bin/env python3
"""JSON-only inner generation helpers.

This path keeps the model away from filesystem writes and verification. The
model emits only a problem JSON object; the wrapper writes it, verifies it, and
records failures in the normal evolution artifacts.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rule_contracts import known_rule_names as contract_rule_names
from rule_contracts import prompt_contract_lines


ROOT = Path(__file__).resolve().parent
PROMPT = ROOT / "prompts" / "generate_derivation_json.md"

COMMON_RULES = [
    "add_constant_to_both_sides",
    "subtract_constant_from_both_sides",
    "divide_both_sides",
    "multiply_both_sides",
    "substitute_expression",
    "substitute_value",
    "swap_sides",
    "simplify_expression",
    "expand_expression",
    "factor_expression",
    "take_positive_square_root",
]

PROBLEM_KEYS = {"id", "root_node", "goal_node", "nodes", "edges"}
NODE_KEYS = {"id", "sympy_srepr"}
EDGE_KEYS = {"from", "to", "rule", "rule_args"}


class ProblemJsonError(ValueError):
    pass


def known_rule_names() -> list[str]:
    names = set(COMMON_RULES)
    names.update(contract_rule_names())
    for path in (ROOT / "validators").glob("*.py"):
        if not path.name.startswith("_"):
            names.add(path.stem)
    for path in (ROOT / "rule_library").glob("**/*.json"):
        names.add(path.stem)
    return sorted(names)


def extract_addenda(text: str) -> str:
    """Return learned addenda from a prior prompt variant, if any."""
    idx = text.find("\n## Addendum")
    if idx < 0:
        idx = text.find("## Addendum")
    if idx < 0:
        return ""
    return text[idx:].strip()


def addendum_blocks(text: str) -> list[str]:
    addenda = extract_addenda(text)
    if not addenda:
        return []
    return [p.strip() for p in re.split(r"(?=^## Addendum)", addenda, flags=re.MULTILINE) if p.strip()]


def append_addenda_unique(base_text: str, addenda_text: str) -> str:
    out = base_text.rstrip()
    for block in addendum_blocks(addenda_text):
        if block not in out:
            out += "\n\n" + block
    return out.rstrip() + "\n"


def adapt_seed_variant(canonical_template: str, seed_text: str) -> str:
    return append_addenda_unique(canonical_template, seed_text)


def render_json_prompt(template: str, *, target: str, problem_id: str) -> str:
    return (
        template
        .replace("<<TARGET>>", target)
        .replace("<<PROBLEM_ID>>", problem_id)
        .replace("<<KNOWN_RULES>>", "\n".join(f"- `{name}`" for name in known_rule_names()))
        .replace("<<RULE_CONTRACTS>>", "\n".join(prompt_contract_lines()))
    )


def _strip_fence(text: str) -> str:
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract a single JSON object from a model response."""
    s = _strip_fence(text)
    try:
        value = json.loads(s)
    except json.JSONDecodeError:
        start = s.find("{")
        end = s.rfind("}")
        if start < 0 or end <= start:
            raise ProblemJsonError("response did not contain a JSON object")
        try:
            value = json.loads(s[start:end + 1])
        except json.JSONDecodeError as e:
            raise ProblemJsonError(f"invalid JSON: {e}") from e
    if isinstance(value, dict) and isinstance(value.get("problem"), dict):
        value = value["problem"]
    if not isinstance(value, dict):
        raise ProblemJsonError("top-level response was not a JSON object")
    return value


def validate_problem(problem: dict[str, Any], *, problem_id: str) -> dict[str, Any]:
    """Validate the graph schema enough to safely hand it to verify.py."""
    extra = set(problem) - PROBLEM_KEYS
    if extra:
        raise ProblemJsonError(f"unexpected top-level keys: {sorted(extra)}")
    missing = PROBLEM_KEYS - set(problem)
    if missing:
        raise ProblemJsonError(f"missing top-level keys: {sorted(missing)}")
    if problem.get("id") != problem_id:
        raise ProblemJsonError(f"id must be {problem_id!r}, got {problem.get('id')!r}")
    if not isinstance(problem.get("root_node"), str):
        raise ProblemJsonError("root_node must be a string")
    if not isinstance(problem.get("goal_node"), str):
        raise ProblemJsonError("goal_node must be a string")

    nodes = problem.get("nodes")
    edges = problem.get("edges")
    if not isinstance(nodes, list) or not nodes:
        raise ProblemJsonError("nodes must be a non-empty list")
    if not isinstance(edges, list):
        raise ProblemJsonError("edges must be a list")

    node_ids: set[str] = set()
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise ProblemJsonError(f"nodes[{i}] must be an object")
        extra = set(node) - NODE_KEYS
        missing = NODE_KEYS - set(node)
        if extra or missing:
            raise ProblemJsonError(f"nodes[{i}] keys invalid: extra={sorted(extra)} missing={sorted(missing)}")
        if not isinstance(node["id"], str) or not node["id"]:
            raise ProblemJsonError(f"nodes[{i}].id must be a non-empty string")
        if node["id"] in node_ids:
            raise ProblemJsonError(f"duplicate node id: {node['id']}")
        if not isinstance(node["sympy_srepr"], str) or not node["sympy_srepr"].strip():
            raise ProblemJsonError(f"nodes[{i}].sympy_srepr must be a non-empty string")
        node_ids.add(node["id"])

    if problem["root_node"] not in node_ids:
        raise ProblemJsonError("root_node does not reference a node id")
    if problem["goal_node"] not in node_ids:
        raise ProblemJsonError("goal_node does not reference a node id")

    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise ProblemJsonError(f"edges[{i}] must be an object")
        extra = set(edge) - EDGE_KEYS
        required = {"from", "to", "rule"}
        missing = required - set(edge)
        if extra or missing:
            raise ProblemJsonError(f"edges[{i}] keys invalid: extra={sorted(extra)} missing={sorted(missing)}")
        if edge["from"] not in node_ids or edge["to"] not in node_ids:
            raise ProblemJsonError(f"edges[{i}] endpoint does not reference node ids")
        if not isinstance(edge["rule"], str) or not edge["rule"].strip():
            raise ProblemJsonError(f"edges[{i}].rule must be a non-empty string")
        if "rule_args" in edge and not isinstance(edge["rule_args"], dict):
            raise ProblemJsonError(f"edges[{i}].rule_args must be an object when present")
    return problem


def problem_from_response(text: str, *, problem_id: str) -> dict[str, Any]:
    return validate_problem(extract_json_object(text), problem_id=problem_id)
