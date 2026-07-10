from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import algebra_linear_practice as alp  # noqa: E402
from task_contract import evaluate_submission  # noqa: E402


def _contract() -> dict:
    corpus = alp.build_corpus(total=12, set_size=12)
    return next(task for task in corpus["tasks"] if task["task_type"] == "linear_equation")


def _graph(contract: dict, *, goal: str = "n1", result: dict | None = None,
           edges: list[dict] | None = None) -> dict:
    return {
        "id": "typed_acceptance_linear",
        "root_node": "n0",
        "goal_node": goal,
        "nodes": [
            {"id": "n0", "kind": "given"},
            {
                "id": "n1",
                "kind": "result",
                "result": copy.deepcopy(result if result is not None else contract["expected"]),
            },
        ],
        "edges": edges if edges is not None else [
            {"from": "n0", "to": "n1", "rule": "solve_linear_equation"}
        ],
    }


class TypedAcceptanceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = _contract()
        self.digest = self.contract["contract_digest"]

    def evaluate(self, graph: dict) -> dict:
        return evaluate_submission(self.contract, graph, self.digest)

    def test_exact_result_at_reachable_terminal_goal_passes(self) -> None:
        payload = self.evaluate(_graph(self.contract))

        self.assertEqual("PASS", payload["status"])
        self.assertEqual("n1", payload["goal_node"])
        self.assertEqual(self.digest, payload["contract_digest"])

    def test_matching_result_at_nonterminal_goal_fails(self) -> None:
        graph = _graph(self.contract, goal="n0")
        graph["nodes"][0]["result"] = copy.deepcopy(self.contract["expected"])

        payload = self.evaluate(graph)

        self.assertEqual("FAIL", payload["status"])
        self.assertIn("goal_node is not terminal", payload["reasons"])

    def test_matching_result_at_unreachable_goal_fails(self) -> None:
        payload = self.evaluate(_graph(self.contract, edges=[]))

        self.assertEqual("FAIL", payload["status"])
        self.assertIn("goal_node is not reachable from root_node", payload["reasons"])

    def test_unknown_edge_endpoint_fails(self) -> None:
        graph = _graph(
            self.contract,
            edges=[{"from": "n404", "to": "n1", "rule": "solve_linear_equation"}],
        )

        payload = self.evaluate(graph)

        self.assertEqual("FAIL", payload["status"])
        self.assertIn("one or more edges reference unknown endpoints", payload["reasons"])

    def test_terminal_goal_without_typed_result_fails(self) -> None:
        graph = _graph(self.contract)
        del graph["nodes"][1]["result"]

        payload = self.evaluate(graph)

        self.assertEqual("FAIL", payload["status"])
        self.assertIn("terminal goal_node has no typed result", payload["reasons"])

    def test_wrong_typed_result_fails(self) -> None:
        wrong = copy.deepcopy(self.contract["expected"])
        wrong["values"][0]["numerator"] += 1

        payload = self.evaluate(_graph(self.contract, result=wrong))

        self.assertEqual("FAIL", payload["status"])
        self.assertIn("terminal goal result does not match expected result", payload["reasons"])

    def test_missing_trusted_digest_fails_closed_without_skip(self) -> None:
        payload = evaluate_submission(self.contract, _graph(self.contract), None)

        self.assertEqual("ERROR", payload["status"])
        self.assertNotEqual("SKIP", payload["status"])


if __name__ == "__main__":
    unittest.main()
