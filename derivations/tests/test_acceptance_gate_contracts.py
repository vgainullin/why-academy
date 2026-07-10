from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import sympy as sp

ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import autonomous_epoch as ae  # noqa: E402
import closure_test as ct  # noqa: E402
import judge  # noqa: E402
import target_check  # noqa: E402
import verify  # noqa: E402


TARGET = "solve x + 2 = 5 for x"


def _eq(text: str):
    parsed = target_check.equation_from_text(text)
    assert parsed is not None
    return parsed[0]


def _linear_problem(*, root_node: str = "n0", goal_node: str = "n1",
                    nodes: list[dict] | None = None,
                    edges: list[dict] | None = None) -> dict:
    return {
        "id": "contract_linear",
        "root_node": root_node,
        "goal_node": goal_node,
        "nodes": nodes or [
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


def _write_problem(tmp: Path, problem: dict) -> Path:
    path = tmp / "problem.json"
    path.write_text(json.dumps(problem))
    return path


class TargetParserContractTests(unittest.TestCase):
    def assert_goal(self, target: str, expected_text_or_expr) -> None:
        expected = (
            expected_text_or_expr
            if isinstance(expected_text_or_expr, sp.Equality)
            else _eq(expected_text_or_expr)
        )
        goals = target_check.expected_goals(target)
        self.assertTrue(
            any(target_check.eq_matches(goal, expected) for goal, _source in goals),
            msg=f"{target!r} did not yield {expected!r}; got {goals!r}",
        )

    def test_supported_prompt_classes_extract_deterministic_goals(self) -> None:
        a, u, t, v = sp.symbols("a u t v", real=True)
        self.assert_goal("solve 4x = 20 for x by dividing both sides by 4", "x = 5")
        self.assert_goal(
            "factor x^2 - 9 as a difference of squares to get (x - 3)(x + 3)",
            "x^2 - 9 = (x - 3)*(x + 3)",
        )
        self.assert_goal(
            "derive the minimum drop height h = 5R/2 for a ball completing a vertical loop",
            "h = 5*R/2",
        )
        self.assert_goal(
            "derive v = u + a*t by integrating the constant-acceleration definition",
            sp.Eq(v, u + a * t, evaluate=False),
        )

    def test_context_implied_isolate_goal_is_extracted(self) -> None:
        F, a, m = sp.symbols("F a m", real=True)
        expected = sp.Eq(a, F / m, evaluate=False)
        self.assert_goal("Given F = m*a, isolate acceleration a.", expected)
        self.assert_goal("Rearrange F = m*a to isolate a.", expected)

    def test_semantic_goal_equivalence_accepts_swapped_orientation(self) -> None:
        goal = _eq("3 = x")
        expected = target_check.expected_goals(TARGET)[0][0]
        self.assertTrue(target_check.eq_matches(goal, expected))


class AcceptanceGraphMetadataContractTests(unittest.TestCase):
    def _check(self, problem: dict, target: str = TARGET) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as td:
            return target_check.check(_write_problem(Path(td), problem), target)

    def test_local_verifier_target_check_and_judge_use_same_goal_endpoint(self) -> None:
        problem = _linear_problem()
        with tempfile.TemporaryDirectory() as td:
            path = _write_problem(Path(td), problem)
            self.assertEqual(verify.verify(path), 0)
            rc, payload = target_check.check(path, TARGET)

        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["goal_node"], "n1")

        rendered = judge.render_graph(problem)
        goal_lines = [line for line in rendered.splitlines() if "(goal)" in line]
        self.assertEqual(len(goal_lines), 1)
        self.assertIn("n1:", goal_lines[0])
        self.assertNotIn("n0:", goal_lines[0])

    def test_rejects_matching_goal_equation_when_goal_is_not_terminal(self) -> None:
        problem = _linear_problem(
            nodes=[
                {"id": "n0", "sympy_srepr": "Eq(x + 2, 5)"},
                {"id": "n1", "sympy_srepr": "Eq(x, 3)"},
                {"id": "n2", "sympy_srepr": "Eq(x, 3)"},
            ],
            edges=[
                {
                    "from": "n0",
                    "to": "n1",
                    "rule": "subtract_constant_from_both_sides",
                    "rule_args": {"constant": 2},
                },
                {
                    "from": "n1",
                    "to": "n2",
                    "rule": "add_constant_to_both_sides",
                    "rule_args": {"constant": 0},
                },
            ],
        )

        rc, payload = self._check(problem)

        self.assertEqual(rc, 1)
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("not terminal", payload["reason"])

    def test_rejects_matching_goal_equation_when_goal_is_unreachable(self) -> None:
        problem = _linear_problem(edges=[])

        rc, payload = self._check(problem)

        self.assertEqual(rc, 1)
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("not reachable", payload["reason"])

    def test_rejects_unknown_edge_endpoint_metadata(self) -> None:
        problem = _linear_problem(edges=[
            {
                "from": "n404",
                "to": "n1",
                "rule": "subtract_constant_from_both_sides",
                "rule_args": {"constant": 2},
            }
        ])

        rc, payload = self._check(problem)

        self.assertEqual(rc, 1)
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("unknown", payload["reason"])

    def test_fails_closed_without_structured_target_evidence(self) -> None:
        rc, payload = self._check(_linear_problem(), "explain why this derivation is useful")

        self.assertEqual(rc, 1)
        self.assertEqual(payload["status"], "ERROR")
        self.assertIn("no deterministic expected goal", payload["reason"])


class BugfixRouteClosureFixtureContractTests(unittest.TestCase):
    def test_eval_plans_record_replay_inputs_for_each_acceptance_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            validator_prop = root / "proposal_bug_validator.md"
            validator_prop.write_text(
                "**Kind**: BUGFIX\n"
                "**Affected rule**: `subtract_constant_from_both_sides`\n"
                "**Seed hypothesis**: validator_contract\n\n"
                "## Reproduction case\n\n"
                "- from_srepr: Eq(x + 2, 5)\n"
                "- to_srepr: Eq(x, 3)\n"
                '- args: {"constant": 2}\n'
                "- expected: PASS\n"
            )
            target_prop = root / "proposal_bug_target.md"
            target_prop.write_text(
                "**Kind**: BUGFIX\n"
                "**Affected rule**: target_check\n"
                "**Seed hypothesis**: target_contract\n\n"
                "## Reproduction case\n\n"
                "```json\n"
                + json.dumps({
                    "target_check_fixture": {
                        "target": TARGET,
                        "problem": _linear_problem(goal_node="n0"),
                        "expected": {"status": "FAIL"},
                    }
                }, indent=2)
                + "\n```\n"
            )
            judge_prop = root / "proposal_bug_judge.md"
            judge_prop.write_text(
                "**Kind**: BUGFIX\n"
                "**Affected rule**: none\n"
                "**Seed hypothesis**: judge_contract\n\n"
                "## Reproduction case\n\n"
                "```json\n"
                + json.dumps({
                    "judge_eval": {
                        "overall": "FAIL",
                        "verdicts": {"target_goal_reached": {"verdict": "PASS"}},
                    }
                }, indent=2)
                + "\n```\n"
            )

            _, validator_plan = ae.write_proposal_eval_plan(
                {"runner": {}}, validator_prop, kind="BUGFIX",
                rule="subtract_constant_from_both_sides", baseline={},
            )
            _, target_plan = ae.write_proposal_eval_plan(
                {"runner": {}}, target_prop, kind="BUGFIX", rule="target_check", baseline={},
            )
            _, judge_plan = ae.write_proposal_eval_plan(
                {"runner": {}}, judge_prop, kind="BUGFIX", rule="none", baseline={},
            )

        self.assertEqual(validator_plan["adapter"], "bugfix_reproduction_replay")
        self.assertIsNotNone(validator_plan["inputs"]["reproduction"])
        self.assertEqual(target_plan["adapter"], "target_check_replay")
        self.assertIsNotNone(target_plan["inputs"]["target_check_fixture"])
        self.assertEqual(judge_plan["adapter"], "judge_aggregation_replay")
        self.assertIsNotNone(judge_plan["inputs"]["judge_fixture"])

    def test_replay_helpers_execute_representative_gate_fixtures(self) -> None:
        status, reason = ct._run_reproduction(
            "subtract_constant_from_both_sides",
            {
                "from_srepr": "Eq(x + 2, 5)",
                "to_srepr": "Eq(x, 3)",
                "args": {"constant": 2},
            },
        )
        self.assertEqual((status, reason.split()[0]), ("PASS", "subtracted"))

        target_status, _target_reason, target_payload = ct._run_target_check_fixture({
            "target": TARGET,
            "problem": _linear_problem(goal_node="n0"),
            "expected": {"status": "FAIL"},
        })
        self.assertEqual(target_status, "FAIL")
        self.assertIsNotNone(target_payload)

        judge_status, _judge_reason, normalized = ct._run_judge_fixture({
            "judge_eval": {
                "overall": "FAIL",
                "verdicts": {"target_goal_reached": {"verdict": "PASS"}},
            }
        })
        self.assertEqual(judge_status, "PASS")
        self.assertIsNotNone(normalized)


if __name__ == "__main__":
    unittest.main()
