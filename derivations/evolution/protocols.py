"""Versioned, domain-neutral contracts for evolution workflows."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


EVIDENCE_SCHEMA_VERSION = "evolution_attempt_evidence.v1"
ALLOWED_STATUSES = frozenset({"PASS", "FAIL", "ERROR"})


class ProtocolError(ValueError):
    """A kernel protocol value is malformed or internally inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"value is not canonical JSON: {exc}") from exc


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _string_tuple(values: Any, path: str) -> tuple[str, ...]:
    if values is None:
        return ()
    _require(isinstance(values, (list, tuple)), f"{path} must be a list of strings")
    _require(all(isinstance(value, str) and value for value in values), f"{path} entries must be non-empty strings")
    return tuple(values)


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    status: str
    reasons: tuple[str, ...] = ()
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require(isinstance(self.name, str) and self.name, "gate name must be a non-empty string")
        _require(self.status in ALLOWED_STATUSES, f"gate {self.name!r} has invalid status {self.status!r}")
        _string_tuple(self.reasons, f"gate {self.name}.reasons")
        _require(isinstance(self.metrics, Mapping), f"gate {self.name}.metrics must be an object")
        canonical_json_bytes(dict(self.metrics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "reasons": list(self.reasons),
            "metrics": dict(self.metrics),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GateResult":
        _require(isinstance(value, Mapping), "gate must be an object")
        return cls(
            name=value.get("name"),
            status=value.get("status"),
            reasons=_string_tuple(value.get("reasons", []), "gate.reasons"),
            metrics=value.get("metrics", {}),
        )


def final_status(gates: tuple[GateResult, ...]) -> str:
    _require(bool(gates), "at least one gate result is required")
    statuses = {gate.status for gate in gates}
    if "ERROR" in statuses:
        return "ERROR"
    if statuses == {"PASS"}:
        return "PASS"
    return "FAIL"


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    plugin_id: str
    evaluator_version: str
    task_id: str
    task_digest: str
    candidate_digest: str
    status: str
    gates: tuple[GateResult, ...]
    outputs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("plugin_id", self.plugin_id),
            ("evaluator_version", self.evaluator_version),
            ("task_id", self.task_id),
            ("task_digest", self.task_digest),
            ("candidate_digest", self.candidate_digest),
        ):
            _require(isinstance(value, str) and value, f"evaluation {name} must be a non-empty string")
        _require(isinstance(self.gates, tuple) and self.gates, "evaluation gates must be a non-empty tuple")
        _require(self.status == final_status(self.gates), "evaluation status must match its gate results")
        _require(isinstance(self.outputs, Mapping), "evaluation outputs must be an object")
        canonical_json_bytes(dict(self.outputs))

    @classmethod
    def create(
        cls,
        *,
        plugin_id: str,
        evaluator_version: str,
        task_id: str,
        task_digest: str,
        candidate_digest: str,
        gates: tuple[GateResult, ...],
        outputs: Mapping[str, Any] | None = None,
    ) -> "EvaluationResult":
        return cls(
            plugin_id=plugin_id,
            evaluator_version=evaluator_version,
            task_id=task_id,
            task_digest=task_digest,
            candidate_digest=candidate_digest,
            status=final_status(gates),
            gates=gates,
            outputs=outputs or {},
        )


@dataclass(frozen=True, slots=True)
class RunSpec:
    run_id: str
    cohort_id: str
    arm: str
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (("run_id", self.run_id), ("cohort_id", self.cohort_id), ("arm", self.arm)):
            _require(isinstance(value, str) and value, f"run {name} must be a non-empty string")
        _require(isinstance(self.provenance, Mapping), "run provenance must be an object")
        canonical_json_bytes(dict(self.provenance))


@dataclass(frozen=True, slots=True)
class AttemptEvidence:
    run_id: str
    cohort_id: str
    arm: str
    plugin_id: str
    task_id: str
    task_digest: str
    attempt_index: int
    candidate_digest: str | None
    status: str
    gates: tuple[GateResult, ...]
    provenance: Mapping[str, Any] = field(default_factory=dict)
    artifact_refs: Mapping[str, str] = field(default_factory=dict)
    schema_version: str = EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.schema_version == EVIDENCE_SCHEMA_VERSION, "unsupported evidence schema version")
        for name, value in (
            ("run_id", self.run_id),
            ("cohort_id", self.cohort_id),
            ("arm", self.arm),
            ("plugin_id", self.plugin_id),
            ("task_id", self.task_id),
            ("task_digest", self.task_digest),
        ):
            _require(isinstance(value, str) and value, f"evidence {name} must be a non-empty string")
        _require(type(self.attempt_index) is int and self.attempt_index >= 0, "attempt_index must be a non-negative integer")
        _require(self.candidate_digest is None or (isinstance(self.candidate_digest, str) and self.candidate_digest), "candidate_digest must be null or a non-empty string")
        _require(self.status == final_status(self.gates), "evidence status must match its gate results")
        _require(isinstance(self.provenance, Mapping), "evidence provenance must be an object")
        _require(isinstance(self.artifact_refs, Mapping), "evidence artifact_refs must be an object")
        _require(all(isinstance(key, str) and key and isinstance(value, str) and value for key, value in self.artifact_refs.items()), "artifact_refs must map non-empty strings to non-empty strings")
        canonical_json_bytes(dict(self.provenance))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "cohort_id": self.cohort_id,
            "arm": self.arm,
            "plugin_id": self.plugin_id,
            "task_id": self.task_id,
            "task_digest": self.task_digest,
            "attempt_index": self.attempt_index,
            "candidate_digest": self.candidate_digest,
            "status": self.status,
            "gates": [gate.to_dict() for gate in self.gates],
            "provenance": dict(self.provenance),
            "artifact_refs": dict(self.artifact_refs),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AttemptEvidence":
        _require(isinstance(value, Mapping), "evidence must be an object")
        raw_gates = value.get("gates")
        _require(isinstance(raw_gates, list), "evidence gates must be a list")
        return cls(
            schema_version=value.get("schema_version"),
            run_id=value.get("run_id"),
            cohort_id=value.get("cohort_id"),
            arm=value.get("arm"),
            plugin_id=value.get("plugin_id"),
            task_id=value.get("task_id"),
            task_digest=value.get("task_digest"),
            attempt_index=value.get("attempt_index"),
            candidate_digest=value.get("candidate_digest"),
            status=value.get("status"),
            gates=tuple(GateResult.from_dict(gate) for gate in raw_gates),
            provenance=value.get("provenance", {}),
            artifact_refs=value.get("artifact_refs", {}),
        )


@runtime_checkable
class DomainPlugin(Protocol):
    """The only domain-specific surface visible to the kernel."""

    plugin_id: str
    plugin_version: str

    def task_id(self, task: Mapping[str, Any]) -> str: ...

    def task_digest(self, task: Mapping[str, Any]) -> str: ...

    def validate_task(self, task: Mapping[str, Any]) -> None: ...

    def public_task(self, task: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def evaluate(
        self,
        task: Mapping[str, Any],
        candidate: Any,
        candidate_digest: str,
    ) -> EvaluationResult: ...
