"""Paired experiment comparison independent of task domain and runner layout."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .protocols import AttemptEvidence, ProtocolError


COMPARISON_SCHEMA_VERSION = "evolution_paired_comparison.v1"


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    plugin_id: str
    task_id: str
    task_digest: str
    status: str
    n_attempts: int

    @property
    def accepted(self) -> bool:
        return self.status == "PASS"


def task_outcomes(records: Iterable[AttemptEvidence]) -> dict[tuple[str, str], TaskOutcome]:
    grouped: dict[tuple[str, str], list[AttemptEvidence]] = {}
    for record in records:
        grouped.setdefault((record.plugin_id, record.task_id), []).append(record)

    outcomes = {}
    for key, attempts in grouped.items():
        digests = {attempt.task_digest for attempt in attempts}
        if len(digests) != 1:
            raise ProtocolError(f"task {key} changed digest within one arm")
        statuses = {attempt.status for attempt in attempts}
        status = "PASS" if "PASS" in statuses else "ERROR" if "ERROR" in statuses else "FAIL"
        outcomes[key] = TaskOutcome(
            plugin_id=key[0],
            task_id=key[1],
            task_digest=next(iter(digests)),
            status=status,
            n_attempts=len(attempts),
        )
    return outcomes


def compare_arms(
    control: Iterable[AttemptEvidence],
    treatment: Iterable[AttemptEvidence],
) -> dict:
    control_records = list(control)
    treatment_records = list(treatment)
    if not control_records or not treatment_records:
        raise ProtocolError("both experiment arms must contain evidence")
    control_cohorts = {record.cohort_id for record in control_records}
    treatment_cohorts = {record.cohort_id for record in treatment_records}
    if len(control_cohorts) != 1 or control_cohorts != treatment_cohorts:
        raise ProtocolError("experiment arms must use the same single cohort_id")
    control_arms = {record.arm for record in control_records}
    treatment_arms = {record.arm for record in treatment_records}
    if len(control_arms) != 1 or len(treatment_arms) != 1 or control_arms == treatment_arms:
        raise ProtocolError("experiment arms must have distinct arm identifiers")

    c_outcomes = task_outcomes(control_records)
    t_outcomes = task_outcomes(treatment_records)
    if set(c_outcomes) != set(t_outcomes):
        raise ProtocolError("experiment arms must contain the same plugin/task pairs")

    pairs = []
    outcome_counts = Counter()
    for key in sorted(c_outcomes):
        c = c_outcomes[key]
        t = t_outcomes[key]
        if c.task_digest != t.task_digest:
            raise ProtocolError(f"task {key} changed digest between experiment arms")
        if c.accepted and t.accepted:
            outcome = "both_accepted"
        elif not c.accepted and not t.accepted:
            outcome = "both_failed"
        elif t.accepted:
            outcome = "treatment_only_accepted"
        else:
            outcome = "control_only_accepted"
        outcome_counts[outcome] += 1
        pairs.append({
            "plugin_id": key[0],
            "task_id": key[1],
            "task_digest": c.task_digest,
            "outcome": outcome,
            "control": {"status": c.status, "n_attempts": c.n_attempts},
            "treatment": {"status": t.status, "n_attempts": t.n_attempts},
        })

    n_tasks = len(pairs)
    control_accepted = sum(outcome.accepted for outcome in c_outcomes.values())
    treatment_accepted = sum(outcome.accepted for outcome in t_outcomes.values())
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "cohort_id": next(iter(control_cohorts)),
        "control_arm": next(iter(control_arms)),
        "treatment_arm": next(iter(treatment_arms)),
        "n_tasks": n_tasks,
        "control_acceptance_rate": control_accepted / n_tasks,
        "treatment_acceptance_rate": treatment_accepted / n_tasks,
        "acceptance_delta": (treatment_accepted - control_accepted) / n_tasks,
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "pairs": pairs,
    }


def evaluate_criteria(comparison: dict, criteria: dict) -> dict:
    supported = {"min_acceptance_delta", "max_treatment_error_rate"}
    unknown = set(criteria) - supported
    if unknown:
        raise ProtocolError(f"unsupported experiment criteria: {sorted(unknown)}")
    checks = {}
    if "min_acceptance_delta" in criteria:
        observed = float(comparison["acceptance_delta"])
        threshold = float(criteria["min_acceptance_delta"])
        checks["min_acceptance_delta"] = {
            "observed": observed,
            "threshold": threshold,
            "passed": observed >= threshold,
        }
    if "max_treatment_error_rate" in criteria:
        errors = sum(pair["treatment"]["status"] == "ERROR" for pair in comparison["pairs"])
        observed = errors / comparison["n_tasks"]
        threshold = float(criteria["max_treatment_error_rate"])
        checks["max_treatment_error_rate"] = {
            "observed": observed,
            "threshold": threshold,
            "passed": observed <= threshold,
        }
    return {"passed": all(check["passed"] for check in checks.values()), "checks": checks}
