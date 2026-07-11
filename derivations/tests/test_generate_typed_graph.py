from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import generate_typed_graph as generator  # noqa: E402


def rational(numerator: int, denominator: int = 1) -> dict[str, int]:
    return {"numerator": numerator, "denominator": denominator}


def public_task() -> dict:
    return {
        "schema_version": "derivation_task_public.v2",
        "id": "alg8-lin-public-001",
        "task_type": "linear_equation",
        "display": {"prompt": "Solve 2x - 3 = 7."},
        "givens": {
            "variable": "x",
            "lhs": {"coefficient": rational(2), "constant": rational(-3)},
            "rhs": {"coefficient": rational(0), "constant": rational(7)},
        },
        "requirements": [],
    }


def legacy_graph() -> dict:
    return {
        "id": "alg8-lin-public-001",
        "root_node": "n0",
        "goal_node": "n2",
        "nodes": [
            {"id": "n0", "sympy_srepr": "Eq(Add(Mul(Integer(2), Symbol('x')), Integer(-3)), Integer(7))"},
            {"id": "n1", "sympy_srepr": "Eq(Mul(Integer(2), Symbol('x')), Integer(10))"},
            {"id": "n2", "sympy_srepr": "Eq(Symbol('x'), Integer(5))"},
        ],
        "edges": [
            {
                "from": "n0",
                "to": "n1",
                "rule": "add_constant_to_both_sides",
                "rule_args": {"constant": 3},
            },
            {
                "from": "n1",
                "to": "n2",
                "rule": "divide_both_sides",
                "rule_args": {"divisor": 2},
            },
        ],
    }


class PublicTaskValidationTests(unittest.TestCase):
    def test_accepts_strict_one_solution_public_task(self) -> None:
        task = public_task()

        self.assertIs(generator.validate_public_task(task), task)

    def test_rejects_private_correctness_fields(self) -> None:
        mutations = []
        for key in ("expected", "contract_digest"):
            task = public_task()
            task[key] = {}
            mutations.append(task)
        task = public_task()
        task["display"]["answer"] = "x = 5"
        mutations.append(task)

        for task in mutations:
            with self.subTest(task=task):
                with self.assertRaises(generator.PublicTaskError):
                    generator.validate_public_task(task)

    def test_accepts_non_unique_equations_and_rejects_noncanonical_rational(self) -> None:
        no_unique_solution = public_task()
        no_unique_solution["givens"]["rhs"]["coefficient"] = rational(2)
        self.assertIs(generator.validate_public_task(no_unique_solution), no_unique_solution)

        noncanonical = public_task()
        noncanonical["givens"]["lhs"]["coefficient"] = rational(2, 2)
        with self.assertRaisesRegex(generator.PublicTaskError, "must be reduced"):
            generator.validate_public_task(noncanonical)

    def test_prompt_contains_only_public_prompt_and_typed_givens(self) -> None:
        prompt = generator.render_model_prompt(public_task())

        self.assertIn("Solve 2x - 3 = 7.", prompt)
        self.assertIn("Authoritative typed givens", prompt)
        self.assertIn('"coefficient":{"denominator":1,"numerator":2}', prompt)
        self.assertIn("alg8-lin-public-001", prompt)
        self.assertNotIn("contract_digest", prompt)
        self.assertNotIn('"expected"', prompt)
        self.assertNotIn('"answer"', prompt)


class GenerateCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.model_cwd = self.root / "model-cwd"
        self.model_cwd.mkdir()
        self.output = self.root / "candidate.json"
        self.metadata = self.root / "candidate.generation.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch.object(generator, "run_prompt")
    def test_generates_strict_graph_and_metadata_from_isolated_cwd(self, run_prompt) -> None:
        graph = legacy_graph()
        run_prompt.return_value = subprocess.CompletedProcess(
            args=["mock-model"],
            returncode=0,
            stdout=json.dumps(graph),
            stderr="",
        )

        with patch.object(generator.os, "replace", wraps=os.replace) as replace:
            actual_graph, metadata = generator.generate_candidate(
                public_task(),
                output_path=self.output,
                metadata_path=self.metadata,
                model_cwd=self.model_cwd,
                engine="codex",
                model="test-model",
                budget="1",
                timeout_s=30,
            )

        self.assertEqual(graph, actual_graph)
        self.assertEqual(graph, json.loads(self.output.read_text()))
        self.assertEqual(metadata, json.loads(self.metadata.read_text()))
        self.assertEqual(2, replace.call_count)
        run_prompt.assert_called_once()
        kwargs = run_prompt.call_args.kwargs
        self.assertEqual("codex", kwargs["engine"])
        self.assertEqual("test-model", kwargs["model"])
        self.assertEqual(self.model_cwd.resolve(), kwargs["cwd"])
        self.assertEqual("inner", kwargs["step"])
        self.assertTrue(metadata["candidate_only"])
        self.assertEqual("alg8-lin-public-001", metadata["task_id"])
        self.assertEqual(str(self.model_cwd.resolve()), metadata["model_cwd"])
        self.assertNotIn("accepted", metadata)
        self.assertNotIn("expected", json.dumps(metadata))
        self.assertNotIn("answer", json.dumps(metadata))
        self.assertEqual([], list(self.root.rglob("*.tmp")))

    @patch.object(generator, "run_prompt")
    def test_model_failure_writes_no_artifacts(self, run_prompt) -> None:
        run_prompt.return_value = subprocess.CompletedProcess(
            args=["mock-model"], returncode=7, stdout="", stderr="failure"
        )

        with self.assertRaisesRegex(generator.GenerationError, "exited 7"):
            generator.generate_candidate(
                public_task(),
                output_path=self.output,
                metadata_path=self.metadata,
                model_cwd=self.model_cwd,
                engine="codex",
                model="test-model",
                budget="1",
                timeout_s=30,
            )

        self.assertFalse(self.output.exists())
        self.assertFalse(self.metadata.exists())

    @patch.object(generator, "run_prompt")
    def test_invalid_legacy_graph_writes_no_artifacts(self, run_prompt) -> None:
        invalid = copy.deepcopy(legacy_graph())
        invalid["nodes"][0]["result"] = {"kind": "solution_set"}
        run_prompt.return_value = subprocess.CompletedProcess(
            args=["mock-model"], returncode=0, stdout=json.dumps(invalid), stderr=""
        )

        with self.assertRaisesRegex(generator.GenerationError, "strict legacy graph"):
            generator.generate_candidate(
                public_task(),
                output_path=self.output,
                metadata_path=self.metadata,
                model_cwd=self.model_cwd,
                engine="codex",
                model="test-model",
                budget="1",
                timeout_s=30,
            )

        self.assertFalse(self.output.exists())
        self.assertFalse(self.metadata.exists())

    def test_requires_existing_isolated_model_cwd_and_distinct_outputs(self) -> None:
        with self.assertRaisesRegex(generator.GenerationError, "existing directory"):
            generator.generate_candidate(
                public_task(),
                output_path=self.output,
                metadata_path=self.metadata,
                model_cwd=self.root / "missing",
                engine="codex",
                model="test-model",
                budget="1",
                timeout_s=30,
            )

        with self.assertRaisesRegex(generator.GenerationError, "different files"):
            generator.generate_candidate(
                public_task(),
                output_path=self.output,
                metadata_path=self.output,
                model_cwd=self.model_cwd,
                engine="codex",
                model="test-model",
                budget="1",
                timeout_s=30,
            )


if __name__ == "__main__":
    unittest.main()
