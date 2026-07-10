from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import algebra_linear_practice as alp  # noqa: E402


class AlgebraLinearPracticeTests(unittest.TestCase):
    def test_generated_corpus_is_balanced_and_verifiable(self) -> None:
        corpus = alp.build_corpus(total=240, set_size=10)

        alp.verify_corpus(corpus)

        self.assertEqual(240, corpus["total_tasks"])
        self.assertEqual(24, corpus["daily_set_count"])
        self.assertEqual(10, corpus["set_size"])
        self.assertEqual("grade8_algebra_linear_practice.v3", corpus["schema_version"])
        self.assertEqual("derivation_task.v1", corpus["task_contract_version"])
        counts = {}
        for task in corpus["tasks"]:
            strand = task["metadata"]["strand"]
            counts[strand] = counts.get(strand, 0) + 1
        self.assertEqual({strand: 20 for strand in alp.STRANDS}, counts)

    def test_generated_corpus_covers_grade_8_algebra_standards(self) -> None:
        corpus = alp.build_corpus(total=240, set_size=10)

        used = {
            standard
            for task in corpus["tasks"]
            for standard in task["metadata"]["standards"]
        }

        self.assertIn("8.EE.C.7", used)
        self.assertIn("8.EE.C.8", used)
        self.assertIn("8.F.A.2", used)
        self.assertIn("8.F.A.3", used)
        self.assertIn("8.F.B.4", used)
        self.assertIn("8.EE.B.5", used)

    def test_checked_in_corpus_matches_generator(self) -> None:
        corpus_path = DERIVATIONS / "practice" / "algebra_linear_8th_grade_summer.json"
        if not corpus_path.exists():
            self.skipTest("practice corpus has not been generated yet")

        expected = json.loads(json.dumps(alp.build_corpus(total=240, set_size=10), sort_keys=True))
        actual = json.loads(corpus_path.read_text())

        self.assertEqual(expected, actual)
        alp.verify_corpus(actual)

    def test_typed_corpus_separates_display_from_correctness(self) -> None:
        corpus_path = DERIVATIONS / "practice" / "algebra_linear_8th_grade_summer.json"
        if not corpus_path.exists():
            self.skipTest("practice corpus has not been generated yet")

        corpus = json.loads(corpus_path.read_text())

        for task in corpus["tasks"]:
            self.assertTrue(task["display"]["prompt"])
            self.assertTrue(task["display"]["answer"])
            self.assertTrue(task["pedagogy"]["reference_steps"])
            self.assertIsInstance(task["givens"], dict)
            self.assertIsInstance(task["expected"], dict)
            self.assertNotIn("target_prompt", task)
            self.assertEqual(
                task["contract_digest"],
                corpus["contract_manifest"][task["id"]],
            )

    def test_markdown_contains_all_daily_sets_and_answers(self) -> None:
        corpus = alp.build_corpus(total=240, set_size=10)
        markdown = alp.render_markdown(corpus)

        self.assertIn("Total problems: 240", markdown)
        self.assertIn("8.EE.C.8", markdown)
        self.assertIn("linear functions", markdown)
        self.assertEqual(48, markdown.count("### Day "))
        self.assertIn("## Answer Key", markdown)
        self.assertIn("slope =", markdown)


if __name__ == "__main__":
    unittest.main()
