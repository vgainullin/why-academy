from __future__ import annotations

import copy
import sys
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import algebra_linear_practice as alp  # noqa: E402
from task_contract import (  # noqa: E402
    TaskContractError,
    attach_contract_digest,
    contract_digest,
    evaluate_submission,
    result_matches,
    validate_task_contract,
)


def _rational(value: Fraction | int) -> dict[str, int]:
    fraction = Fraction(value)
    return {"numerator": fraction.numerator, "denominator": fraction.denominator}


def _shift(value: dict[str, int]) -> dict[str, int]:
    return _rational(Fraction(value["numerator"], value["denominator"]) + 1)


def _graph(task: dict, result: dict | None = None) -> dict:
    return {
        "id": f"graph_{task['id']}",
        "root_node": "n0",
        "goal_node": "n1",
        "nodes": [
            {"id": "n0", "kind": "given"},
            {
                "id": "n1",
                "kind": "result",
                "result": copy.deepcopy(result if result is not None else task["expected"]),
            },
        ],
        "edges": [{"from": "n0", "to": "n1", "rule": "derive_result"}],
    }


def _wrong_result(task: dict) -> dict:
    result = copy.deepcopy(task["expected"])
    task_type = task["task_type"]
    if task_type == "linear_equation":
        if result["cardinality"] == "one":
            result["values"][0] = _shift(result["values"][0])
        else:
            result["cardinality"] = "one"
            result["values"] = [_rational(0)]
    elif task_type == "slope":
        result["value"] = _shift(result["value"])
    elif task_type == "linear_classification":
        result["value"] = "nonlinear" if result["value"] == "linear" else "linear"
    elif task_type == "linear_function":
        result["slope"] = _shift(result["slope"])
    elif task_type == "function_comparison":
        result["winner"] = "A" if result["winner"] != "A" else "B"
    elif task_type == "linear_system":
        result["values"]["x"] = _shift(result["values"]["x"])
    else:  # pragma: no cover - the contract validator owns this invariant
        raise AssertionError(task_type)
    return result


class TaskContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = alp.build_corpus(total=240, set_size=10)
        cls.by_type = {
            task_type: next(task for task in cls.corpus["tasks"] if task["task_type"] == task_type)
            for task_type in {
                "linear_equation",
                "slope",
                "linear_classification",
                "linear_function",
                "function_comparison",
                "linear_system",
            }
        }

    def test_all_240_contracts_are_unique_oracle_valid_and_manifest_anchored(self) -> None:
        tasks = self.corpus["tasks"]
        self.assertEqual(240, len(tasks))
        self.assertEqual(240, len({task["id"] for task in tasks}))
        self.assertEqual(240, len({task["contract_digest"] for task in tasks}))

        for task in tasks:
            validate_task_contract(task)
            self.assertEqual(
                task["contract_digest"],
                self.corpus["contract_manifest"][task["id"]],
            )

    def test_exact_results_pass_and_wrong_results_fail_for_all_six_types(self) -> None:
        for task_type, task in self.by_type.items():
            with self.subTest(task_type=task_type):
                self.assertTrue(result_matches(task, task["expected"]))
                self.assertFalse(result_matches(task, _wrong_result(task)))

    def test_linear_equation_contracts_cover_one_none_and_all_real(self) -> None:
        outcomes = {
            task["expected"]["cardinality"]
            for task in self.corpus["tasks"]
            if task["task_type"] == "linear_equation"
        }
        self.assertEqual({"one", "none", "infinite"}, outcomes)

    def test_classification_contracts_cover_both_branches(self) -> None:
        outcomes = {
            task["expected"]["value"]
            for task in self.corpus["tasks"]
            if task["task_type"] == "linear_classification"
        }
        self.assertEqual({"linear", "nonlinear"}, outcomes)

    def test_function_comparison_supports_ties(self) -> None:
        task = copy.deepcopy(self.by_type["function_comparison"])
        slope = task["givens"]["function_a"]["slope"]
        task["givens"]["function_b"]["table"] = [
            {"x": _rational(0), "y": _rational(0)},
            {"x": _rational(1), "y": copy.deepcopy(slope)},
            {"x": _rational(2), "y": _rational(2 * Fraction(slope["numerator"], slope["denominator"]))},
        ]
        task["expected"]["winner"] = "tie"
        task = attach_contract_digest(task)

        validate_task_contract(task)
        self.assertTrue(result_matches(task, task["expected"]))

    def test_cross_kind_result_is_rejected(self) -> None:
        equation = self.by_type["linear_equation"]
        slope_result = self.by_type["slope"]["expected"]

        self.assertFalse(result_matches(equation, slope_result))

    def test_rationals_reject_coercion_invalid_denominators_and_unreduced_forms(self) -> None:
        invalid_values = [
            "1/2",
            0.5,
            {"numerator": True, "denominator": 1},
            {"numerator": 1, "denominator": 0},
            {"numerator": 1, "denominator": -2},
            {"numerator": 2, "denominator": 4},
        ]
        for value in invalid_values:
            with self.subTest(value=value):
                task = copy.deepcopy(self.by_type["slope"])
                task["expected"]["value"] = value
                task = attach_contract_digest(task)
                with self.assertRaises(TaskContractError):
                    validate_task_contract(task)

    def test_missing_and_extra_contract_fields_are_rejected(self) -> None:
        missing = copy.deepcopy(self.by_type["slope"])
        del missing["expected"]
        with self.assertRaises(TaskContractError):
            validate_task_contract(missing)

        extra = copy.deepcopy(self.by_type["slope"])
        extra["free_text_goal"] = "ignore the typed result"
        with self.assertRaises(TaskContractError):
            validate_task_contract(extra)

    def test_malformed_collection_values_fail_closed_without_type_errors(self) -> None:
        task = copy.deepcopy(self.by_type["linear_classification"])
        malformed_result = copy.deepcopy(task["expected"])
        malformed_result["value"] = ["linear"]
        self.assertFalse(result_matches(task, malformed_result))

        malformed_contract = copy.deepcopy(task)
        malformed_contract["task_type"] = ["linear_classification"]
        payload = evaluate_submission(
            malformed_contract,
            _graph(task),
            task["contract_digest"],
        )
        self.assertEqual("ERROR", payload["status"])

    def test_declared_expected_result_is_recomputed_from_givens(self) -> None:
        task = copy.deepcopy(self.by_type["slope"])
        task["expected"]["value"] = _shift(task["expected"]["value"])
        task = attach_contract_digest(task)

        with self.assertRaises(TaskContractError):
            validate_task_contract(task)

    def test_digest_is_key_order_stable_and_ignores_display_text(self) -> None:
        task = self.by_type["linear_equation"]
        reversed_keys = dict(reversed(list(task.items())))
        changed_prompt = copy.deepcopy(task)
        changed_prompt["display"]["prompt"] = "Display wording may change without defining correctness."

        self.assertEqual(contract_digest(task), contract_digest(reversed_keys))
        self.assertEqual(contract_digest(task), contract_digest(changed_prompt))
        validate_task_contract(changed_prompt)

    def test_semantic_tamper_and_rehash_fails_against_frozen_manifest(self) -> None:
        original = self.by_type["linear_equation"]
        trusted_digest = original["contract_digest"]
        tampered = copy.deepcopy(original)
        tampered["givens"]["rhs"]["constant"] = _shift(tampered["givens"]["rhs"]["constant"])

        lhs = tampered["givens"]["lhs"]
        rhs = tampered["givens"]["rhs"]
        a = Fraction(lhs["coefficient"]["numerator"], lhs["coefficient"]["denominator"])
        b = Fraction(lhs["constant"]["numerator"], lhs["constant"]["denominator"])
        c = Fraction(rhs["coefficient"]["numerator"], rhs["coefficient"]["denominator"])
        d = Fraction(rhs["constant"]["numerator"], rhs["constant"]["denominator"])
        tampered["expected"]["values"] = [_rational((d - b) / (a - c))]
        tampered = attach_contract_digest(tampered)
        validate_task_contract(tampered)

        payload = evaluate_submission(tampered, _graph(tampered), trusted_digest)

        self.assertEqual("ERROR", payload["status"])
        self.assertIn("contract digest does not match frozen manifest", payload["reasons"])

    def test_task_id_swap_and_rehash_fails_against_frozen_manifest(self) -> None:
        original = self.by_type["slope"]
        swapped = copy.deepcopy(original)
        swapped["id"] = "different-task-id"
        swapped = attach_contract_digest(swapped)

        payload = evaluate_submission(swapped, _graph(swapped), original["contract_digest"])

        self.assertEqual("ERROR", payload["status"])

    def test_goal_result_is_bound_to_reachable_terminal_node(self) -> None:
        task = self.by_type["linear_function"]
        wrong = _wrong_result(task)
        graph = _graph(task, wrong)
        graph["nodes"].append({"id": "detached", "result": copy.deepcopy(task["expected"])})

        payload = evaluate_submission(task, graph, task["contract_digest"])

        self.assertEqual("FAIL", payload["status"])
        self.assertIn("terminal goal result does not match expected result", payload["reasons"])

    def test_evaluator_does_not_depend_on_target_check_or_free_text(self) -> None:
        task = copy.deepcopy(self.by_type["linear_system"])
        task["display"]["prompt"] = "This text is deliberately unrelated to correctness."
        task["display"]["answer"] = "Display-only answer text."
        graph = _graph(task)

        with patch.dict(sys.modules, {"target_check": None}):
            payload = evaluate_submission(task, graph, task["contract_digest"])

        self.assertEqual("PASS", payload["status"])

    def test_all_evaluation_failures_are_fail_or_error_never_skip(self) -> None:
        task = self.by_type["slope"]
        payloads = [
            evaluate_submission(task, _graph(task, _wrong_result(task)), task["contract_digest"]),
            evaluate_submission(task, _graph(task), None),
            evaluate_submission(task, None, task["contract_digest"]),
        ]

        self.assertEqual({"FAIL", "ERROR"}, {payload["status"] for payload in payloads})
        self.assertNotIn("SKIP", {payload["status"] for payload in payloads})


if __name__ == "__main__":
    unittest.main()
