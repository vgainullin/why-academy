"""Generic one-attempt runner driven entirely by a domain plugin."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .artifacts import ArtifactStore
from .protocols import (
    AttemptEvidence,
    DomainPlugin,
    EvaluationResult,
    GateResult,
    ProtocolError,
    RunSpec,
    canonical_digest,
    final_status,
)


CandidateProducer = Callable[[Mapping[str, Any]], Any]


def _error_evidence(
    *,
    spec: RunSpec,
    plugin_id: str,
    task_id: str,
    task_digest: str,
    attempt_index: int,
    stage: str,
    exc: Exception,
    candidate_digest: str | None = None,
) -> AttemptEvidence:
    gate = GateResult(
        name=stage,
        status="ERROR",
        reasons=(f"{type(exc).__name__}: {exc}",),
    )
    return AttemptEvidence(
        run_id=spec.run_id,
        cohort_id=spec.cohort_id,
        arm=spec.arm,
        plugin_id=plugin_id,
        task_id=task_id,
        task_digest=task_digest,
        attempt_index=attempt_index,
        candidate_digest=candidate_digest,
        status="ERROR",
        gates=(gate,),
        provenance=spec.provenance,
    )


def _validate_evaluation(
    evaluation: EvaluationResult,
    *,
    plugin: DomainPlugin,
    task_id: str,
    task_digest: str,
    candidate_digest: str,
) -> None:
    expected = {
        "plugin_id": plugin.plugin_id,
        "task_id": task_id,
        "task_digest": task_digest,
        "candidate_digest": candidate_digest,
    }
    actual = {name: getattr(evaluation, name) for name in expected}
    if actual != expected:
        raise ProtocolError(f"plugin evaluation identity mismatch: expected {expected}, got {actual}")


def run_attempt(
    *,
    spec: RunSpec,
    plugin: DomainPlugin,
    task: Mapping[str, Any],
    producer: CandidateProducer,
    attempt_index: int = 0,
    store: ArtifactStore | None = None,
) -> AttemptEvidence:
    """Generate and evaluate one candidate without knowing its domain semantics."""
    if not isinstance(plugin, DomainPlugin):
        raise ProtocolError("plugin does not implement DomainPlugin")
    task_id = plugin.task_id(task)
    task_digest = plugin.task_digest(task)
    try:
        plugin.validate_task(task)
        public_task = plugin.public_task(task)
    except Exception as exc:
        evidence = _error_evidence(
            spec=spec,
            plugin_id=plugin.plugin_id,
            task_id=task_id,
            task_digest=task_digest,
            attempt_index=attempt_index,
            stage="task_contract",
            exc=exc,
        )
    else:
        try:
            candidate = producer(public_task)
            candidate_digest = canonical_digest(candidate)
        except Exception as exc:
            evidence = _error_evidence(
                spec=spec,
                plugin_id=plugin.plugin_id,
                task_id=task_id,
                task_digest=task_digest,
                attempt_index=attempt_index,
                stage="generation",
                exc=exc,
            )
        else:
            try:
                evaluation = plugin.evaluate(task, candidate, candidate_digest)
                _validate_evaluation(
                    evaluation,
                    plugin=plugin,
                    task_id=task_id,
                    task_digest=task_digest,
                    candidate_digest=candidate_digest,
                )
                gates = (GateResult(name="generation", status="PASS"), *evaluation.gates)
                evidence = AttemptEvidence(
                    run_id=spec.run_id,
                    cohort_id=spec.cohort_id,
                    arm=spec.arm,
                    plugin_id=plugin.plugin_id,
                    task_id=task_id,
                    task_digest=task_digest,
                    attempt_index=attempt_index,
                    candidate_digest=candidate_digest,
                    status=final_status(gates),
                    gates=gates,
                    provenance=spec.provenance,
                )
            except Exception as exc:
                evidence = _error_evidence(
                    spec=spec,
                    plugin_id=plugin.plugin_id,
                    task_id=task_id,
                    task_digest=task_digest,
                    attempt_index=attempt_index,
                    stage="evaluation",
                    exc=exc,
                    candidate_digest=candidate_digest,
                )
    if store is not None:
        store.write_evidence(evidence)
    return evidence
