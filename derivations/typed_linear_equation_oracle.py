#!/usr/bin/env python3
"""Fail-closed oracle for typed one-solution linear-equation derivations.

The graph is model-authored; the contract and verifier sidecar are trusted
inputs.  Acceptance is derived only from the frozen typed givens, the graph's
equations, and the verifier evidence.  Model-authored result fields are not
part of the accepted graph schema.
"""
from __future__ import annotations

from collections import Counter, deque
from fractions import Fraction
from typing import Any

import sympy as sp

from sympy_eval import parse_srepr, strip_symbol_assumptions
from task_contract import TaskContractError, result_matches, validate_task_contract


EVALUATOR_VERSION = "typed_linear_equation_oracle.v1"
GATE_NAMES = ("contract", "graph_schema", "topology", "verifier", "root", "goal")
GRAPH_KEYS = {"id", "root_node", "goal_node", "nodes", "edges"}
NODE_KEYS = {"id", "sympy_srepr"}
EDGE_REQUIRED_KEYS = {"from", "to", "rule"}
EDGE_OPTIONAL_KEYS = {"rule_args"}
EDGE_SUMMARY_KEYS = {"PASS", "FAIL", "UNCOVERED", "WEAK_PASS", "ERROR"}


def _gate_record() -> dict[str, dict[str, Any]]:
    return {
        name: {"status": "NOT_RUN", "reasons": []}
        for name in GATE_NAMES
    }


