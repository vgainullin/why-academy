#!/usr/bin/env python3
"""Load an externally pinned Grade 8 task bundle for trusted evaluation.

The expected bundle hash is a trust input supplied by the caller.  Nothing in
the bundle, including its embedded contract manifest, can establish that trust
on its own.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from algebra_linear_practice import verify_corpus
from task_contract import (
    CORPUS_SCHEMA_VERSION,
    TASK_CONTRACT_VERSION,
    TaskContractError,
    validate_task_contract,
)


EXPECTED_TASK_COUNT = 240
SELECTION_SCHEMA_VERSION = "frozen_task_selection.v1"
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


class FrozenTaskStoreError(ValueError):
    """The frozen bundle or a requested task selection is invalid."""


def _normalize_sha256(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise FrozenTaskStoreError("expected_sha256 must be a full SHA-256 digest")
    digest = value.removeprefix("sha256:")
    if _SHA256_RE.fullmatch(digest) is None:
        raise FrozenTaskStoreError("expected_sha256 must contain exactly 64 hexadecimal characters")
    return digest.lower()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise FrozenTaskStoreError(f"bundle JSON contains duplicate key {key!r}")
        value[key] = item
    return value


def _reject_nonfinite(value: str) -> None:
    raise FrozenTaskStoreError(f"bundle JSON contains non-finite number {value!r}")


def _load_strict_json(raw: bytes) -> Any:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FrozenTaskStoreError("bundle is not valid UTF-8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_nonfinite,
        )
    except FrozenTaskStoreError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise FrozenTaskStoreError(f"bundle is not valid strict JSON: {exc}") from exc


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise FrozenTaskStoreError(f"value is not canonical JSON: {exc}") from exc


@dataclass(frozen=True, slots=True)
class FrozenTaskStore:
    """An immutable, byte-pinned snapshot of the Grade 8 task corpus."""

    bundle_path: Path
    bundle_sha256: str
    _task_bytes: Mapping[str, bytes]
    _task_digests: Mapping[str, str]
    _task_ids: tuple[str, ...]

    @classmethod
    def load(
        cls,
        bundle_path: str | Path,
        expected_sha256: str,
    ) -> "FrozenTaskStore":
        """Load and fully validate a bundle whose raw bytes match the trusted pin."""
        expected = _normalize_sha256(expected_sha256)
        path = Path(bundle_path).expanduser()
        try:
            raw = path.read_bytes()
        except (OSError, ValueError) as exc:
            raise FrozenTaskStoreError(f"cannot read frozen task bundle {path}: {exc}") from exc

        actual = hashlib.sha256(raw).hexdigest()
        if not hmac.compare_digest(actual, expected):
            raise FrozenTaskStoreError(
                f"bundle SHA-256 mismatch: expected {expected}, got {actual}"
            )

        bundle = _load_strict_json(raw)
        if not isinstance(bundle, dict):
            raise FrozenTaskStoreError("bundle must be a JSON object")
        if bundle.get("schema_version") != CORPUS_SCHEMA_VERSION:
            raise FrozenTaskStoreError(
                f"bundle schema_version must be {CORPUS_SCHEMA_VERSION!r}"
            )
        if bundle.get("task_contract_version") != TASK_CONTRACT_VERSION:
            raise FrozenTaskStoreError(
                f"bundle task_contract_version must be {TASK_CONTRACT_VERSION!r}"
            )

        tasks = bundle.get("tasks")
        if not isinstance(tasks, list) or len(tasks) != EXPECTED_TASK_COUNT:
            raise FrozenTaskStoreError(
                f"bundle must contain exactly {EXPECTED_TASK_COUNT} tasks"
            )
        total_tasks = bundle.get("total_tasks")
        if (
            not isinstance(total_tasks, int)
            or isinstance(total_tasks, bool)
            or total_tasks != EXPECTED_TASK_COUNT
        ):
            raise FrozenTaskStoreError(
                f"bundle total_tasks must be exactly {EXPECTED_TASK_COUNT}"
            )

        manifest = bundle.get("contract_manifest")
        if not isinstance(manifest, dict):
            raise FrozenTaskStoreError("bundle contract_manifest must be an object")

        task_by_id: dict[str, dict[str, Any]] = {}
        for index, task in enumerate(tasks):
            if not isinstance(task, dict):
                raise FrozenTaskStoreError(f"tasks[{index}] must be an object")
            task_id = task.get("id")
            if not isinstance(task_id, str) or not task_id:
                raise FrozenTaskStoreError(f"tasks[{index}].id must be a non-empty string")
            if task_id in task_by_id:
                raise FrozenTaskStoreError(f"duplicate task id {task_id!r}")
            try:
                validate_task_contract(task)
            except (TaskContractError, KeyError, TypeError, ValueError) as exc:
                raise FrozenTaskStoreError(f"task {task_id!r} is invalid: {exc}") from exc
            task_by_id[task_id] = task

        if set(manifest) != set(task_by_id):
            raise FrozenTaskStoreError("contract_manifest task ids do not match bundle tasks")
        for task_id, task in task_by_id.items():
            manifest_digest = manifest.get(task_id)
            if not isinstance(manifest_digest, str):
                raise FrozenTaskStoreError(
                    f"contract_manifest digest for {task_id!r} must be a string"
                )
            if not hmac.compare_digest(manifest_digest, task["contract_digest"]):
                raise FrozenTaskStoreError(
                    f"contract_manifest digest mismatch for task {task_id!r}"
                )

        try:
            verify_corpus(bundle)
        except Exception as exc:
            raise FrozenTaskStoreError(f"bundle corpus validation failed: {exc}") from exc

        task_ids = tuple(task["id"] for task in tasks)
        task_bytes = MappingProxyType(
            {task_id: _canonical_bytes(task_by_id[task_id]) for task_id in task_ids}
        )
        task_digests = MappingProxyType(
            {task_id: task_by_id[task_id]["contract_digest"] for task_id in task_ids}
        )
        return cls(
            bundle_path=path.resolve(),
            bundle_sha256=actual,
            _task_bytes=task_bytes,
            _task_digests=task_digests,
            _task_ids=task_ids,
        )

    @property
    def task_count(self) -> int:
        return len(self._task_ids)

    @property
    def task_ids(self) -> tuple[str, ...]:
        return self._task_ids

    def get_task(self, task_id: str) -> dict[str, Any]:
        """Return a fresh deep copy of one frozen task contract."""
        if not isinstance(task_id, str) or not task_id:
            raise FrozenTaskStoreError("task_id must be a non-empty string")
        raw = self._task_bytes.get(task_id)
        if raw is None:
            raise FrozenTaskStoreError(f"unknown frozen task id {task_id!r}")
        task = json.loads(raw)
        if not isinstance(task, dict):  # pragma: no cover - canonicalized internally
            raise FrozenTaskStoreError(f"frozen task {task_id!r} is not an object")
        return task

    def selected_task_list_digest(self, ids: Iterable[str]) -> str:
        """Digest an ordered, non-empty selection against this exact bundle."""
        if isinstance(ids, (str, bytes)):
            raise FrozenTaskStoreError("selected task ids must be an iterable of task ids")
        try:
            selected = list(ids)
        except TypeError as exc:
            raise FrozenTaskStoreError("selected task ids must be iterable") from exc
        if not selected:
            raise FrozenTaskStoreError("selected task ids must not be empty")

        seen: set[str] = set()
        task_refs = []
        for index, task_id in enumerate(selected):
            if not isinstance(task_id, str) or not task_id:
                raise FrozenTaskStoreError(
                    f"selected task id at index {index} must be a non-empty string"
                )
            if task_id in seen:
                raise FrozenTaskStoreError(f"duplicate selected task id {task_id!r}")
            if task_id not in self._task_bytes:
                raise FrozenTaskStoreError(f"unknown frozen task id {task_id!r}")
            seen.add(task_id)
            task_refs.append(
                {"id": task_id, "contract_digest": self._task_digests[task_id]}
            )

        payload = {
            "schema_version": SELECTION_SCHEMA_VERSION,
            "bundle_sha256": self.bundle_sha256,
            "tasks": task_refs,
        }
        return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()
