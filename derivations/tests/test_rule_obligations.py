from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sympy import Derivative, Eq, Integer, Symbol


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import verify  # noqa: E402


class RuleObligationTests(unittest.TestCase):
    def run_cmd(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_simplify_expression_has_explicit_symbolic_obligation(self) -> None:
        problem = {
            "id": "simplify_obligation",
            "root_node": "n0",
            "goal_node": "n1",
            "nodes": [
                {
                    "id": "n0",
                    "sympy_srepr": "Eq(Add(Symbol('x'), Integer(0), evaluate=False), Integer(1), evaluate=False)",
                },
                {"id": "n1", "sympy_srepr": "Eq(Symbol('x'), Integer(1), evaluate=False)"},
            ],
            "edges": [
                {"from": "n0", "to": "n1", "rule": "simplify_expression", "rule_args": {}},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            problem_path = Path(tmp) / "problem.json"
            problem_path.write_text(json.dumps(problem, indent=2))

            result = self.run_cmd("derivations/verify.py", str(problem_path))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            sidecar = json.loads((Path(tmp) / "problem.verifier.json").read_text())
            self.assertEqual(sidecar["edge_results"][0]["status"], "PASS")
            self.assertEqual(
                sidecar["validator_sources"]["simplify_expression"],
                "rule_contracts:builtin",
            )

    def test_known_rule_without_obligation_does_not_fallback_to_truth_preservation(self) -> None:
        x = Symbol("x")
        with patch.object(verify, "KNOWN_RULES", {"declared_but_unproved"}), patch.dict(
            verify.VALIDATORS,
            {},
            clear=True,
        ):
            status, reason = verify.verify_edge(
                Eq(x, Integer(1), evaluate=False),
                Eq(x, Integer(1), evaluate=False),
                "declared_but_unproved",
                {},
            )

        self.assertEqual(status, "FAIL")
        self.assertIn("no registered proof obligation", reason)

    def test_unsafe_calculus_rule_requires_registered_obligation(self) -> None:
        x = Symbol("x")
        y = Symbol("y")
        with patch.object(verify, "KNOWN_RULES", {"differentiate_both_sides"}), patch.dict(
            verify.VALIDATORS,
            {},
            clear=True,
        ):
            status, reason = verify.verify_edge(
                Eq(y, x**2, evaluate=False),
                Eq(Derivative(y, x), 2 * x, evaluate=False),
                "differentiate_both_sides",
                {"var": "x"},
            )

        self.assertEqual(status, "FAIL")
        self.assertIn("no registered proof obligation", reason)


if __name__ == "__main__":
    unittest.main()
