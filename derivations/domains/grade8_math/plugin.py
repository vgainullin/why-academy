"""Grade-8 math adapter for the domain-neutral evolution kernel."""
from __future__ import annotations

import copy
from typing import Any, Mapping

from evolution.protocols import EvaluationResult, GateResult
from task_contract import validate_task_contract
from typed_linear_equation_oracle import EVALUATOR_VERSION, evaluate_typed_linear_equation


PUBLIC_TASK_VERSION = "derivation_task_public.v2"


class Grade8MathPlugin:
    plugin_id = "grade8_math"
    plugin_version = "grade8_math.v1"

    def task_id(self, task: Mapping[str, Any]) -> str:
        value = task.get("id")
        return value if isinstance(value, str) and value else "unknown-task"

    def task_digest(self, task: Mapping[str, Any]) -> str:
        value = task.get("contract_digest")
        return value if isinstance(value, str) and value else "missing-contract-digest"

    def validate_task(self, task: Mapping[str, Any]) -> None:
        validate_task_contract(task)
        if task.get("task_type") != "linear_equation":
            raise ValueError("Grade8MathPlugin pilot currently supports linear_equation only")

    def public_task(self, task: Mapping[str, Any]) -> Mapping[str, Any]:
        self.validate_task(task)
        return {
            "schema_version": PUBLIC_TASK_VERSION,
            "id": task["id"],
            "task_type": task["task_type"],
            "display": {"prompt": task["display"]["prompt"]},
            "givens": copy.deepcopy(task["givens"]),
            "requirements": copy.deepcopy(task["pedagogy"]["requirements"]),
        }

    def evaluate_raw(self, task: Mapping[str, Any], candidate: Any) -> dict[str, Any]:
        if not isinstance(candidate, Mapping) or set(candidate) != {"graph", "verifier"}:
            return {
                "evaluator_version": EVALUATOR_VERSION,
                "status": "ERROR",
                "task_id": self.task_id(task),
                "graph_id": None,
                "gates": {
                    "candidate": {
                        "status": "ERROR",
                        "reasons": ["candidate must contain exactly graph and verifier"],
                    }
                },
                "reasons": ["candidate: candidate must contain exactly graph and verifier"],
            }
        return evaluate_typed_linear_equation(task, candidate["graph"], candidate["verifier"])

    def evaluate(
        self,
        task: Mapping[str, Any],
        candidate: Any,
        candidate_digest: str,
    ) -> EvaluationResult:
        raw = self.evaluate_raw(task, candidate)
        gates = []
        for name, record in raw.get("gates", {}).items():
            if not isinstance(record, Mapping) or record.get("status") == "NOT_RUN":
                continue
            status = record.get("status")
            if status not in {"PASS", "FAIL", "ERROR"}:
                status = "ERROR"
            reasons = record.get("reasons") if isinstance(record.get("reasons"), list) else []
            gates.append(GateResult(name=name, status=status, reasons=tuple(str(reason) for reason in reasons)))
        if not gates:
            gates.append(GateResult(name="evaluation", status="ERROR", reasons=("oracle returned no gate results",)))
        outputs = {"legacy_payload": raw}
        if "derived_result" in raw:
            outputs["derived_result"] = raw["derived_result"]
        return EvaluationResult.create(
            plugin_id=self.plugin_id,
            evaluator_version=str(raw.get("evaluator_version") or EVALUATOR_VERSION),
            task_id=self.task_id(task),
            task_digest=self.task_digest(task),
            candidate_digest=candidate_digest,
            gates=tuple(gates),
            outputs=outputs,
        )
