"""Translate legacy derivation batch artifacts into neutral attempt evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from evolution.artifacts import ArtifactStore
from evolution.protocols import (
    AttemptEvidence,
    GateResult,
    ProtocolError,
    RunSpec,
    canonical_digest,
)


PLUGIN_ID = "derivation_graph"
ADAPTER_VERSION = "derivation_graph_batch_adapter.v1"
ERROR_STATUSES = frozenset({
    "missing",
    "problem_missing",
    "verifier_didnt_run",
    "worker_error",
})


def target_identity(target: str, target_index: int) -> tuple[str, str]:
    if not isinstance(target, str) or not target.strip():
        raise ProtocolError("target must be a non-empty string")
    if type(target_index) is not int or target_index < 0:
        raise ProtocolError("target_index must be a non-negative integer")
    contract = {"target_index": target_index, "target": target}
    digest = canonical_digest(contract)
    return f"target-{target_index:03d}-{digest.removeprefix('sha256:')[:16]}", digest


def _candidate_digest(problem_path: Path) -> str | None:
    if not problem_path.exists():
        return None
    try:
        return canonical_digest(json.loads(problem_path.read_text()))
    except Exception:
        return "sha256:" + hashlib.sha256(problem_path.read_bytes()).hexdigest()


def _status(legacy_status: str) -> str:
    if legacy_status == "PASS":
        return "PASS"
    if legacy_status in ERROR_STATUSES or legacy_status.startswith("worker_error"):
        return "ERROR"
    return "FAIL"


def _provenance(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "batch_id",
        "experiment_id",
        "treatment_id",
        "inner_mode",
        "normalization_mode",
        "inner_engine",
        "inner_model",
        "judge_engine",
        "judge_model",
        "evolve_engine",
        "evolve_model",
        "prompt_version",
        "validator_version",
    )
    return {
        "adapter_version": ADAPTER_VERSION,
        "batch": {key: checkpoint[key] for key in fields if key in checkpoint},
    }


def run_spec_from_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    batch_id: str,
    cohort_id: str | None = None,
    arm: str | None = None,
) -> RunSpec:
    resolved_cohort = cohort_id or checkpoint.get("experiment_id") or batch_id
    resolved_arm = arm or checkpoint.get("treatment_id")
    if not resolved_arm:
        resolved_arm = "control" if checkpoint.get("experiment_id") else checkpoint.get("inner_mode") or "candidate"
    return RunSpec(
        run_id=str(checkpoint.get("batch_id") or batch_id),
        cohort_id=str(resolved_cohort),
        arm=str(resolved_arm),
        provenance=_provenance(checkpoint),
    )


def build_target_evidence(
    target_dir: Path,
    *,
    target: str,
    target_index: int,
    spec: RunSpec,
) -> tuple[AttemptEvidence, ...]:
    task_id, task_digest = target_identity(target, target_index)
    attempts = []
    for iter_dir in sorted(target_dir.glob("iter_*")):
        try:
            attempt_index = int(iter_dir.name.removeprefix("iter_"))
        except ValueError as exc:
            raise ProtocolError(f"invalid iteration directory: {iter_dir.name}") from exc
        status_path = iter_dir / "status.txt"
        legacy_status = status_path.read_text().strip() if status_path.exists() else "missing"
        gate_status = _status(legacy_status)
        reasons = () if gate_status == "PASS" else (f"legacy pipeline status: {legacy_status}",)
        metrics: dict[str, Any] = {"legacy_status": legacy_status}
        bridge_path = iter_dir / "problem.normalization_bridge.json"
        if bridge_path.exists():
            try:
                bridge = json.loads(bridge_path.read_text())
            except Exception as exc:
                metrics["normalization_bridge_error"] = f"{type(exc).__name__}: {exc}"
            else:
                if isinstance(bridge, dict):
                    metrics["normalization_bridge"] = {
                        "status": bridge.get("status"),
                        "metrics": bridge.get("metrics") if isinstance(bridge.get("metrics"), dict) else {},
                    }
        problem_path = iter_dir / "problem.json"
        artifact_refs = {"status": str(status_path.relative_to(target_dir))}
        if problem_path.exists():
            artifact_refs["candidate"] = str(problem_path.relative_to(target_dir))
        verifier_path = iter_dir / "problem.verifier.json"
        if verifier_path.exists():
            artifact_refs["verifier"] = str(verifier_path.relative_to(target_dir))
        gate = GateResult(
            name="pipeline",
            status=gate_status,
            reasons=reasons,
            metrics=metrics,
        )
        attempts.append(AttemptEvidence(
            run_id=spec.run_id,
            cohort_id=spec.cohort_id,
            arm=spec.arm,
            plugin_id=PLUGIN_ID,
            task_id=task_id,
            task_digest=task_digest,
            attempt_index=attempt_index,
            candidate_digest=_candidate_digest(problem_path),
            status=gate_status,
            gates=(gate,),
            provenance=spec.provenance,
            artifact_refs=artifact_refs,
        ))
    if not attempts:
        raise ProtocolError(f"target has no iteration artifacts: {target_dir}")
    return tuple(attempts)


def load_target_evidence(target_dir: Path) -> tuple[AttemptEvidence, ...]:
    evidence_dir = target_dir / "evidence"
    if not evidence_dir.exists():
        return ()
    paths = sorted(evidence_dir.glob("attempt_*.evidence.json"))
    if not paths:
        raise ProtocolError(f"evidence directory contains no attempt records: {evidence_dir}")
    return tuple(
        AttemptEvidence.from_dict(json.loads(path.read_text()))
        for path in paths
    )


def validate_target_evidence(
    records: tuple[AttemptEvidence, ...],
    *,
    target: str,
    target_index: int,
    n_iterations: int,
    accepted: bool,
    spec: RunSpec,
) -> None:
    task_id, task_digest = target_identity(target, target_index)
    if len(records) != n_iterations:
        raise ProtocolError(
            f"evidence attempt count mismatch: expected {n_iterations}, found {len(records)}"
        )
    expected_indices = list(range(n_iterations))
    actual_indices = [record.attempt_index for record in records]
    if actual_indices != expected_indices:
        raise ProtocolError(
            f"evidence attempt indices mismatch: expected {expected_indices}, found {actual_indices}"
        )
    for record in records:
        expected = {
            "run_id": spec.run_id,
            "cohort_id": spec.cohort_id,
            "arm": spec.arm,
            "plugin_id": PLUGIN_ID,
            "task_id": task_id,
            "task_digest": task_digest,
        }
        actual = {key: getattr(record, key) for key in expected}
        if actual != expected:
            raise ProtocolError(
                f"evidence identity mismatch: expected {expected}, found {actual}"
            )
    evidence_accepted = any(record.status == "PASS" for record in records)
    if evidence_accepted != accepted:
        raise ProtocolError(
            f"evidence acceptance mismatch: metrics={accepted}, evidence={evidence_accepted}"
        )


def write_target_evidence(
    target_dir: Path,
    *,
    target: str,
    target_index: int,
    n_iterations: int,
    accepted: bool,
    checkpoint: Mapping[str, Any],
) -> tuple[AttemptEvidence, ...]:
    batch_id = str(checkpoint.get("batch_id") or target_dir.parent.parent.name)
    spec = run_spec_from_checkpoint(checkpoint, batch_id=batch_id)
    records = build_target_evidence(
        target_dir,
        target=target,
        target_index=target_index,
        spec=spec,
    )
    validate_target_evidence(
        records,
        target=target,
        target_index=target_index,
        n_iterations=n_iterations,
        accepted=accepted,
        spec=spec,
    )
    store = ArtifactStore(target_dir)
    for record in records:
        relative = Path("evidence") / f"attempt_{record.attempt_index:03d}.evidence.json"
        if (target_dir / relative).exists():
            existing = AttemptEvidence.from_dict(store.read_json(relative))
            if existing != record:
                raise ProtocolError(f"immutable evidence differs from current artifacts: {relative}")
            continue
        try:
            store.write_json_once(relative, record.to_dict())
        except FileExistsError:
            existing = AttemptEvidence.from_dict(store.read_json(relative))
            if existing != record:
                raise ProtocolError(f"immutable evidence differs from current artifacts: {relative}")
    return records
