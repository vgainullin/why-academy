"""Adapters from existing gate records into the neutral evidence contract."""
from __future__ import annotations

from typing import Any, Mapping

from .protocols import AttemptEvidence, GateResult, ProtocolError, RunSpec, final_status


def evidence_from_gate_records(
    *,
    spec: RunSpec,
    plugin_id: str,
    task_id: str,
    task_digest: str,
    attempt_index: int,
    candidate_digest: str | None,
    gates: Mapping[str, Mapping[str, Any]],
    artifact_refs: Mapping[str, str] | None = None,
) -> AttemptEvidence:
    """Normalize a legacy named-gate mapping without domain-specific logic."""
    if not isinstance(gates, Mapping):
        raise ProtocolError("legacy gates must be an object")
    normalized = []
    for name, record in gates.items():
        if not isinstance(name, str) or not name or not isinstance(record, Mapping):
            raise ProtocolError("legacy gates must map names to objects")
        status = record.get("status")
        if status == "NOT_RUN":
            continue
        if status not in {"PASS", "FAIL", "ERROR"}:
            status = "ERROR"
        raw_reasons = record.get("reasons", [])
        reasons = (
            tuple(str(reason) for reason in raw_reasons)
            if isinstance(raw_reasons, list)
            else ("gate reasons were not a list",)
        )
        metrics = {
            key: value
            for key, value in record.items()
            if key not in {"status", "reasons"}
        }
        normalized.append(
            GateResult(name=name, status=status, reasons=reasons, metrics=metrics)
        )
    if not normalized:
        normalized.append(
            GateResult(
                name="evaluation",
                status="ERROR",
                reasons=("legacy workflow emitted no completed gates",),
            )
        )
    gate_tuple = tuple(normalized)
    return AttemptEvidence(
        run_id=spec.run_id,
        cohort_id=spec.cohort_id,
        arm=spec.arm,
        plugin_id=plugin_id,
        task_id=task_id,
        task_digest=task_digest,
        attempt_index=attempt_index,
        candidate_digest=candidate_digest,
        status=final_status(gate_tuple),
        gates=gate_tuple,
        provenance=spec.provenance,
        artifact_refs=artifact_refs or {},
    )