def _identity(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def _finish(
    contract: Any,
    graph: Any,
    gates: dict[str, dict[str, Any]],
    gate: str,
    status: str,
    reasons: list[str],
    *,
    derived_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gates[gate] = {"status": status, "reasons": list(reasons)}
    payload: dict[str, Any] = {
        "evaluator_version": EVALUATOR_VERSION,
        "status": status,
        "task_id": _identity(contract, "id"),
        "graph_id": _identity(graph, "id"),
        "gates": gates,
        "reasons": [f"{gate}: {reason}" for reason in reasons],
    }
    if derived_result is not None:
        payload["derived_result"] = derived_result
    return payload


def _pass_gate(gates: dict[str, dict[str, Any]], gate: str) -> None:
    gates[gate] = {"status": "PASS", "reasons": []}


def _validate_contract(contract: Any) -> list[str]:
    try:
        validate_task_contract(contract)
    except TaskContractError as exc:
        return [str(exc)]
    if contract["task_type"] != "linear_equation":
        return ["task_type must be 'linear_equation'"]
    expected = contract["expected"]
    if expected.get("kind") != "solution_set" or expected.get("cardinality") != "one":
        return ["linear_equation contract must declare exactly one solution"]
    return []


def _validate_graph_schema(graph: Any) -> tuple[list[str], dict[str, dict[str, Any]] | None]:
    if not isinstance(graph, dict):
        return ["graph must be an object"], None
    reasons: list[str] = []
    if set(graph) != GRAPH_KEYS:
        reasons.append(
            f"graph keys must be {sorted(GRAPH_KEYS)}; got {sorted(graph)}"
        )
    for key in ("id", "root_node", "goal_node"):
        if not isinstance(graph.get(key), str) or not graph.get(key):
            reasons.append(f"graph.{key} must be a non-empty string")
    if graph.get("root_node") == graph.get("goal_node"):
        reasons.append("root_node must differ from goal_node")

    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        reasons.append("graph.nodes must be a non-empty list")
        nodes = []
    node_by_id: dict[str, dict[str, Any]] = {}
    for index, node in enumerate(nodes):
        path = f"graph.nodes[{index}]"
        if not isinstance(node, dict):
            reasons.append(f"{path} must be an object")
            continue
        if set(node) != NODE_KEYS:
            reasons.append(
                f"{path} keys must be {sorted(NODE_KEYS)}; got {sorted(node)}"
            )
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            reasons.append(f"{path}.id must be a non-empty string")
        elif node_id in node_by_id:
            reasons.append(f"duplicate node id: {node_id}")
        else:
            node_by_id[node_id] = node
        if not isinstance(node.get("sympy_srepr"), str) or not node.get("sympy_srepr"):
            reasons.append(f"{path}.sympy_srepr must be a non-empty string")

    for key in ("root_node", "goal_node"):
        value = graph.get(key)
        if isinstance(value, str) and value not in node_by_id:
            reasons.append(f"{key} {value!r} does not reference a node")

    edges = graph.get("edges")
    if not isinstance(edges, list) or not edges:
        reasons.append("graph.edges must contain at least one edge")
        edges = []
    seen_edges: set[tuple[str, str, str]] = set()
    for index, edge in enumerate(edges):
        path = f"graph.edges[{index}]"
        if not isinstance(edge, dict):
            reasons.append(f"{path} must be an object")
            continue
        keys = set(edge)
        if not EDGE_REQUIRED_KEYS.issubset(keys) or not keys.issubset(
            EDGE_REQUIRED_KEYS | EDGE_OPTIONAL_KEYS
        ):
            reasons.append(
                f"{path} keys must be {sorted(EDGE_REQUIRED_KEYS)} with optional "
                f"{sorted(EDGE_OPTIONAL_KEYS)}; got {sorted(keys)}"
            )
        for key in ("from", "to", "rule"):
            if not isinstance(edge.get(key), str) or not edge.get(key):
                reasons.append(f"{path}.{key} must be a non-empty string")
        if "rule_args" in edge and not isinstance(edge.get("rule_args"), dict):
            reasons.append(f"{path}.rule_args must be an object")
        source = edge.get("from")
        destination = edge.get("to")
        rule = edge.get("rule")
        if isinstance(source, str) and source not in node_by_id:
            reasons.append(f"{path}.from references unknown node {source!r}")
        if isinstance(destination, str) and destination not in node_by_id:
            reasons.append(f"{path}.to references unknown node {destination!r}")
        if all(isinstance(value, str) and value for value in (source, destination, rule)):
            identity = (source, destination, rule)
            if identity in seen_edges:
                reasons.append(f"duplicate edge: {source}->{destination} via {rule}")
            seen_edges.add(identity)

    return reasons, node_by_id


def _topology_reasons(graph: dict[str, Any], node_ids: set[str]) -> list[str]:
    adjacency = {node_id: [] for node_id in node_ids}
    reverse = {node_id: [] for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    for edge in graph["edges"]:
        source, destination = edge["from"], edge["to"]
        adjacency[source].append(destination)
        reverse[destination].append(source)
        indegree[destination] += 1

    pending = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    visited_count = 0
    while pending:
        node_id = pending.popleft()
        visited_count += 1
        for destination in adjacency[node_id]:
            indegree[destination] -= 1
            if indegree[destination] == 0:
                pending.append(destination)
    reasons: list[str] = []
    if visited_count != len(node_ids):
        reasons.append("graph must be acyclic")

    def reachable(start: str, edges: dict[str, list[str]]) -> set[str]:
        found: set[str] = set()
        stack = [start]
        while stack:
            node_id = stack.pop()
            if node_id in found:
                continue
            found.add(node_id)
            stack.extend(edges[node_id])
        return found

    from_root = reachable(graph["root_node"], adjacency)
    missing_from_root = sorted(node_ids - from_root)
    if missing_from_root:
        reasons.append(
            "all nodes must be reachable from root_node; unreachable: "
            + ", ".join(missing_from_root)
        )
    to_goal = reachable(graph["goal_node"], reverse)
    missing_to_goal = sorted(node_ids - to_goal)
    if missing_to_goal:
        reasons.append(
            "all nodes must be able to reach goal_node; dead ends: "
            + ", ".join(missing_to_goal)
        )
    return reasons


def _validate_verifier(
    verifier: Any,
    graph: dict[str, Any],
) -> tuple[str, list[str]]:
    if not isinstance(verifier, dict):
        return "ERROR", ["verifier sidecar must be an object"]
    structural: list[str] = []
    if verifier.get("problem_id") != graph["id"]:
        structural.append("verifier problem_id does not match graph id")
    if not isinstance(verifier.get("verifier_version"), str) or not verifier.get("verifier_version"):
        structural.append("verifier_version must be a non-empty string")
    for field, expected in (("n_nodes", len(graph["nodes"])), ("n_edges", len(graph["edges"]))):
        value = verifier.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value != expected:
            structural.append(f"verifier {field} must equal {expected}")
    parsed_nodes = verifier.get("parsed_nodes")
    if not isinstance(parsed_nodes, int) or isinstance(parsed_nodes, bool):
        structural.append("verifier parsed_nodes must be an integer")
    parse_errors = verifier.get("parse_errors")
    if not isinstance(parse_errors, list):
        structural.append("verifier parse_errors must be a list")

    summary = verifier.get("edge_summary")
    if not isinstance(summary, dict) or set(summary) != EDGE_SUMMARY_KEYS:
        structural.append(f"verifier edge_summary keys must be {sorted(EDGE_SUMMARY_KEYS)}")
    elif any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in summary.values()):
        structural.append("verifier edge_summary counts must be non-negative integers")

    edge_results = verifier.get("edge_results")
    normalized_results: list[tuple[str, str, str]] = []
    if not isinstance(edge_results, list) or len(edge_results) != len(graph["edges"]):
        structural.append("verifier edge_results must contain exactly one result per graph edge")
        edge_results = []
    for index, result in enumerate(edge_results):
        if not isinstance(result, dict):
            structural.append(f"verifier edge_results[{index}] must be an object")
            continue
        if not all(isinstance(result.get(key), str) for key in ("from", "to", "rule", "status")):
            structural.append(
                f"verifier edge_results[{index}] must contain string from/to/rule/status fields"
            )
            continue
        normalized_results.append((result["from"], result["to"], result["rule"]))

    graph_edges = Counter((edge["from"], edge["to"], edge["rule"]) for edge in graph["edges"])
    if normalized_results and Counter(normalized_results) != graph_edges:
        structural.append("verifier edge_results are not bound to the graph edges")
    if structural:
        return "ERROR", structural

    failures: list[str] = []
    if parsed_nodes != len(graph["nodes"]):
        failures.append("verifier did not parse every graph node")
    if parse_errors:
        failures.append("verifier reported node parse errors")
    nonpass = [
        f"{result['from']}->{result['to']} via {result['rule']}: {result['status']}"
        for result in edge_results
        if result["status"] != "PASS"
    ]
    if nonpass:
        failures.append("verifier reported non-PASS edges: " + "; ".join(nonpass))
    expected_summary = {key: 0 for key in EDGE_SUMMARY_KEYS}
    expected_summary["PASS"] = len(graph["edges"])
    if summary != expected_summary:
        failures.append("verifier edge_summary must report every edge as PASS")
    return ("FAIL", failures) if failures else ("PASS", [])


def _fraction(value: dict[str, Any]) -> Fraction:
    return Fraction(value["numerator"], value["denominator"])


def _parse_equation(node: dict[str, Any], label: str) -> tuple[sp.Equality | None, list[str]]:
    try:
        expression = strip_symbol_assumptions(parse_srepr(node["sympy_srepr"]))
    except Exception as exc:
        return None, [f"{label} sympy_srepr could not be parsed: {type(exc).__name__}: {exc}"]
    if not isinstance(expression, sp.Equality):
        return None, [f"{label} must be exactly one Eq(lhs, rhs)"]
    return expression, []


def _root_reasons(contract: dict[str, Any], root: sp.Equality) -> list[str]:
    givens = contract["givens"]
    lhs, rhs = givens["lhs"], givens["rhs"]
    variable = sp.Symbol(givens["variable"])
    expected = (
        sp.Rational(*_fraction(lhs["coefficient"]).as_integer_ratio()) * variable
        + sp.Rational(*_fraction(lhs["constant"]).as_integer_ratio())
        - sp.Rational(*_fraction(rhs["coefficient"]).as_integer_ratio()) * variable
        - sp.Rational(*_fraction(rhs["constant"]).as_integer_ratio())
    )
    residual = sp.expand(root.lhs - root.rhs)
    expected = sp.expand(expected)
    if sp.expand(residual - expected) != 0 and sp.expand(residual + expected) != 0:
        return ["root equation residual does not exactly match frozen givens up to sign"]
    return []


def _goal_result(goal: sp.Equality) -> tuple[dict[str, Any] | None, list[str]]:
    left, right = goal.lhs, goal.rhs
    if isinstance(left, sp.Symbol) and left.name == "x" and isinstance(right, sp.Rational):
        value = right
    elif isinstance(right, sp.Symbol) and right.name == "x" and isinstance(left, sp.Rational):
        value = left
    else:
        return None, ["goal must be exactly Eq(x, q) or Eq(q, x) for rational q"]
    return {
        "kind": "solution_set",
        "variable": "x",
        "cardinality": "one",
        "values": [{"numerator": int(value.p), "denominator": int(value.q)}],
    }, []


def evaluate_typed_linear_equation(
    contract: Any,
    graph: Any,
    verifier_sidecar: Any,
) -> dict[str, Any]:
    """Evaluate one model-authored graph against a trusted typed contract."""
    gates = _gate_record()

    reasons = _validate_contract(contract)
    if reasons:
        return _finish(contract, graph, gates, "contract", "ERROR", reasons)
    _pass_gate(gates, "contract")

    reasons, node_by_id = _validate_graph_schema(graph)
    if reasons or node_by_id is None:
        return _finish(contract, graph, gates, "graph_schema", "FAIL", reasons)
    _pass_gate(gates, "graph_schema")

    reasons = _topology_reasons(graph, set(node_by_id))
    if reasons:
        return _finish(contract, graph, gates, "topology", "FAIL", reasons)
    _pass_gate(gates, "topology")

    verifier_status, reasons = _validate_verifier(verifier_sidecar, graph)
    if reasons:
        return _finish(contract, graph, gates, "verifier", verifier_status, reasons)
    _pass_gate(gates, "verifier")

    root, reasons = _parse_equation(node_by_id[graph["root_node"]], "root_node")
    if reasons or root is None:
        return _finish(contract, graph, gates, "root", "FAIL", reasons)
    reasons = _root_reasons(contract, root)
    if reasons:
        return _finish(contract, graph, gates, "root", "FAIL", reasons)
    _pass_gate(gates, "root")

    goal, reasons = _parse_equation(node_by_id[graph["goal_node"]], "goal_node")
    if reasons or goal is None:
        return _finish(contract, graph, gates, "goal", "FAIL", reasons)
    derived_result, reasons = _goal_result(goal)
    if reasons or derived_result is None:
        return _finish(contract, graph, gates, "goal", "FAIL", reasons)
    if not result_matches(contract, derived_result):
        return _finish(
            contract,
            graph,
            gates,
            "goal",
            "FAIL",
            ["goal-derived typed solution does not match the trusted contract"],
            derived_result=derived_result,
        )
    _pass_gate(gates, "goal")

    return {
        "evaluator_version": EVALUATOR_VERSION,
        "status": "PASS",
        "task_id": contract["id"],
        "graph_id": graph["id"],
        "gates": gates,
        "reasons": [],
        "derived_result": derived_result,
    }


evaluate = evaluate_typed_linear_equation
