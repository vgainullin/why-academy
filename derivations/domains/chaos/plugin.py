"""A graph-free logistic-map workflow used to prove kernel modularity."""
from __future__ import annotations

import copy
from fractions import Fraction
from typing import Any, Mapping

from evolution.protocols import EvaluationResult, GateResult, ProtocolError, canonical_digest


TASK_SCHEMA_VERSION = "chaos_logistic_task.v1"
PUBLIC_TASK_VERSION = "chaos_logistic_public.v1"
EVALUATOR_VERSION = "chaos_logistic_evaluator.v1"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def _fraction(value: Any, path: str) -> Fraction:
    _require(isinstance(value, Mapping) and set(value) == {"numerator", "denominator"}, f"{path} must be a rational object")
    numerator = value["numerator"]
    denominator = value["denominator"]
    _require(type(numerator) is int and type(denominator) is int and denominator > 0, f"{path} must contain integer numerator and positive denominator")
    result = Fraction(numerator, denominator)
    _require(result.numerator == numerator and result.denominator == denominator, f"{path} must be reduced")
    return result


def _rational(value: Fraction | int) -> dict[str, int]:
    result = Fraction(value)
    return {"numerator": result.numerator, "denominator": result.denominator}


def _task_payload(task: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": task.get("schema_version"),
        "id": task.get("id"),
        "system": task.get("system"),
        "expected": task.get("expected"),
    }


def _iterate(system: Mapping[str, Any]) -> tuple[Fraction, Fraction, Fraction]:
    rate = _fraction(system["rate"], "system.rate")
    first = _fraction(system["initial_conditions"][0], "system.initial_conditions[0]")
    second = _fraction(system["initial_conditions"][1], "system.initial_conditions[1]")
    for _ in range(system["steps"]):
        first = rate * first * (1 - first)
        second = rate * second * (1 - second)
    return first, second, abs(first - second)


def build_logistic_task(
    *,
    task_id: str = "chaos-logistic-sensitive-dependence",
    rate: Fraction = Fraction(4),
    initial_a: Fraction = Fraction(1, 5),
    initial_b: Fraction = Fraction(201, 1000),
    steps: int = 8,
    minimum_separation: Fraction = Fraction(1, 100),
) -> dict[str, Any]:
    task = {
        "schema_version": TASK_SCHEMA_VERSION,
        "id": task_id,
        "system": {
            "kind": "logistic_map",
            "rate": _rational(rate),
            "initial_conditions": [_rational(initial_a), _rational(initial_b)],
            "steps": steps,
        },
        "expected": {
            "kind": "sensitive_dependence",
            "minimum_separation": _rational(minimum_separation),
            "value": False,
        },
    }
    separation = _iterate(task["system"])[2]
    task["expected"]["value"] = separation >= minimum_separation
    task["task_digest"] = canonical_digest(_task_payload(task))
    return task


