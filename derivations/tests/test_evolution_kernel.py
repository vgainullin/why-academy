from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from collections import Counter
from fractions import Fraction
from pathlib import Path

import sympy as sp


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

from domains.chaos import ChaosLogisticPlugin, build_logistic_task  # noqa: E402
from domains.grade8_math import Grade8MathPlugin  # noqa: E402
from evolution.artifacts import ArtifactStore  # noqa: E402
from evolution.evidence import aggregate_evidence  # noqa: E402
from evolution.experiments import compare_arms, evaluate_criteria  # noqa: E402
from evolution.protocols import AttemptEvidence, DomainPlugin, RunSpec  # noqa: E402
from evolution.runner import run_attempt  # noqa: E402
from frozen_task_store import FrozenTaskStore  # noqa: E402


def _fraction(value: dict[str, int]) -> Fraction:
    return Fraction(value["numerator"], value["denominator"])


def _rational(value: Fraction) -> sp.Rational:
    return sp.Rational(value.numerator, value.denominator)


def _grade8_candidate(contract: dict, *, correct: bool) -> dict:
    givens = contract["givens"]
    x = sp.Symbol("x", real=True)
    lhs = givens["lhs"]
    rhs = givens["rhs"]
    lhs_expr = _rational(_fraction(lhs["coefficient"])) * x + _rational(_fraction(lhs["constant"]))
    rhs_expr = _rational(_fraction(rhs["coefficient"])) * x + _rational(_fraction(rhs["constant"]))
    value = _fraction(contract["expected"]["values"][0])
    if not correct:
        value += 1
    root = sp.Eq(lhs_expr, rhs_expr, evaluate=False)
    goal = sp.Eq(x, _rational(value), evaluate=False)
    graph = {
        "id": "kernel_grade8_candidate",
        "root_node": "n0",
        "goal_node": "n1",
        "nodes": [
            {"id": "n0", "sympy_srepr": sp.srepr(root)},
            {"id": "n1", "sympy_srepr": sp.srepr(goal)},
        ],
        "edges": [
            {"from": "n0", "to": "n1", "rule": "solve_linear_equation", "rule_args": {}}
        ],
    }
    statuses = ["PASS"]
    counts = Counter(statuses)
    verifier = {
        "problem_id": graph["id"],
        "verifier_version": "kernel-test.v1",
        "n_nodes": len(graph["nodes"]),
        "n_edges": len(graph["edges"]),
        "parsed_nodes": len(graph["nodes"]),
        "parse_errors": [],
        "edge_results": [
            {
                "from": "n0",
                "to": "n1",
                "rule": "solve_linear_equation",
                "status": "PASS",
                "reason": "test evidence",
            }
        ],
        "edge_summary": {
            status: counts[status]
            for status in ("PASS", "FAIL", "UNCOVERED", "WEAK_PASS", "ERROR")
        },
    }
    return {"graph": graph, "verifier": verifier}


class EvolutionKernelConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        bundle = DERIVATIONS / "practice" / "algebra_linear_8th_grade_summer.json"
        store = FrozenTaskStore.load(bundle, hashlib.sha256(bundle.read_bytes()).hexdigest())
        cls.grade8_task = store.get_task("alg8-lin-001")
        cls.chaos_task = build_logistic_task()
        cls.grade8 = Grade8MathPlugin()
        cls.chaos = ChaosLogisticPlugin()

    def _run(self, plugin, task, candidate, *, run_id: str, arm: str):
        seen = {}

        def producer(public_task):
            seen.update(public_task)
            return candidate

        evidence = run_attempt(
            spec=RunSpec(run_id=run_id, cohort_id="mixed-domain-v1", arm=arm),
            plugin=plugin,
            task=task,
            producer=producer,
        )
        self.assertNotIn("expected", seen)
        self.assertNotIn("task_digest", seen)
        self.assertNotIn("contract_digest", seen)
        return evidence

    def test_unrelated_domains_implement_one_runtime_protocol(self) -> None:
        self.assertIsInstance(self.grade8, DomainPlugin)
        self.assertIsInstance(self.chaos, DomainPlugin)

        grade8 = self._run(
            self.grade8,
            self.grade8_task,
            _grade8_candidate(self.grade8_task, correct=True),
            run_id="mixed-pass",
            arm="candidate",
        )
        chaos = self._run(
            self.chaos,
            self.chaos_task,
            {
                "task_id": self.chaos_task["id"],
                "claim": {
                    "kind": "sensitive_dependence",
                    "value": self.chaos_task["expected"]["value"],
                },
            },
            run_id="mixed-pass",
            arm="candidate",
        )

        self.assertEqual("PASS", grade8.status)
        self.assertEqual("PASS", chaos.status)
        self.assertIn("pedagogy", {gate.name for gate in grade8.gates})
        self.assertIn("dynamics", {gate.name for gate in chaos.gates})
        self.assertNotIn("graph", str(chaos.to_dict()).lower())

        aggregate = aggregate_evidence([grade8, chaos])
        self.assertEqual(2, aggregate["n_tasks"])
        self.assertEqual(
            {"chaos_logistic": 1, "grade8_math": 1},
            aggregate["plugin_counts"],
        )

    def test_same_artifact_store_round_trips_both_domains(self) -> None:
        grade8 = self._run(
            self.grade8,
            self.grade8_task,
            _grade8_candidate(self.grade8_task, correct=True),
            run_id="artifact-run",
            arm="candidate",
        )
        chaos = self._run(
            self.chaos,
            self.chaos_task,
            {
                "task_id": self.chaos_task["id"],
                "claim": {"kind": "sensitive_dependence", "value": self.chaos_task["expected"]["value"]},
            },
            run_id="artifact-run",
            arm="candidate",
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = ArtifactStore(tmp)
            first_path = store.write_evidence(grade8)
            store.write_evidence(chaos)
            restored = AttemptEvidence.from_dict(store.read_json(first_path.relative_to(store.root)))
            self.assertEqual(grade8, restored)
            with self.assertRaises(FileExistsError):
                store.write_evidence(grade8)

    def test_same_experiment_comparator_pairs_both_domains(self) -> None:
        correct_grade8 = _grade8_candidate(self.grade8_task, correct=True)
        wrong_grade8 = _grade8_candidate(self.grade8_task, correct=False)
        correct_chaos = {
            "task_id": self.chaos_task["id"],
            "claim": {"kind": "sensitive_dependence", "value": self.chaos_task["expected"]["value"]},
        }
        wrong_chaos = {
            "task_id": self.chaos_task["id"],
            "claim": {"kind": "sensitive_dependence", "value": not self.chaos_task["expected"]["value"]},
        }
        control = [
            self._run(self.grade8, self.grade8_task, wrong_grade8, run_id="control", arm="control"),
            self._run(self.chaos, self.chaos_task, wrong_chaos, run_id="control", arm="control"),
        ]
        treatment = [
            self._run(self.grade8, self.grade8_task, correct_grade8, run_id="treatment", arm="treatment"),
            self._run(self.chaos, self.chaos_task, correct_chaos, run_id="treatment", arm="treatment"),
        ]

        comparison = compare_arms(control, treatment)

        self.assertEqual(2, comparison["n_tasks"])
        self.assertEqual(1.0, comparison["acceptance_delta"])
        self.assertEqual({"treatment_only_accepted": 2}, comparison["outcome_counts"])
        self.assertTrue(
            evaluate_criteria(comparison, {"min_acceptance_delta": 0.5})["passed"]
        )

    def test_kernel_source_has_no_domain_dependencies(self) -> None:
        source = "\n".join(
            path.read_text().lower()
            for path in sorted((DERIVATIONS / "evolution").glob("*.py"))
        )
        for forbidden in (
            "sympy",
            "linear_equation",
            "grade8",
            "chaos",
            "canvas_check",
            "typed_linear_equation_oracle",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
