"""Paired experiment comparison independent of task domain and runner layout."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping

from .protocols import AttemptEvidence, ProtocolError


COMPARISON_SCHEMA_VERSION = "evolution_paired_comparison.v1"
OUTCOMES = frozenset({
    "both_accepted",
    "both_failed",
    "treatment_only_accepted",
    "control_only_accepted",
})


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
    comparison = {
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
    validate_comparison(comparison)
    return comparison


def _rate(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"comparison {name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ProtocolError(f"comparison {name} must be a finite number")
    return result


def validate_comparison(comparison: Mapping[str, Any]) -> None:
    if not isinstance(comparison, Mapping):
        raise ProtocolError("comparison must be an object")
    if comparison.get("schema_version") != COMPARISON_SCHEMA_VERSION:
        raise ProtocolError("unsupported comparison schema version")
    for field in ("cohort_id", "control_arm", "treatment_arm"):
        value = comparison.get(field)
        if not isinstance(value, str) or not value:
            raise ProtocolError(f"comparison {field} must be a non-empty string")
    if comparison["control_arm"] == comparison["treatment_arm"]:
        raise ProtocolError("comparison arms must be distinct")
    n_tasks = comparison.get("n_tasks")
    if type(n_tasks) is not int or n_tasks <= 0:
        raise ProtocolError("comparison n_tasks must be a positive integer")
    control_rate = _rate(comparison.get("control_acceptance_rate"), "control_acceptance_rate")
    treatment_rate = _rate(comparison.get("treatment_acceptance_rate"), "treatment_acceptance_rate")
    delta = _rate(comparison.get("acceptance_delta"), "acceptance_delta")
    if not 0 <= control_rate <= 1 or not 0 <= treatment_rate <= 1:
        raise ProtocolError("comparison acceptance rates must be in [0, 1]")
    if not math.isclose(delta, treatment_rate - control_rate, abs_tol=1e-12):
        raise ProtocolError("comparison acceptance_delta does not match arm rates")
    raw_counts = comparison.get("outcome_counts")
    if not isinstance(raw_counts, Mapping) or set(raw_counts) - OUTCOMES:
        raise ProtocolError("comparison outcome_counts are invalid")
    if any(type(value) is not int or value < 0 for value in raw_counts.values()):
        raise ProtocolError("comparison outcome counts must be non-negative integers")
    if sum(raw_counts.values()) != n_tasks:
        raise ProtocolError("comparison outcome counts must sum to n_tasks")
    pairs = comparison.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != n_tasks:
        raise ProtocolError("comparison pairs must contain exactly n_tasks records")
    seen = set()
    observed_counts = Counter()
    observed_control_accepted = 0
    observed_treatment_accepted = 0
    for pair in pairs:
        if not isinstance(pair, Mapping):
            raise ProtocolError("comparison pair must be an object")
        key = (pair.get("plugin_id"), pair.get("task_id"))
        if not all(isinstance(value, str) and value for value in key) or key in seen:
            raise ProtocolError("comparison pair identity is invalid or duplicated")
        seen.add(key)
        if not isinstance(pair.get("task_digest"), str) or not pair["task_digest"]:
            raise ProtocolError("comparison pair task_digest must be a non-empty string")
        outcome = pair.get("outcome")
        if outcome not in OUTCOMES:
            raise ProtocolError("comparison pair outcome is invalid")
        observed_counts[outcome] += 1
        for arm in ("control", "treatment"):
            arm_record = pair.get(arm)
            if not isinstance(arm_record, Mapping):
                raise ProtocolError(f"comparison pair {arm} result must be an object")
            if arm_record.get("status") not in {"PASS", "FAIL", "ERROR"}:
                raise ProtocolError(f"comparison pair {arm} status is invalid")
            if type(arm_record.get("n_attempts")) is not int or arm_record["n_attempts"] <= 0:
                raise ProtocolError(f"comparison pair {arm} n_attempts must be positive")
        control_accepted = pair["control"]["status"] == "PASS"
        treatment_accepted = pair["treatment"]["status"] == "PASS"
        observed_control_accepted += control_accepted
        observed_treatment_accepted += treatment_accepted
        expected_outcome = (
            "both_accepted"
            if control_accepted and treatment_accepted
            else "both_failed"
            if not control_accepted and not treatment_accepted
            else "treatment_only_accepted"
            if treatment_accepted
            else "control_only_accepted"
        )
        if outcome != expected_outcome:
            raise ProtocolError("comparison pair outcome does not match arm statuses")
    if dict(observed_counts) != dict(raw_counts):
        raise ProtocolError("comparison outcome counts do not match pairs")
    if not math.isclose(control_rate, observed_control_accepted / n_tasks, abs_tol=1e-12):
        raise ProtocolError("control acceptance rate does not match comparison pairs")
    if not math.isclose(treatment_rate, observed_treatment_accepted / n_tasks, abs_tol=1e-12):
        raise ProtocolError("treatment acceptance rate does not match comparison pairs")


def evaluate_criteria(comparison: dict, criteria: dict) -> dict:
    validate_comparison(comparison)
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
