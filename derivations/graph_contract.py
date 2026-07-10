#!/usr/bin/env python3
"""Deterministic structural contract for derivation graphs.

This module deliberately does not interpret free-form target text. It validates
the graph topology shared by every task type so mathematical and pedagogical
evaluators can rely on the same root and goal endpoint.
"""
from __future__ import annotations

from collections import Counter
from typing import Any


def analyze_graph_shape(problem: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic topology facts without mutating ``problem``."""
    raw_nodes = problem.get("nodes")
    raw_edges = problem.get("edges")
    nodes = raw_nodes if isinstance(raw_nodes, list) else []
    edges = raw_edges if isinstance(raw_edges, list) else []

    node_ids = [
        node.get("id")
        for node in nodes
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    ]
    node_counts = Counter(node_ids)
    node_set = set(node_ids)
    duplicate_node_ids = sorted(node_id for node_id, count in node_counts.items() if count > 1)

    root = problem.get("root_node")
    goal = problem.get("goal_node")
    outgoing: dict[str, list[str]] = {}
    incoming: dict[str, int] = {}
    unknown_edge_endpoints: list[dict[str, Any]] = []

    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            unknown_edge_endpoints.append({"edge_index": index, "from": None, "to": None})
            continue
        source = edge.get("from")
        destination = edge.get("to")
        if not isinstance(source, str) or not isinstance(destination, str):
            unknown_edge_endpoints.append(
                {"edge_index": index, "from": source, "to": destination}
            )
            continue
        if source not in node_set or destination not in node_set:
            unknown_edge_endpoints.append(
                {"edge_index": index, "from": source, "to": destination}
            )
        if source in node_set:
            outgoing.setdefault(source, []).append(destination)
        if destination in node_set:
            incoming[destination] = incoming.get(destination, 0) + 1

    reachable: set[str] = set()
    if isinstance(root, str) and root in node_set:
        stack = [root]
        while stack:
            node_id = stack.pop()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            stack.extend(
                destination
                for destination in outgoing.get(node_id, [])
                if destination in node_set
            )

    terminal_nodes = sorted(node_id for node_id in node_set if not outgoing.get(node_id))
    disconnected_nonroot_nodes = sorted(
        node_id
        for node_id in node_set
        if node_id != root and incoming.get(node_id, 0) == 0
    )

    return {
        "root_node": root,
        "goal_node": goal,
        "node_ids": sorted(node_set),
        "duplicate_node_ids": duplicate_node_ids,
        "root_exists": isinstance(root, str) and root in node_set,
        "goal_exists": isinstance(goal, str) and goal in node_set,
        "terminal_nodes": terminal_nodes,
        "reachable_nodes": sorted(reachable),
        "goal_is_terminal": isinstance(goal, str) and goal in terminal_nodes,
        "goal_reachable_from_root": isinstance(goal, str) and goal in reachable,
        "disconnected_nonroot_nodes": disconnected_nonroot_nodes,
        "unknown_edge_endpoints": unknown_edge_endpoints,
    }


def validate_graph_shape(problem: dict[str, Any]) -> list[str]:
    """Return stable, human-readable structural contract violations."""
    shape = analyze_graph_shape(problem)
    violations: list[str] = []
    if shape["duplicate_node_ids"]:
        violations.append(
            "duplicate node ids: " + ", ".join(shape["duplicate_node_ids"])
        )
    if not shape["root_exists"]:
        violations.append(f"root_node {shape['root_node']!r} is unknown")
    if not shape["goal_exists"]:
        violations.append(f"goal_node {shape['goal_node']!r} is unknown")
    if shape["unknown_edge_endpoints"]:
        violations.append("one or more edges reference unknown endpoints")
    if shape["goal_exists"] and not shape["goal_reachable_from_root"]:
        violations.append("goal_node is not reachable from root_node")
    if shape["goal_exists"] and not shape["goal_is_terminal"]:
        violations.append("goal_node is not terminal")
    return violations

