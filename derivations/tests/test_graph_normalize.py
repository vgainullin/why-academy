from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

from graph_normalize import normalize_problem  # noqa: E402


def linear_duplicate_problem() -> dict:
    return {
        "id": "normalize_linear_duplicate",
        "root_node": "n0",
        "goal_node": "n2",
        "nodes": [
            {
                "id": "n0",
                "sympy_srepr": "Eq(Add(Symbol('x'), Integer(2)), Integer(5), evaluate=False)",
            },
            {
                "id": "n1",
                "sympy_srepr": "Eq(Symbol('x'), Integer(3), evaluate=False)",
            },
            {
                "id": "n2",
                "sympy_srepr": "Equality(Symbol('x'), Integer(3))",
            },
        ],
        "edges": [
            {
                "from": "n0",
                "to": "n1",
                "rule": "subtract_constant_from_both_sides",
                "rule_args": {"constant": "Integer(2)"},
            },
            {
                "from": "n1",
                "to": "n2",
                "rule": "simplify_expression",
                "rule_args": {},
            },
            {
                "from": "n0",
                "to": "n2",
                "rule": "subtract_constant_from_both_sides",
                "rule_args": {"constant": "Integer(2)"},
            },
        ],
    }


def vertical_loop_duplicate_problem() -> dict:
    return {
        "id": "normalize_vertical_loop_duplicate",
        "root_node": "n0",
        "goal_node": "n8",
        "nodes": [
            {
                "id": "n0",
                "sympy_srepr": "Eq(Rational(1, 2)*m*v**2 + m*Symbol('g')*(2*Symbol('R')), m*Symbol('g')*Symbol('h'))",
            },
            {
                "id": "n1",
                "sympy_srepr": "Eq(Rational(1, 2)*v**2 + Symbol('g')*(2*Symbol('R')), Symbol('g')*Symbol('h'))",
            },
            {
                "id": "n2",
                "sympy_srepr": "Eq((Rational(1, 2)*v**2 + Symbol('g')*(2*Symbol('R')))/Symbol('g'), Symbol('h'))",
            },
            {
                "id": "n3",
                "sympy_srepr": "Eq(2*Symbol('R') + v**2/(2*Symbol('g')), Symbol('h'))",
            },
            {
                "id": "n4",
                "sympy_srepr": "Eq(m*Symbol('g'), m*v**2/Symbol('R'))",
            },
            {
                "id": "n5",
                "sympy_srepr": "Eq(Symbol('g'), v**2/Symbol('R'))",
            },
            {
                "id": "n6",
                "sympy_srepr": "Eq(Symbol('g')*Symbol('R'), v**2)",
            },
            {
                "id": "n7",
                "sympy_srepr": "Eq(2*Symbol('R') + (Symbol('g')*Symbol('R'))/(2*Symbol('g')), Symbol('h'))",
            },
            {
                "id": "n8",
                "sympy_srepr": "Eq(5*Symbol('R')/2, Symbol('h'))",
            },
        ],
        "edges": [
            {"from": "n0", "to": "n1", "rule": "divide_both_sides", "rule_args": {"divisor": "m"}},
            {
                "from": "n1",
                "to": "n2",
                "rule": "divide_both_sides",
                "rule_args": {"divisor": "Symbol('g')"},
            },
            {"from": "n2", "to": "n3", "rule": "simplify_expression", "rule_args": {}},
            {"from": "n4", "to": "n5", "rule": "divide_both_sides", "rule_args": {"divisor": "m"}},
            {
                "from": "n5",
                "to": "n6",
                "rule": "multiply_both_sides",
                "rule_args": {"multiplier": "Symbol('R')"},
            },
            {
                "from": "n3",
                "to": "n7",
                "rule": "substitute_expression",
                "rule_args": {
                    "symbol": "v**2",
                    "replacement": "Symbol('g')*Symbol('R')",
                },
            },
            {"from": "n7", "to": "n8", "rule": "simplify_expression", "rule_args": {}},
        ],
    }


def assumption_mismatch_substitution_problem() -> dict:
    return {
        "id": "assumption_mismatch_substitution",
        "root_node": "n0",
        "goal_node": "n1",
        "nodes": [
            {
                "id": "n0",
                "sympy_srepr": (
                    "Eq(Rational(1,2)*m*Symbol('v')**2 + m*Symbol('g')*(2*Symbol('R')), "
                    "m*Symbol('g')*Symbol('h'))"
                ),
            },
            {
                "id": "n1",
                "sympy_srepr": (
                    "Eq(Rational(1,2)*m*(sqrt(Symbol('g')*Symbol('R')))**2 + "
                    "m*Symbol('g')*(2*Symbol('R')), m*Symbol('g')*Symbol('h'))"
                ),
            },
        ],
        "edges": [
            {
                "from": "n0",
                "to": "n1",
                "rule": "substitute_value",
                "rule_args": {
                    "symbol": "v",
                    "replacement": "sqrt(Symbol('g')*Symbol('R'))",
                },
            }
        ],
    }


