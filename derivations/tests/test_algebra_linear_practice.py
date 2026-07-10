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

        self.assertEqual(240, corpus["total_problems"])
        self.assertEqual(24, corpus["daily_set_count"])
        self.assertEqual(10, corpus["set_size"])
        self.assertEqual("grade8_algebra_linear_practice.v2", corpus["schema_version"])
        counts = {}
        for problem in corpus["problems"]:
            counts[problem["strand"]] = counts.get(problem["strand"], 0) + 1
        self.assertEqual({strand: 20 for strand in alp.STRANDS}, counts)

    def test_generated_corpus_covers_grade_8_algebra_standards(self) -> None:
        corpus = alp.build_corpus(total=240, set_size=10)

        used = {standard for problem in corpus["problems"] for standard in problem["standards"]}

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

    def test_typed_corpus_retains_answer_steps_and_target_prompt(self) -> None:
        corpus_path = DERIVATIONS / "practice" / "algebra_linear_8th_grade_summer.json"
        if not corpus_path.exists():
            self.skipTest("practice corpus has not been generated yet")

        corpus = json.loads(corpus_path.read_text())

        for problem in corpus["problems"]:
            self.assertTrue(problem["answer"])
            self.assertTrue(problem["steps"])
            self.assertTrue(problem["target_prompt"])
            self.assertIsInstance(problem["structured"], dict)

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
