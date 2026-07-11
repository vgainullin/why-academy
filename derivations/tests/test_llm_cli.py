from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

import llm_cli  # noqa: E402


class OpenRouterEngineTests(unittest.TestCase):
    def test_openrouter_requires_api_key(self) -> None:
        old_key = os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            with self.assertRaisesRegex(llm_cli.LLMEngineError, "OPENROUTER_API_KEY"):
                llm_cli.run_prompt("hello", engine="openrouter", model="x/test")
        finally:
            if old_key is not None:
                os.environ["OPENROUTER_API_KEY"] = old_key

    def test_openrouter_requires_model(self) -> None:
        old_key = os.environ.get("OPENROUTER_API_KEY")
        old_model = os.environ.pop("OPENROUTER_MODEL", None)
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        try:
            with self.assertRaisesRegex(llm_cli.LLMEngineError, "model"):
                llm_cli.run_prompt("hello", engine="openrouter")
        finally:
            if old_key is None:
                os.environ.pop("OPENROUTER_API_KEY", None)
            else:
                os.environ["OPENROUTER_API_KEY"] = old_key
            if old_model is not None:
                os.environ["OPENROUTER_MODEL"] = old_model


class CodexCommandTests(unittest.TestCase):
    def test_skip_git_repo_check_requires_explicit_opt_in(self) -> None:
        cwd = Path("/tmp/not-a-repository")
        with patch.dict(os.environ, {}, clear=True):
            self.assertNotIn("--skip-git-repo-check", llm_cli._codex_base_cmd(cwd, "read-only"))
        with patch.dict(os.environ, {"CODEX_SKIP_GIT_REPO_CHECK": "1"}, clear=True):
            self.assertIn("--skip-git-repo-check", llm_cli._codex_base_cmd(cwd, "read-only"))


if __name__ == "__main__":
    unittest.main()
