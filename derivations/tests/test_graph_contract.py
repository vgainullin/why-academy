from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

from graph_contract import analyze_graph_shape, validate_graph_shape  # noqa: E402


def _problem(*, goal: str = "n1", edges: list[dict] | None = None) -> dict:
    return {
        "id": "typed_contract_linear",
        "root_node": "n0",
        "goal_node": goal,
        "nodes": [
            {"id": "n0", "sympy_srepr": "Eq(x + 2, 5)"},
            {"id": "n1", "sympy_srepr": "Eq(x, 3)"},
        ],
        "edges": edges if edges is not None else [
            {
                "from": "n0",
                "to": "n1",
                "rule": "subtract_constant_from_both_sides",
                "rule_args": {"constant": 2},
            }
        ],
    }


class GraphContractTests(unittest.TestCase):
    def test_valid_graph_has_one_reachable_terminal_goal(self) -> None:
        shape = analyze_graph_shape(_problem())

        self.assertEqual([], validate_graph_shape(_problem()))
        self.assertEqual(["n1"], shape["terminal_nodes"])
        self.assertTrue(shape["goal_reachable_from_root"])
        self.assertTrue(shape["goal_is_terminal"])

    def test_nonterminal_goal_is_rejected(self) -> None:
        violations = validate_graph_shape(_problem(goal="n0"))

        self.assertIn("goal_node is not terminal", violations)

    def test_unreachable_goal_is_rejected(self) -> None:
        violations = validate_graph_shape(_problem(edges=[]))

        self.assertIn("goal_node is not reachable from root_node", violations)

    def test_unknown_edge_endpoint_is_rejected(self) -> None:
        problem = _problem(edges=[{"from": "n404", "to": "n1", "rule": "unknown"}])

        self.assertIn(
            "one or more edges reference unknown endpoints",
            validate_graph_shape(problem),
        )

    def test_duplicate_node_ids_are_rejected(self) -> None:
        problem = _problem()
        problem["nodes"].append({"id": "n1", "sympy_srepr": "Eq(x, 4)"})

        self.assertIn("duplicate node ids: n1", validate_graph_shape(problem))


if __name__ == "__main__":
    unittest.main()
