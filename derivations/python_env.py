"""Python interpreter helpers for derivation CLI entrypoints."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def invocation_path(path: str | Path) -> Path:
    """Return the absolute invocation path without resolving symlinks."""
    return Path(path).expanduser().absolute()


def should_reexec(candidate: str | Path, current: str | Path | None = None) -> bool:
    """True when candidate should be exec'd as a distinct interpreter path.

    Do not compare resolved paths here. A venv Python is often a symlink to the
    base interpreter, but invoking the symlink is what activates the venv prefix
    and site-packages.
    """
    candidate_path = invocation_path(candidate)
    current_path = invocation_path(current or sys.executable)
    return candidate_path.exists() and candidate_path != current_path


def derivation_python_candidates(anchor: Path, env_var: str = "DERIVATION_PYTHON") -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get(env_var)
    if configured:
        candidates.append(Path(configured))
    for parent in anchor.resolve().parents:
        candidates.append(parent / "derivations" / ".venv" / "bin" / "python")
        candidates.append(parent / ".venv" / "bin" / "python")
    return candidates


def reexec_with_derivation_python(flag_env: str, anchor: Path) -> None:
    if os.environ.get(flag_env) == "1":
        return
    for candidate in derivation_python_candidates(anchor):
        if should_reexec(candidate):
            os.environ[flag_env] = "1"
            os.execv(str(candidate), [str(candidate), *sys.argv])
