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

from substitution_structural_check import check_problem  # noqa: E402


def fused_substitution_problem() -> dict:
    return {
        "id": "fused_substitution",
        "root_node": "n0",
        "goal_node": "n1",
        "nodes": [
            {
                "id": "n0",
                "sympy_srepr": (
                    "Eq(Add(Mul(Integer(2), Symbol('R')), "
                    "Mul(Rational(1, 2), Pow(Symbol('g'), Integer(-1)), Pow(v, Integer(2))), "
                    "evaluate=False), Symbol('h'), evaluate=False)"
                ),
            },
            {"id": "n1", "sympy_srepr": "Eq(Mul(Rational(5, 2), Symbol('R')), Symbol('h'))"},
        ],
        "edges": [
            {
                "from": "n0",
                "to": "n1",
                "rule": "substitute_value",
                "rule_args": {"symbol": "v**2", "replacement": "Symbol('g')*Symbol('R')"},
            }
        ],
    }


def immediate_substitution_problem() -> dict:
    p = fused_substitution_problem()
    p["id"] = "immediate_substitution"
    p["nodes"][1]["sympy_srepr"] = (
        "Eq(Add(Mul(Integer(2), Symbol('R')), "
        "Mul(Rational(1, 2), Pow(Symbol('g'), Integer(-1)), "
        "Mul(Symbol('R'), Symbol('g'), evaluate=False), evaluate=False), "
        "evaluate=False), Symbol('h'), evaluate=False)"
    )
    return p


class SubstitutionStructuralCheckTests(unittest.TestCase):
    def run_cmd(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_accepts_immediate_unsimplified_substitute_value(self) -> None:
        report = check_problem(immediate_substitution_problem())

        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(report["n_inspected"], 1)

    def test_rejects_simplified_substitute_value(self) -> None:
        report = check_problem(fused_substitution_problem())

        self.assertEqual(report["status"], "FAIL", report)
        self.assertIn("expected_sympy_srepr", report["failures"][0])

    def test_control_verify_still_passes_known_fused_edge_without_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "problem.json"
            path.write_text(json.dumps(fused_substitution_problem(), indent=2))

            verify = self.run_cmd("derivations/verify.py", str(path))

            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)


if __name__ == "__main__":
    unittest.main()
