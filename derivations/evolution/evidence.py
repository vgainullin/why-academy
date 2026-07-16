"""Domain-neutral aggregation over versioned attempt evidence."""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from .protocols import AttemptEvidence


AGGREGATE_SCHEMA_VERSION = "evolution_evidence_aggregate.v1"


def aggregate_evidence(records: Iterable[AttemptEvidence]) -> dict:
    attempts = list(records)
    status_counts = Counter(record.status for record in attempts)
    plugin_counts = Counter(record.plugin_id for record in attempts)
    gate_status_counts: dict[str, Counter] = {}
    failure_signals = Counter()
    task_ids = set()

    for record in attempts:
        task_ids.add((record.plugin_id, record.task_id))
        for gate in record.gates:
            gate_status_counts.setdefault(gate.name, Counter())[gate.status] += 1
            if gate.status != "PASS":
                if gate.reasons:
                    for reason in gate.reasons:
                        failure_signals[(gate.name, reason)] += 1
                else:
                    failure_signals[(gate.name, gate.status)] += 1

    return {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "n_attempts": len(attempts),
        "n_tasks": len(task_ids),
        "status_counts": dict(sorted(status_counts.items())),
        "plugin_counts": dict(sorted(plugin_counts.items())),
        "gate_status_counts": {
            name: dict(sorted(counts.items()))
            for name, counts in sorted(gate_status_counts.items())
        },
        "failure_signals": [
            {"gate": gate, "reason": reason, "count": count}
            for (gate, reason), count in sorted(
                failure_signals.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
    }
