"""Immutable JSON artifact storage for every domain workflow."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .protocols import AttemptEvidence, ProtocolError, canonical_json_bytes


_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def safe_component(value: str, name: str) -> str:
    if not isinstance(value, str) or _SAFE_COMPONENT.fullmatch(value) is None:
        raise ProtocolError(f"{name} must be a filesystem-safe identifier")
    return value


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def _path(self, relative: str | Path) -> Path:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ProtocolError("artifact path must stay below the store root")
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise ProtocolError("artifact path escapes the store root")
        return path

    def write_json_once(self, relative: str | Path, value: Any) -> Path:
        canonical_json_bytes(value)
        path = self._path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(f"immutable artifact already exists: {path}")
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp_path, path)
            except FileExistsError as exc:
                raise FileExistsError(f"immutable artifact already exists: {path}") from exc
            temp_path.unlink()
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return path

    def read_json(self, relative: str | Path) -> Any:
        return json.loads(self._path(relative).read_text())

    def write_evidence(self, evidence: AttemptEvidence) -> Path:
        run_id = safe_component(evidence.run_id, "run_id")
        plugin_id = safe_component(evidence.plugin_id, "plugin_id")
        task_id = safe_component(evidence.task_id, "task_id")
        relative = Path("runs") / run_id / "tasks" / plugin_id / task_id / f"attempt_{evidence.attempt_index:03d}.evidence.json"
        return self.write_json_once(relative, evidence.to_dict())

    def read_evidence(self, relative: str | Path) -> AttemptEvidence:
        return AttemptEvidence.from_dict(self.read_json(relative))
