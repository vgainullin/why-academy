#!/usr/bin/env python3
"""Paired control/treatment summary for derivation A/B batches."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any


def reexec_with_derivation_python() -> None:
    if os.environ.get("AB_COMPARE_REEXECED") == "1":
        return
    candidates: list[Path] = []
    configured = os.environ.get("DERIVATION_PYTHON")
    if configured:
        candidates.append(Path(configured))
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "derivations" / ".venv" / "bin" / "python")
        candidates.append(parent / ".venv" / "bin" / "python")

    current = Path(sys.executable).resolve()
    for candidate in candidates:
        if candidate.exists() and candidate.resolve() != current:
            os.environ["AB_COMPARE_REEXECED"] = "1"
            os.execv(str(candidate), [str(candidate), *sys.argv])


if __name__ == "__main__":
    reexec_with_derivation_python()

from substitution_structural_check import check_problem


TREATMENT_FAILURE_STATUSES = {
    "rule_plan_invalid",
    "rule_executor_coverage_gap",
    "rule_executor_fail",
    "substitution_structural_fail",
    "normalization_boundary_fail",
    "normalization_bridge_fail",
    "normalization_contract_mismatch",
}


class ComparisonRefused(ValueError):
    def __init__(self, issues: dict[str, Any]):
        self.issues = issues
        parts = []
        for key, value in issues.items():
            if value:
                parts.append(f"{key}={value}")
        super().__init__("incomplete or mismatched A/B batches: " + ", ".join(parts))


class InvalidTargetRecord(ValueError):
    def __init__(self, issues: list[dict[str, Any]]):
        self.issues = issues
        super().__init__("invalid target record")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def read_status(iter_dir: Path) -> str:
    path = iter_dir / "status.txt"
    return path.read_text().strip() if path.exists() else "missing"


def target_dir_index(target_dir: Path) -> int | None:
    try:
        return int(target_dir.name.replace("target_", ""))
    except ValueError:
        return None


def target_artifact_issue(
    target_dir: Path,
    artifact: str,
    code: str,
    *,
    target_index: int | None = None,
    field: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "target_dir": str(target_dir),
        "target_dir_name": target_dir.name,
        "target_dir_index": target_dir_index(target_dir),
        "artifact": artifact,
        "path": str(target_dir / artifact),
        "code": code,
    }
    if target_index is not None:
        issue["target_index"] = target_index
    if field is not None:
        issue["field"] = field
    if detail:
        issue["detail"] = detail
    return issue


def read_required_json_object(target_dir: Path, artifact: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    path = target_dir / artifact
    if not path.exists():
        return None, target_artifact_issue(target_dir, artifact, "missing_file")
    try:
        data = json.loads(path.read_text())
    except Exception as e:
        return None, target_artifact_issue(
            target_dir,
            artifact,
            "invalid_json",
            detail=f"{type(e).__name__}: {e}",
        )
    if not isinstance(data, dict):
        return None, target_artifact_issue(
            target_dir,
            artifact,
            "invalid_schema",
            detail="expected JSON object",
        )
    return data, None


def require_int_metric(
    metrics: dict[str, Any],
    target_dir: Path,
    field: str,
    issues: list[dict[str, Any]],
    *,
    target_index: int | None = None,
) -> int | None:
    if field not in metrics:
        issues.append(target_artifact_issue(
            target_dir,
            "target_metrics.json",
            "missing_required_metric",
            target_index=target_index,
            field=field,
        ))
        return None
    value = metrics[field]
    if type(value) is not int:
        issues.append(target_artifact_issue(
            target_dir,
            "target_metrics.json",
            "invalid_metric_type",
            target_index=target_index,
            field=field,
            detail=f"expected int, got {type(value).__name__}",
        ))
        return None
    return value


def require_bool_metric(
    metrics: dict[str, Any],
    target_dir: Path,
    field: str,
    issues: list[dict[str, Any]],
    *,
    target_index: int | None = None,
) -> bool | None:
    if field not in metrics:
        issues.append(target_artifact_issue(
            target_dir,
            "target_metrics.json",
            "missing_required_metric",
            target_index=target_index,
            field=field,
        ))
        return None
    value = metrics[field]
    if type(value) is not bool:
        issues.append(target_artifact_issue(
            target_dir,
            "target_metrics.json",
            "invalid_metric_type",
            target_index=target_index,
            field=field,
            detail=f"expected bool, got {type(value).__name__}",
        ))
        return None
    return value


def substitution_report(iter_dir: Path) -> dict[str, Any] | None:
    problem = read_json(iter_dir / "problem.json")
    if problem:
        try:
            return check_problem(problem)
        except Exception as e:
            return {
                "status": "ERROR",
                "n_inspected": 0,
                "failures": [],
                "parse_errors": [{"error": f"{type(e).__name__}: {e}"}],
            }
    return read_json(iter_dir / "problem.substitution_check.json")


def target_record(target_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    metrics, metrics_issue = read_required_json_object(target_dir, "target_metrics.json")
    if metrics_issue:
        issues.append(metrics_issue)
    target_json, target_issue = read_required_json_object(target_dir, "target.json")

    target_index = None
    accepted = None
    first_try_pass = None
    n_iterations = None
    accepted_iter = None
    if metrics is not None:
        target_index = require_int_metric(metrics, target_dir, "target_index", issues)
        accepted = require_bool_metric(metrics, target_dir, "accepted", issues, target_index=target_index)
        first_try_pass = require_bool_metric(metrics, target_dir, "first_try_pass", issues, target_index=target_index)
        n_iterations = require_int_metric(metrics, target_dir, "n_iterations", issues, target_index=target_index)
        accepted_iter = metrics.get("accepted_at_iter")
        if accepted is True:
            accepted_iter = require_int_metric(metrics, target_dir, "accepted_at_iter", issues, target_index=target_index)
        elif accepted_iter is not None and type(accepted_iter) is not int:
            issues.append(target_artifact_issue(
                target_dir,
                "target_metrics.json",
                "invalid_metric_type",
                target_index=target_index,
                field="accepted_at_iter",
                detail=f"expected int or null, got {type(accepted_iter).__name__}",
            ))

    target = None
    if target_issue:
        if target_index is not None:
            target_issue["target_index"] = target_index
        issues.append(target_issue)
    elif target_json is not None:
        raw_target = target_json.get("target")
        if raw_target is None:
            issues.append(target_artifact_issue(
                target_dir,
                "target.json",
                "missing_required_field",
                target_index=target_index,
                field="target",
            ))
        elif not isinstance(raw_target, str):
            issues.append(target_artifact_issue(
                target_dir,
                "target.json",
                "invalid_field_type",
                target_index=target_index,
                field="target",
                detail=f"expected str, got {type(raw_target).__name__}",
            ))
        elif not raw_target.strip():
            issues.append(target_artifact_issue(
                target_dir,
                "target.json",
                "empty_target_text",
                target_index=target_index,
                field="target",
            ))
        else:
            target = raw_target

    if issues:
        raise InvalidTargetRecord(issues)

    iter_statuses = []
    for iter_dir in sorted(target_dir.glob("iter_*")):
        item = {
            "iter": int(iter_dir.name.replace("iter_", "")),
            "status": read_status(iter_dir),
        }
        bridge = read_json(iter_dir / "problem.normalization_bridge.json")
        if bridge:
            item["normalization_bridge"] = {
                "status": bridge.get("status"),
                "metrics": bridge.get("metrics") if isinstance(bridge.get("metrics"), dict) else {},
            }
        iter_statuses.append(item)

    accepted_substitution = None
    if accepted and accepted_iter is not None:
        accepted_substitution = substitution_report(target_dir / f"iter_{accepted_iter:02d}")

    return {
        "target_index": target_index,
        "target": target,
        "accepted": accepted,
        "accepted_at_iter": accepted_iter,
        "first_try_pass": first_try_pass,
        "n_iterations": n_iterations,
        "failure_reason": metrics.get("failure_reason"),
        "iter_statuses": iter_statuses,
        "accepted_substitution": accepted_substitution,
    }


def load_batch(batch_dir: Path) -> dict[str, Any]:
    records = {}
    invalid_targets = []
    for target_dir in sorted((batch_dir / "targets").glob("target_*")):
        try:
            rec = target_record(target_dir)
        except InvalidTargetRecord as e:
            invalid_targets.extend(e.issues)
            continue
        target_index = int(rec["target_index"])
        if target_index in records:
            invalid_targets.append(target_artifact_issue(
                target_dir,
                "target_metrics.json",
                "duplicate_target_index",
                target_index=target_index,
                field="target_index",
            ))
            continue
        records[target_index] = rec
    return {
        "batch_dir": str(batch_dir),
        "checkpoint": read_json(batch_dir / "checkpoint.json", {}) or {},
        "targets": records,
        "invalid_targets": invalid_targets,
    }


def count_by(values: list[str | None]) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        key = value or "unknown"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def batch_summary(batch: dict[str, Any]) -> dict[str, Any]:
    records = list(batch["targets"].values())
    accepted = [r for r in records if r["accepted"]]
    accepted_iters = [int(r["accepted_at_iter"]) for r in accepted if r["accepted_at_iter"] is not None]
    status_counts: dict[str, int] = {}
    for r in records:
        for item in r["iter_statuses"]:
            status = item["status"]
            status_counts[status] = status_counts.get(status, 0) + 1

    accepted_substitution_failures = 0
    accepted_failed_edges = 0
    accepted_inspected_edges = 0
    normalization_bridge = {
        "status_counts": {},
        "protected_edges": 0,
        "preserved_edges": 0,
        "collapsed_protected_edges": 0,
        "blocked_merges": 0,
        "allowed_noop_drops": 0,
        "raw_pass_normalized_substitution_fail": 0,
    }
    for r in records:
        for item in r["iter_statuses"]:
            bridge = item.get("normalization_bridge")
            if not bridge:
                continue
            status = bridge.get("status") or "unknown"
            bridge_status_counts = normalization_bridge["status_counts"]
            bridge_status_counts[status] = bridge_status_counts.get(status, 0) + 1
            metrics = bridge.get("metrics") if isinstance(bridge.get("metrics"), dict) else {}
            for key in (
                "protected_edges",
                "preserved_edges",
                "collapsed_protected_edges",
                "blocked_merges",
                "allowed_noop_drops",
                "raw_pass_normalized_substitution_fail",
            ):
                normalization_bridge[key] += int(metrics.get(key, 0) or 0)
    for r in accepted:
        report = r.get("accepted_substitution")
        if not report:
            continue
        accepted_inspected_edges += int(report.get("n_inspected", 0) or 0)
        failures = len(report.get("failures", []) or [])
        accepted_failed_edges += failures
        if report.get("status") != "PASS":
            accepted_substitution_failures += 1

    return {
        "batch_id": batch["checkpoint"].get("batch_id") or Path(batch["batch_dir"]).name,
        "inner_mode": batch["checkpoint"].get("inner_mode"),
        "experiment_id": batch["checkpoint"].get("experiment_id"),
        "treatment_id": batch["checkpoint"].get("treatment_id"),
        "n_targets": len(records),
        "n_accepted": len(accepted),
        "acceptance_rate": len(accepted) / len(records) if records else 0.0,
        "n_first_try_pass": sum(1 for r in records if r["first_try_pass"]),
        "first_try_pass_rate": (
            sum(1 for r in records if r["first_try_pass"]) / len(records) if records else 0.0
        ),
        "avg_iters_to_accept": statistics.mean(accepted_iters) if accepted_iters else 0.0,
        "failure_reasons": count_by([r["failure_reason"] for r in records if not r["accepted"]]),
        "iter_status_counts": dict(sorted(status_counts.items())),
        "treatment_failure_counts": {
            status: status_counts.get(status, 0)
            for status in sorted(TREATMENT_FAILURE_STATUSES)
            if status_counts.get(status, 0)
        },
        "accepted_substitution": {
            "n_inspected_edges": accepted_inspected_edges,
            "n_failed_edges": accepted_failed_edges,
            "n_iters_with_failures": accepted_substitution_failures,
        },
        "normalization_bridge": normalization_bridge,
    }


def compare_batches(control_dir: Path, treatment_dir: Path, *, experiment_id: str | None = None) -> dict[str, Any]:
    control = load_batch(control_dir)
    treatment = load_batch(treatment_dir)
    control_targets = control["targets"]
    treatment_targets = treatment["targets"]
    common = sorted(set(control_targets) & set(treatment_targets))

    invalid_targets = []
    for side, batch in (("control", control), ("treatment", treatment)):
        for issue in batch.get("invalid_targets", []):
            invalid_targets.append({
                "side": side,
                "batch_dir": batch["batch_dir"],
                **issue,
            })

    pairing_issues = {
        "invalid_targets": invalid_targets,
        "missing_in_control": sorted(set(treatment_targets) - set(control_targets)),
        "missing_in_treatment": sorted(set(control_targets) - set(treatment_targets)),
        "missing_target_text": [],
        "target_mismatches": [],
        "empty_pair_set": not common,
    }
    for idx in common:
        c_target = control_targets[idx]["target"]
        t_target = treatment_targets[idx]["target"]
        if not c_target or not t_target:
            pairing_issues["missing_target_text"].append(idx)
        elif c_target != t_target:
            pairing_issues["target_mismatches"].append(idx)
    if any(pairing_issues.values()):
        raise ComparisonRefused(pairing_issues)

    pairs = []
    outcome_counts = {
        "both_accepted": 0,
        "both_failed": 0,
        "treatment_only_accepted": 0,
        "control_only_accepted": 0,
    }
    for idx in common:
        c = control_targets[idx]
        t = treatment_targets[idx]
        if c["accepted"] and t["accepted"]:
            outcome = "both_accepted"
        elif not c["accepted"] and not t["accepted"]:
            outcome = "both_failed"
        elif t["accepted"]:
            outcome = "treatment_only_accepted"
        else:
            outcome = "control_only_accepted"
        outcome_counts[outcome] += 1
        pairs.append({
            "target_index": idx,
            "target": t["target"] or c["target"],
            "outcome": outcome,
            "control": {
                "accepted": c["accepted"],
                "accepted_at_iter": c["accepted_at_iter"],
                "first_try_pass": c["first_try_pass"],
                "failure_reason": c["failure_reason"],
            },
            "treatment": {
                "accepted": t["accepted"],
                "accepted_at_iter": t["accepted_at_iter"],
                "first_try_pass": t["first_try_pass"],
                "failure_reason": t["failure_reason"],
                "iter_statuses": t["iter_statuses"],
            },
        })

    c_summary = batch_summary(control)
    t_summary = batch_summary(treatment)
    n_pairs = len(pairs)
    control_accepted = sum(1 for p in pairs if p["control"]["accepted"])
    treatment_accepted = sum(1 for p in pairs if p["treatment"]["accepted"])
    control_first_try = sum(1 for p in pairs if p["control"]["first_try_pass"])
    treatment_first_try = sum(1 for p in pairs if p["treatment"]["first_try_pass"])
    control_acceptance_rate = control_accepted / n_pairs
    treatment_acceptance_rate = treatment_accepted / n_pairs
    control_first_try_rate = control_first_try / n_pairs
    treatment_first_try_rate = treatment_first_try / n_pairs
    return {
        "experiment_id": experiment_id or t_summary.get("experiment_id") or c_summary.get("experiment_id"),
        "control_batch": c_summary,
        "treatment_batch": t_summary,
        "paired": {
            "n_pairs": n_pairs,
            "missing_in_control": [],
            "missing_in_treatment": [],
            "missing_target_text": [],
            "target_mismatches": [],
            **outcome_counts,
            "control_accepted": control_accepted,
            "treatment_accepted": treatment_accepted,
            "control_acceptance_rate": control_acceptance_rate,
            "treatment_acceptance_rate": treatment_acceptance_rate,
            "acceptance_delta": treatment_acceptance_rate - control_acceptance_rate,
            "control_first_try_pass": control_first_try,
            "treatment_first_try_pass": treatment_first_try,
            "control_first_try_pass_rate": control_first_try_rate,
            "treatment_first_try_pass_rate": treatment_first_try_rate,
            "first_try_pass_delta": treatment_first_try_rate - control_first_try_rate,
        },
        "pairs": pairs,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    c = summary["control_batch"]
    t = summary["treatment_batch"]
    p = summary["paired"]
    lines = [
        f"# A/B comparison: {summary.get('experiment_id') or '(unspecified)'}",
        "",
        f"- Control batch: `{c['batch_id']}`",
        f"- Treatment batch: `{t['batch_id']}`",
        f"- Pairs: {p['n_pairs']}",
        f"- Paired acceptance: control {p['control_accepted']}/{p['n_pairs']} "
        f"({p['control_acceptance_rate']:.2%}), treatment "
        f"{p['treatment_accepted']}/{p['n_pairs']} "
        f"({p['treatment_acceptance_rate']:.2%}), "
        f"delta {p['acceptance_delta']:+.2%}",
        f"- Paired first try: control {p['control_first_try_pass_rate']:.2%}, "
        f"treatment {p['treatment_first_try_pass_rate']:.2%}, "
        f"delta {p['first_try_pass_delta']:+.2%}",
        f"- Outcomes: both accepted {p['both_accepted']}, both failed {p['both_failed']}, "
        f"treatment-only accepted {p['treatment_only_accepted']}, "
        f"control-only accepted {p['control_only_accepted']}",
        "",
        "## Treatment Failures",
        "",
    ]
    failures = t.get("treatment_failure_counts") or {}
    if failures:
        for status, count in failures.items():
            lines.append(f"- {status}: {count}")
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Accepted Substitution Checks",
        "",
        f"- Control failed accepted substitution edges: {c['accepted_substitution']['n_failed_edges']}",
        f"- Treatment failed accepted substitution edges: {t['accepted_substitution']['n_failed_edges']}",
        "",
        "## Normalization Bridge",
        "",
    ])
    bridge_statuses = (t.get("normalization_bridge") or {}).get("status_counts") or {}
    if bridge_statuses:
        for status, count in bridge_statuses.items():
            lines.append(f"- {status}: {count}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", required=True, type=Path)
    ap.add_argument("--treatment", required=True, type=Path)
    ap.add_argument("--experiment-id", default=None)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    try:
        summary = compare_batches(args.control.resolve(), args.treatment.resolve(), experiment_id=args.experiment_id)
    except ComparisonRefused as e:
        print(json.dumps({
            "error": "comparison_refused",
            "issues": e.issues,
        }, indent=2), file=sys.stderr)
        return 2
    out_dir = (args.out_dir or args.treatment).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ab_comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out_dir / "ab_comparison.md").write_text(render_markdown(summary) + "\n")
    print(json.dumps(summary["paired"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