class ChaosLogisticPlugin:
    plugin_id = "chaos_logistic"
    plugin_version = "chaos_logistic.v1"

    def task_id(self, task: Mapping[str, Any]) -> str:
        value = task.get("id")
        return value if isinstance(value, str) and value else "unknown-task"

    def task_digest(self, task: Mapping[str, Any]) -> str:
        value = task.get("task_digest")
        return value if isinstance(value, str) and value else "missing-task-digest"

    def validate_task(self, task: Mapping[str, Any]) -> None:
        _require(isinstance(task, Mapping), "task must be an object")
        _require(set(task) == {"schema_version", "id", "system", "expected", "task_digest"}, "task has unexpected fields")
        _require(task["schema_version"] == TASK_SCHEMA_VERSION, "task schema_version is invalid")
        _require(isinstance(task["id"], str) and task["id"], "task id must be a non-empty string")
        system = task["system"]
        _require(isinstance(system, Mapping) and set(system) == {"kind", "rate", "initial_conditions", "steps"}, "system is invalid")
        _require(system["kind"] == "logistic_map", "system kind must be logistic_map")
        rate = _fraction(system["rate"], "system.rate")
        _require(0 < rate <= 4, "system.rate must be in (0, 4]")
        initials = system["initial_conditions"]
        _require(isinstance(initials, list) and len(initials) == 2, "system.initial_conditions must contain two values")
        parsed_initials = [_fraction(value, f"system.initial_conditions[{index}]") for index, value in enumerate(initials)]
        _require(all(0 < value < 1 for value in parsed_initials), "initial conditions must be in (0, 1)")
        _require(type(system["steps"]) is int and system["steps"] > 0, "system.steps must be a positive integer")
        expected = task["expected"]
        _require(isinstance(expected, Mapping) and set(expected) == {"kind", "minimum_separation", "value"}, "expected is invalid")
        _require(expected["kind"] == "sensitive_dependence" and type(expected["value"]) is bool, "expected claim is invalid")
        threshold = _fraction(expected["minimum_separation"], "expected.minimum_separation")
        _require(threshold > 0, "minimum separation must be positive")
        computed = _iterate(system)[2] >= threshold
        _require(expected["value"] == computed, "expected claim does not follow from the system")
        _require(task["task_digest"] == canonical_digest(_task_payload(task)), "task_digest does not match task payload")

    def public_task(self, task: Mapping[str, Any]) -> Mapping[str, Any]:
        self.validate_task(task)
        return {
            "schema_version": PUBLIC_TASK_VERSION,
            "id": task["id"],
            "system": copy.deepcopy(task["system"]),
            "claim_kind": task["expected"]["kind"],
        }

    def evaluate(
        self,
        task: Mapping[str, Any],
        candidate: Any,
        candidate_digest: str,
    ) -> EvaluationResult:
        self.validate_task(task)
        gates = [GateResult(name="contract", status="PASS")]
        if not isinstance(candidate, Mapping) or set(candidate) != {"task_id", "claim"}:
            gates.append(GateResult(name="candidate_schema", status="FAIL", reasons=("candidate must contain task_id and claim",)))
            return EvaluationResult.create(
                plugin_id=self.plugin_id,
                evaluator_version=EVALUATOR_VERSION,
                task_id=self.task_id(task),
                task_digest=self.task_digest(task),
                candidate_digest=candidate_digest,
                gates=tuple(gates),
            )
        claim = candidate["claim"]
        if candidate["task_id"] != task["id"] or not isinstance(claim, Mapping) or set(claim) != {"kind", "value"} or claim.get("kind") != "sensitive_dependence" or type(claim.get("value")) is not bool:
            gates.append(GateResult(name="candidate_schema", status="FAIL", reasons=("candidate claim is malformed or bound to another task",)))
            return EvaluationResult.create(
                plugin_id=self.plugin_id,
                evaluator_version=EVALUATOR_VERSION,
                task_id=self.task_id(task),
                task_digest=self.task_digest(task),
                candidate_digest=candidate_digest,
                gates=tuple(gates),
            )
        gates.append(GateResult(name="candidate_schema", status="PASS"))
        first, second, separation = _iterate(task["system"])
        gates.append(GateResult(
            name="dynamics",
            status="PASS",
            metrics={
                "final_first": str(first),
                "final_second": str(second),
                "final_separation": str(separation),
            },
        ))
        matches = claim["value"] == task["expected"]["value"]
        gates.append(GateResult(
            name="goal",
            status="PASS" if matches else "FAIL",
            reasons=() if matches else ("candidate claim does not match deterministic dynamics",),
        ))
        return EvaluationResult.create(
            plugin_id=self.plugin_id,
            evaluator_version=EVALUATOR_VERSION,
            task_id=self.task_id(task),
            task_digest=self.task_digest(task),
            candidate_digest=candidate_digest,
            gates=tuple(gates),
            outputs={"derived_claim": task["expected"]},
        )
