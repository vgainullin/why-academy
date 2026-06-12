from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sympy import Derivative, Eq, Limit, Symbol


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

from rule_contracts import (  # noqa: E402
    validate_limit_definition,
    validate_limit_evaluate,
    validate_limit_rewrite,
)
import target_check  # noqa: E402

x = Symbol("x", real=True)
h = Symbol("h")
t = Symbol("t", real=True)

DQ = ((x + h) ** 2 - x**2) / h


class LimitDefinitionTests(unittest.TestCase):
    def test_literal_difference_quotient_passes(self) -> None:
        status, reason = validate_limit_definition(
            Eq(t, Derivative(x**2, x)),
            Eq(t, Limit(DQ, h, 0)),
            {},
            {},
        )
        self.assertEqual(status, "PASS", reason)

    def test_pre_simplified_quotient_fails(self) -> None:
        status, reason = validate_limit_definition(
            Eq(t, Derivative(x**2, x)),
            Eq(t, Limit(2 * x + h, h, 0)),
            {},
            {},
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("difference quotient", reason)

    def test_expanded_quotient_fails(self) -> None:
        status, _ = validate_limit_definition(
            Eq(t, Derivative(x**2, x)),
            Eq(t, Limit((2 * x * h + h**2) / h, h, 0)),
            {},
            {},
        )
        self.assertEqual(status, "FAIL")

    def test_limit_variable_must_be_fresh(self) -> None:
        status, reason = validate_limit_definition(
            Eq(t, Derivative(x**2, x)),
            Eq(t, Limit(((x + x) ** 2 - x**2) / x, x, 0)),
            {},
            {},
        )
        self.assertEqual(status, "FAIL")

    def test_rest_of_equation_must_be_unchanged(self) -> None:
        status, _ = validate_limit_definition(
            Eq(t, Derivative(x**2, x)),
            Eq(t + 1, Limit(DQ, h, 0)),
            {},
            {},
        )
        self.assertEqual(status, "FAIL")


class LimitRewriteTests(unittest.TestCase):
    def test_cancel_removable_factor_passes(self) -> None:
        status, reason = validate_limit_rewrite(
            Eq(t, Limit((2 * x * h + h**2) / h, h, 0)),
            Eq(t, Limit(2 * x + h, h, 0)),
            {},
            {},
        )
        self.assertEqual(status, "PASS", reason)

    def test_expand_passes(self) -> None:
        status, reason = validate_limit_rewrite(
            Eq(t, Limit(DQ, h, 0)),
            Eq(t, Limit((2 * x * h + h**2) / h, h, 0)),
            {},
            {},
        )
        self.assertEqual(status, "PASS", reason)

    def test_changing_limit_point_fails(self) -> None:
        status, reason = validate_limit_rewrite(
            Eq(t, Limit(2 * x + h, h, 0)),
            Eq(t, Limit(2 * x + h, h, 1)),
            {},
            {},
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("point", reason)

    def test_changing_limit_variable_fails(self) -> None:
        u = Symbol("u", real=True)
        status, reason = validate_limit_rewrite(
            Eq(t, Limit(2 * x + h, h, 0)),
            Eq(t, Limit(2 * x + u, u, 0)),
            {},
            {},
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("variable", reason)

    def test_changing_other_side_fails(self) -> None:
        status, reason = validate_limit_rewrite(
            Eq(t, Limit((2 * x * h + h**2) / h, h, 0)),
            Eq(t + 1, Limit(2 * x + h, h, 0)),
            {},
            {},
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("unchanged", reason)

    def test_non_equivalent_body_fails(self) -> None:
        status, _ = validate_limit_rewrite(
            Eq(t, Limit((2 * x * h + h**2) / h, h, 0)),
            Eq(t, Limit(3 * x + h, h, 0)),
            {},
            {},
        )
        self.assertEqual(status, "FAIL")


class LimitEvaluateTests(unittest.TestCase):
    def test_continuous_substitution_passes(self) -> None:
        status, reason = validate_limit_evaluate(
            Eq(t, Limit(2 * x + h, h, 0)),
            Eq(t, 2 * x),
            {},
            {},
        )
        self.assertEqual(status, "PASS", reason)

    def test_indeterminate_form_fails(self) -> None:
        status, reason = validate_limit_evaluate(
            Eq(t, Limit((2 * x * h + h**2) / h, h, 0)),
            Eq(t, 2 * x),
            {},
            {},
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("not continuous", reason)

    def test_wrong_value_fails(self) -> None:
        status, _ = validate_limit_evaluate(
            Eq(t, Limit(2 * x + h, h, 0)),
            Eq(t, 3 * x),
            {},
            {},
        )
        self.assertEqual(status, "FAIL")

    def test_unbounded_limit_fails(self) -> None:
        status, reason = validate_limit_evaluate(
            Eq(t, Limit(1 / h, h, 0)),
            Eq(t, 0),
            {},
            {},
        )
        self.assertEqual(status, "FAIL")


class LimitChainEndToEndTests(unittest.TestCase):
    PROBLEM = {
        "id": "ddx_x_squared_limit_def",
        "root_node": "n0",
        "goal_node": "n4",
        "nodes": [
            {"id": "n0", "sympy_srepr": "Eq(t, Derivative(x**2, x), evaluate=False)"},
            {
                "id": "n1",
                "sympy_srepr": "Eq(t, Limit(((x + Symbol('h'))**2 - x**2)/Symbol('h'), Symbol('h'), 0), evaluate=False)",
            },
            {
                "id": "n2",
                "sympy_srepr": "Eq(t, Limit((2*x*Symbol('h') + Symbol('h')**2)/Symbol('h'), Symbol('h'), 0), evaluate=False)",
            },
            {
                "id": "n3",
                "sympy_srepr": "Eq(t, Limit(2*x + Symbol('h'), Symbol('h'), 0), evaluate=False)",
            },
            {"id": "n4", "sympy_srepr": "Eq(t, 2*x, evaluate=False)"},
        ],
        "edges": [
            {"from": "n0", "to": "n1", "rule": "limit_definition_of_derivative", "rule_args": {}},
            {"from": "n1", "to": "n2", "rule": "expand_within_limit", "rule_args": {}},
            {"from": "n2", "to": "n3", "rule": "cancel_within_limit", "rule_args": {}},
            {"from": "n3", "to": "n4", "rule": "evaluate_limit", "rule_args": {}},
        ],
    }

    def run_cmd(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_full_chain_passes_verifier_and_canvas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            problem_path = Path(tmp) / "problem.json"
            problem_path.write_text(json.dumps(self.PROBLEM, indent=2))

            result = self.run_cmd("derivations/verify.py", str(problem_path))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            sidecar = json.loads((Path(tmp) / "problem.verifier.json").read_text())
            self.assertEqual(sidecar["edge_summary"]["PASS"], 4, sidecar["edge_results"])
            self.assertEqual(sidecar["edge_summary"]["FAIL"], 0, sidecar["edge_results"])

            canvas = self.run_cmd("derivations/canvas_check.py", str(problem_path))
            self.assertEqual(canvas.returncode, 0, canvas.stdout + canvas.stderr)

    def test_fused_chain_fails_verifier(self) -> None:
        fused = json.loads(json.dumps(self.PROBLEM))
        fused["nodes"] = [fused["nodes"][0], fused["nodes"][4]]
        fused["edges"] = [
            {"from": "n0", "to": "n4", "rule": "evaluate_limit", "rule_args": {}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            problem_path = Path(tmp) / "problem.json"
            problem_path.write_text(json.dumps(fused, indent=2))
            result = self.run_cmd("derivations/verify.py", str(problem_path))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)


class TargetCheckDerivativeNotationTests(unittest.TestCase):
    TARGET = "derive d/dx(x^2) = 2x from the limit definition of the derivative"

    def test_target_goal_is_extracted(self) -> None:
        goals = target_check.expected_goals(self.TARGET)
        self.assertTrue(goals, "d/dx goal should be deterministically extractable")
        goal, _source = goals[0]
        self.assertTrue(goal.lhs.has(Derivative))

    def test_goal_node_matches_target(self) -> None:
        goals = target_check.expected_goals(self.TARGET)
        goal_expr = Eq(Derivative(x**2, x), 2 * x, evaluate=False)
        self.assertTrue(any(target_check.eq_matches(goal_expr, eq) for eq, _ in goals))

    def test_wrong_goal_node_does_not_match(self) -> None:
        goals = target_check.expected_goals(self.TARGET)
        wrong = Eq(Derivative(x**2, x), 3 * x, evaluate=False)
        self.assertFalse(any(target_check.eq_matches(wrong, eq) for eq, _ in goals))


if __name__ == "__main__":
    unittest.main()