def unknown_macro_rule_problem() -> dict:
    return {
        "id": "unknown_macro_rule",
        "root_node": "n0",
        "goal_node": "n1",
        "nodes": [
            {"id": "n0", "sympy_srepr": "Eq(Symbol('x'), Integer(1))"},
            {"id": "n1", "sympy_srepr": "Eq(Symbol('x'), Integer(1))"},
        ],
        "edges": [
            {
                "from": "n0",
                "to": "n1",
                "rule": "invented_macro_rule",
                "rule_args": {},
            }
        ],
    }


class GraphNormalizeTests(unittest.TestCase):
    def run_cmd(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_merges_duplicate_nodes_and_rewrites_edges(self) -> None:
        normalized, report = normalize_problem(linear_duplicate_problem())

        self.assertEqual(normalized["goal_node"], "n1")
        self.assertEqual([n["id"] for n in normalized["nodes"]], ["n0", "n1"])
        self.assertEqual(len(normalized["edges"]), 1)
        self.assertEqual(normalized["edges"][0]["from"], "n0")
        self.assertEqual(normalized["edges"][0]["to"], "n1")
        self.assertEqual(len(report["node_merges"]), 1)
        self.assertEqual(
            [d["reason"] for d in report["dropped_edges"]],
            ["self_edge_after_merge", "duplicate_edge"],
        )

    def test_does_not_merge_real_derivation_steps(self) -> None:
        normalized, _report = normalize_problem(linear_duplicate_problem())

        node_ids = {n["id"] for n in normalized["nodes"]}
        self.assertEqual(node_ids, {"n0", "n1"})

    def test_normalized_previous_duplicate_failure_passes_local_gates(self) -> None:
        target = (
            "derive the minimum drop height h = 5R/2 for a ball completing a vertical loop, "
            "given (1) centripetal: m*g = m*v^2/R and (2) energy: "
            "(1/2)*m*v^2 + m*g*(2R) = m*g*h"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            problem_path = tmpdir / "problem.json"
            problem_path.write_text(json.dumps(vertical_loop_duplicate_problem(), indent=2))

            before_canvas = self.run_cmd("derivations/canvas_check.py", str(problem_path))
            self.assertNotEqual(before_canvas.returncode, 0, before_canvas.stdout + before_canvas.stderr)

            normalizer = self.run_cmd("derivations/graph_normalize.py", str(problem_path))
            self.assertEqual(normalizer.returncode, 0, normalizer.stdout + normalizer.stderr)
            report = json.loads((tmpdir / "problem.normalizer.json").read_text())
            self.assertEqual(report["n_nodes_before"], 9)
            self.assertEqual(report["n_nodes_after"], 8)
            self.assertEqual(report["n_edges_before"], 7)
            self.assertEqual(report["n_edges_after"], 6)

            verify = self.run_cmd("derivations/verify.py", str(problem_path))
            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
            canvas = self.run_cmd("derivations/canvas_check.py", str(problem_path))
            self.assertEqual(canvas.returncode, 0, canvas.stdout + canvas.stderr)
            target_check = self.run_cmd(
                "derivations/target_check.py",
                str(problem_path),
                "--target",
                target,
            )
            self.assertEqual(target_check.returncode, 0, target_check.stdout + target_check.stderr)

    def test_unknown_macro_rules_fail_even_if_truth_preserving(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            problem_path = Path(tmp) / "problem.json"
            problem_path.write_text(json.dumps(unknown_macro_rule_problem(), indent=2))

            verify = self.run_cmd("derivations/verify.py", str(problem_path))
            self.assertNotEqual(verify.returncode, 0, verify.stdout + verify.stderr)
            sidecar = json.loads((Path(tmp) / "problem.verifier.json").read_text())
            self.assertEqual(sidecar["edge_summary"]["FAIL"], 1)
            self.assertIn("unknown rule", sidecar["edge_results"][0]["reason"])

    def test_substitution_matches_symbols_by_name_across_assumptions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            problem_path = Path(tmp) / "problem.json"
            problem_path.write_text(json.dumps(assumption_mismatch_substitution_problem(), indent=2))

            verify = self.run_cmd("derivations/verify.py", str(problem_path))
            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)


if __name__ == "__main__":
    unittest.main()
