"""Domain-neutral evolution kernel."""

from .protocols import (
    AttemptEvidence,
    DomainPlugin,
    EvaluationResult,
    GateResult,
    RunSpec,
)
from .adapters import evidence_from_gate_records

__all__ = [
    "AttemptEvidence",
    "DomainPlugin",
    "EvaluationResult",
    "GateResult",
    "RunSpec",
    "evidence_from_gate_records",
]
