from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

from rule_executor import (  # noqa: E402
    RuleExecutorCoverageGap,
    RulePlanError,
    execute_plan,
    plan_from_response,
    validate_rule_plan,
)
from substitution_structural_check import check_problem  # noqa: E402


def two_step_plan() -> dict:
    return {
        "id": "rule_exec_valid",
        "root_ref": "energy_reduced",
        "goal_ref": "combined",
        "facts": [
            {
                "ref": "energy_reduced",
                "expr": (
                    "Eq(Add(Mul(Integer(2), Symbol('R')), "
                    "Mul(Rational(1, 2), Pow(Symbol('g'), Integer(-1)), Pow(v, Integer(2))), "
                    "evaluate=False), Symbol('h'), evaluate=False)"
                ),
            }
        ],
        "steps": [
            {
                "id": "substitute_v2",
                "from": "energy_reduced",
                "rule": "substitute_value",
                "rule_args": {"symbol": "v**2", "replacement": "Symbol('g')*Symbol('R')"},
            },
            {
                "id": "combined",
                "from": "substitute_v2",
                "rule": "simplify_expression",
                "rule_args": {},
            },
        ],
    }


class RuleExecutorTests(unittest.TestCase):
    def test_accepts_minimal_rule_plan_v1(self) -> None:
        plan = two_step_plan()

        self.assertIs(validate_rule_plan(plan, problem_id="rule_exec_valid"), plan)

    def test_rejects_embedded_nodes_or_edges(self) -> None:
        plan = two_step_plan()
        plan["nodes"] = []

        with self.assertRaisesRegex(RulePlanError, "schema validation failed"):
            validate_rule_plan(plan, problem_id="rule_exec_valid")

    def test_malformed_json_fails_closed(self) -> None:
        with self.assertRaisesRegex(RulePlanError, "invalid JSON|response did not contain"):
            plan_from_response("{not-json", problem_id="rule_exec_valid")

    def test_unknown_tactic_is_coverage_gap_not_pass(self) -> None:
        plan = two_step_plan()
        plan["steps"][0]["rule"] = "solve_entire_problem"

        with self.assertRaises(RuleExecutorCoverageGap) as cm:
            execute_plan(plan, problem_id="rule_exec_valid")

        self.assertEqual(cm.exception.failure_class, "rule_executor_coverage_gap")
        self.assertEqual(cm.exception.report["status"], "COVERAGE_GAP")

    def test_rejects_zero_step_answer_fact(self) -> None:
        plan = {
            "id": "rule_exec_valid",
            "root_ref": "start",
            "goal_ref": "answer",
            "facts": [
                {"ref": "start", "expr": "Eq(Add(Symbol('x'), Integer(2)), Integer(5), evaluate=False)"},
                {"ref": "answer", "expr": "Eq(Symbol('x'), Integer(3), evaluate=False)"},
            ],
            "steps": [],
        }

        with self.assertRaisesRegex(RulePlanError, "schema validation failed at \\$.steps"):
            validate_rule_plan(plan, problem_id="rule_exec_valid")

    def test_rejects_goal_ref_to_initial_fact(self) -> None:
        plan = two_step_plan()
        plan["facts"].append({"ref": "answer", "expr": "Eq(Symbol('x'), Integer(3), evaluate=False)"})
        plan["goal_ref"] = "answer"

        with self.assertRaisesRegex(RulePlanError, "goal_ref must reference a derived step"):
            validate_rule_plan(plan, problem_id="rule_exec_valid")

    def test_rejects_goal_not_derived_from_root(self) -> None:
        plan = two_step_plan()
        plan["facts"].append({"ref": "other_start", "expr": "Eq(Symbol('x'), Integer(3), evaluate=False)"})
        plan["steps"].append({
            "id": "other_final",
            "from": "other_start",
            "rule": "swap_sides",
            "rule_args": {},
        })
        plan["goal_ref"] = "other_final"

        with self.assertRaisesRegex(RulePlanError, "goal_ref must be derived from root_ref"):
            validate_rule_plan(plan, problem_id="rule_exec_valid")

    def test_same_plan_emits_same_graph_ids_and_srepr(self) -> None:
        plan = two_step_plan()

        p1, r1 = execute_plan(copy.deepcopy(plan), problem_id="rule_exec_valid")
        p2, r2 = execute_plan(copy.deepcopy(plan), problem_id="rule_exec_valid")

        self.assertEqual(p1, p2)
        self.assertEqual(r1["ref_to_node_id"], r2["ref_to_node_id"])

    def test_substitute_then_simplify_requires_two_steps(self) -> None:
        problem, report = execute_plan(two_step_plan(), problem_id="rule_exec_valid")

        self.assertEqual(report["status"], "PASS")
        self.assertEqual([edge["rule"] for edge in problem["edges"]], ["substitute_value", "simplify_expression"])
        substitution_report = check_problem(problem)
        self.assertEqual(substitution_report["status"], "PASS", substitution_report)
        goal_node = next(n for n in problem["nodes"] if n["id"] == problem["goal_node"])
        self.assertIn("Rational(5, 2)", goal_node["sympy_srepr"])


if __name__ == "__main__":
    unittest.main()
