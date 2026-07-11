from __future__ import annotations

import copy
import sys
import unittest
from collections import Counter
from fractions import Fraction
from pathlib import Path

import sympy as sp


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import algebra_linear_practice as alp  # noqa: E402
from typed_linear_equation_oracle import (  # noqa: E402
    EVALUATOR_VERSION,
    evaluate_typed_linear_equation,
)


def _fraction(value: dict[str, int]) -> Fraction:
    return Fraction(value["numerator"], value["denominator"])


def _rational(value: Fraction) -> sp.Rational:
    return sp.Rational(value.numerator, value.denominator)


class TypedLinearEquationOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        corpus = alp.build_corpus(total=12, set_size=12)
        cls.contract = next(
            task
            for task in corpus["tasks"]
            if task["task_type"] == "linear_equation"
            and task["expected"]["cardinality"] == "one"
        )
        cls.non_one_contract = next(
            task
            for task in corpus["tasks"]
            if task["task_type"] == "linear_equation"
            and task["expected"]["cardinality"] != "one"
        )

    def graph(self, *, swapped_root: bool = False, swapped_goal: bool = False) -> dict:
        givens = self.contract["givens"]
        lhs = givens["lhs"]
        rhs = givens["rhs"]
        x = sp.Symbol("x", real=True)
        lhs_expr = _rational(_fraction(lhs["coefficient"])) * x + _rational(_fraction(lhs["constant"]))
        rhs_expr = _rational(_fraction(rhs["coefficient"])) * x + _rational(_fraction(rhs["constant"]))
        root = sp.Eq(rhs_expr, lhs_expr, evaluate=False) if swapped_root else sp.Eq(lhs_expr, rhs_expr, evaluate=False)
        value = _fraction(self.contract["expected"]["values"][0])
        q = _rational(value)
        goal = sp.Eq(q, x, evaluate=False) if swapped_goal else sp.Eq(x, q, evaluate=False)
        return {
            "id": "typed_linear_equation_graph",
            "root_node": "n0",
            "goal_node": "n1",
            "nodes": [
                {"id": "n0", "sympy_srepr": sp.srepr(root)},
                {"id": "n1", "sympy_srepr": sp.srepr(goal)},
            ],
            "edges": [
                {
                    "from": "n0",
                    "to": "n1",
                    "rule": "solve_linear_equation",
                    "rule_args": {},
                }
            ],
        }

    def verifier(self, graph: dict, *, statuses: list[str] | None = None) -> dict:
        statuses = statuses or ["PASS"] * len(graph["edges"])
        edge_results = [
            {
                "from": edge["from"],
                "to": edge["to"],
                "rule": edge["rule"],
                "status": status,
                "reason": "test evidence",
            }
            for edge, status in zip(graph["edges"], statuses)
        ]
        counts = Counter(statuses)
        return {
            "problem_id": graph["id"],
            "verifier_version": "test.v1",
            "n_nodes": len(graph["nodes"]),
            "n_edges": len(graph["edges"]),
            "parsed_nodes": len(graph["nodes"]),
            "parse_errors": [],
            "edge_results": edge_results,
            "edge_summary": {
                "PASS": counts["PASS"],
                "FAIL": counts["FAIL"],
                "UNCOVERED": counts["UNCOVERED"],
                "WEAK_PASS": counts["WEAK_PASS"],
                "ERROR": counts["ERROR"],
            },
        }

    def evaluate(self, graph: dict, verifier: dict | None = None, contract: dict | None = None) -> dict:
        return evaluate_typed_linear_equation(
            contract or self.contract,
            graph,
            verifier or self.verifier(graph),
        )

    def assert_reason(self, payload: dict, text: str) -> None:
        self.assertTrue(
            any(text in reason for reason in payload["reasons"]),
            msg=f"{text!r} not found in {payload['reasons']!r}",
        )

    def test_valid_graph_passes_and_derives_result_from_goal(self) -> None:
        graph = self.graph()

        payload = self.evaluate(graph)

        self.assertEqual("PASS", payload["status"])
        self.assertEqual(EVALUATOR_VERSION, payload["evaluator_version"])
        self.assertEqual(self.contract["expected"], payload["derived_result"])
        self.assertTrue(all(gate["status"] == "PASS" for gate in payload["gates"].values()))
        self.assertNotIn("result", graph["nodes"][1])

    def test_swapped_root_and_goal_orientations_pass(self) -> None:
        graph = self.graph(swapped_root=True, swapped_goal=True)

        self.assertEqual("PASS", self.evaluate(graph)["status"])

    def test_contract_must_be_valid_one_solution_linear_equation(self) -> None:
        graph = self.graph()
        payload = self.evaluate(graph, contract=self.non_one_contract)

        self.assertEqual("ERROR", payload["status"])
        self.assertEqual("ERROR", payload["gates"]["contract"]["status"])
        self.assert_reason(payload, "exactly one solution")

    def test_model_authored_result_is_rejected_by_exact_schema(self) -> None:
        graph = self.graph()
        graph["nodes"][1]["result"] = copy.deepcopy(self.contract["expected"])

        payload = self.evaluate(graph)

        self.assertEqual("FAIL", payload["status"])
        self.assert_reason(payload, "graph.nodes[1] keys")

    def test_root_must_differ_from_goal_and_graph_needs_an_edge(self) -> None:
        graph = self.graph()
        graph["goal_node"] = graph["root_node"]
        graph["edges"] = []

        payload = self.evaluate(graph, verifier=self.verifier(graph))

        self.assertEqual("FAIL", payload["status"])
        self.assert_reason(payload, "root_node must differ")
        self.assert_reason(payload, "at least one edge")

    def test_graph_must_be_a_dag(self) -> None:
        graph = self.graph()
        graph["edges"].append({"from": "n1", "to": "n0", "rule": "cycle"})

        payload = self.evaluate(graph, verifier=self.verifier(graph))

        self.assertEqual("FAIL", payload["status"])
        self.assert_reason(payload, "acyclic")

    def test_every_node_must_be_reachable_from_root_and_reach_goal(self) -> None:
        graph = self.graph()
        graph["nodes"].append({"id": "n2", "sympy_srepr": "Eq(x, 99)"})
        graph["edges"].append({"from": "n0", "to": "n2", "rule": "dead_end"})

        payload = self.evaluate(graph, verifier=self.verifier(graph))

        self.assertEqual("FAIL", payload["status"])
        self.assert_reason(payload, "dead ends: n2")

        graph = self.graph()
        graph["nodes"].append({"id": "n2", "sympy_srepr": "Eq(x, 99)"})
        graph["edges"].append({"from": "n2", "to": "n1", "rule": "detached"})
        payload = self.evaluate(graph, verifier=self.verifier(graph))
        self.assertEqual("FAIL", payload["status"])
        self.assert_reason(payload, "unreachable: n2")

    def test_verifier_must_be_bound_parse_all_nodes_and_pass_all_edges(self) -> None:
        graph = self.graph()
        verifier = self.verifier(graph)
        verifier["problem_id"] = "other_graph"
        payload = self.evaluate(graph, verifier=verifier)
        self.assertEqual("ERROR", payload["status"])
        self.assert_reason(payload, "problem_id")

        verifier = self.verifier(graph)
        verifier["parsed_nodes"] -= 1
        verifier["parse_errors"] = [{"node": "n1", "error": "bad"}]
        payload = self.evaluate(graph, verifier=verifier)
        self.assertEqual("FAIL", payload["status"])
        self.assert_reason(payload, "parse every graph node")

        verifier = self.verifier(graph, statuses=["FAIL"])
        payload = self.evaluate(graph, verifier=verifier)
        self.assertEqual("FAIL", payload["status"])
        self.assert_reason(payload, "non-PASS edges")

    def test_root_residual_must_exactly_match_frozen_givens_up_to_sign(self) -> None:
        graph = self.graph()
        root = sp.sympify(graph["nodes"][0]["sympy_srepr"], locals=vars(sp))
        graph["nodes"][0]["sympy_srepr"] = sp.srepr(
            sp.Eq(2 * root.lhs, 2 * root.rhs, evaluate=False)
        )

        payload = self.evaluate(graph)

        self.assertEqual("FAIL", payload["status"])
        self.assert_reason(payload, "residual does not exactly match")

    def test_goal_must_be_exact_rational_solution_and_match_contract(self) -> None:
        graph = self.graph()
        graph["nodes"][1]["sympy_srepr"] = "Eq(2*x, 6)"
        payload = self.evaluate(graph)
        self.assertEqual("FAIL", payload["status"])
        self.assert_reason(payload, "Eq(x, q)")

        graph = self.graph()
        graph["nodes"][1]["sympy_srepr"] = "Eq(x, 999)"
        payload = self.evaluate(graph)
        self.assertEqual("FAIL", payload["status"])
        self.assert_reason(payload, "does not match the trusted contract")


if __name__ == "__main__":
    unittest.main()
