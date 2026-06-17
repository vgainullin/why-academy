from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

from json_inner import ProblemJsonError, validate_problem  # noqa: E402


def valid_problem() -> dict:
    return {
        "id": "json_schema_valid",
        "root_node": "n0",
        "goal_node": "n1",
        "nodes": [
            {"id": "n0", "sympy_srepr": "Eq(Symbol('x'), Integer(3), evaluate=False)"},
            {"id": "n1", "sympy_srepr": "Eq(Symbol('x'), Integer(3), evaluate=False)"},
        ],
        "edges": [
            {
                "from": "n0",
                "to": "n1",
                "rule": "simplify_expression",
                "rule_args": {},
            }
        ],
    }


class JsonInnerValidationTests(unittest.TestCase):
    def assert_invalid(self, problem: dict, expected: str) -> None:
        with self.assertRaisesRegex(ProblemJsonError, expected):
            validate_problem(problem, problem_id="json_schema_valid")

    def test_valid_problem_passes(self) -> None:
        problem = valid_problem()

        self.assertIs(validate_problem(problem, problem_id="json_schema_valid"), problem)

    def test_missing_top_level_key_fails_schema(self) -> None:
        problem = valid_problem()
        del problem["nodes"]

        self.assert_invalid(problem, "schema validation failed")

    def test_extra_top_level_key_fails_schema(self) -> None:
        problem = valid_problem()
        problem["metadata"] = {}

        self.assert_invalid(problem, "schema validation failed")

    def test_rule_args_must_be_object(self) -> None:
        problem = valid_problem()
        problem["edges"][0]["rule_args"] = "constant=Integer(1)"

        self.assert_invalid(problem, "schema validation failed")

    def test_edge_endpoint_must_reference_node(self) -> None:
        problem = valid_problem()
        problem["edges"][0]["to"] = "missing"

        self.assert_invalid(problem, "endpoint does not reference node ids")

    def test_duplicate_node_id_fails(self) -> None:
        problem = valid_problem()
        problem["nodes"].append(copy.deepcopy(problem["nodes"][0]))

        self.assert_invalid(problem, "duplicate node id")


if __name__ == "__main__":
    unittest.main()
