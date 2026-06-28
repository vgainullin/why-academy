from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DERIVATIONS = ROOT / "derivations"
sys.path.insert(0, str(DERIVATIONS))

from python_env import should_reexec  # noqa: E402


class PythonEnvTests(unittest.TestCase):

    def test_same_invocation_path_does_not_reexec(self) -> None:
        self.assertFalse(should_reexec(Path(sys.executable), current=Path(sys.executable)))

    def test_symlink_to_current_binary_still_reexecs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "python"
            link.symlink_to(Path(sys.executable).resolve())
            self.assertEqual(link.resolve(), Path(sys.executable).resolve())
            self.assertTrue(should_reexec(link, current=Path(sys.executable).resolve()))


if __name__ == "__main__":
    unittest.main()
