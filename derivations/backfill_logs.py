#!/usr/bin/env python3
"""Reconstruct logs/epoch_<NNN>/run_<UUID>.jsonl entries from existing
_evolutions/batches/ workspace artifacts.

This is one-time migration glue: when inner_evolve.py landed it bypassed the
old emit_log.py path that wrote jsonl. The outer loop reads jsonl. The data
is all on disk in the workspace, just in a different layout. This walks every
batch's target dirs and emits one jsonl line per target into the correct
epoch's logs/ directory.

Idempotent: re-running overwrites the same per-batch jsonl file.
Usage:
    derivations/backfill_logs.py                # all batches
    derivations/backfill_logs.py <batch_id>     # one batch
"""
from __future__ import annotations
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def emit_from_target(target_dir: Path, batch_checkpoint: dict, target: str) -> list[dict]:
    """One target dir -> one record per iter (so outer loop sees every attempt)."""
    records = []
    target_metrics = json.loads((target_dir / "target_metrics.json").read_text()) if (target_dir / "target_metrics.json").exists() else {}
    target_idx = target_metrics.get("target_index", -1)
    for iter_dir in sorted(target_dir.glob("iter_*")):
        problem_path = iter_dir / "problem.json"
        verifier_path = iter_dir / "problem.verifier.json"
        canvas_check_path = iter_dir / "problem.canvas_check.json"
        judge_path = iter_dir / "problem.judge.json"
        target_check_path = iter_dir / "problem.target_check.json"
        if not problem_path.exists() or not verifier_path.exists():
            status = (iter_dir / "status.txt").read_text().strip() if (iter_dir / "status.txt").exists() else "missing"
            treatment_error = json.loads((iter_dir / "rule_executor_error.json").read_text()) if (iter_dir / "rule_executor_error.json").exists() else None
            if status in ("rule_plan_invalid", "rule_executor_coverage_gap", "rule_executor_fail", "substitution_structural_fail"):
                records.append({
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "run_id": f"{batch_checkpoint['batch_id']}_t{target_idx:03d}_{iter_dir.name}",
                    "batch_id": batch_checkpoint["batch_id"],
                    "target_index": target_idx,
                    "iter": int(iter_dir.name.replace("iter_", "")),
                    "epoch": batch_checkpoint["epoch"],
                    "prompt_version": batch_checkpoint["prompt_version"],
                    "validator_library_version": batch_checkpoint["validator_version"],
                    "config_version": batch_checkpoint.get("config_version", "v1"),
                    "engine": batch_checkpoint.get("inner_engine", "claude"),
                    "model": batch_checkpoint.get("inner_model", "unknown"),
                    "inner_mode": batch_checkpoint.get("inner_mode"),
                    "experiment_id": batch_checkpoint.get("experiment_id"),
                    "treatment_id": batch_checkpoint.get("treatment_id"),
                    "target": target,
                    "problem_id": None,
                    "verifier_version": None,
                    "n_nodes": 0,
                    "n_edges": 0,
                    "node_truth": {"TRUE": 0, "FALSE": 0, "ERROR": 0, "NA": 0},
                    "edge_summary": {"PASS": 0, "FAIL": 0, "UNCOVERED": 0, "WEAK_PASS": 0, "ERROR": 0},
                    "edge_results": [],
                    "canvas_check": None,
                    "judge_eval": None,
                    "target_check": None,
                    "treatment_failure": {
                        "status": status,
                        "failure_class": treatment_error.get("failure_class") if treatment_error else status,
                        "error": treatment_error.get("error") if treatment_error else "",
                    },
                })
            continue
        problem = json.loads(problem_path.read_text())
        verifier = json.loads(verifier_path.read_text())
        cc = json.loads(canvas_check_path.read_text()) if canvas_check_path.exists() else None
        judge = json.loads(judge_path.read_text()) if judge_path.exists() else None
        target_check = json.loads(target_check_path.read_text()) if target_check_path.exists() else None

        rec = {
            "timestamp": verifier.get("timestamp") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "run_id": f"{batch_checkpoint['batch_id']}_t{target_idx:03d}_{iter_dir.name}",
            "batch_id": batch_checkpoint["batch_id"],
            "target_index": target_idx,
            "iter": int(iter_dir.name.replace("iter_", "")),
            "epoch": batch_checkpoint["epoch"],
            "prompt_version": batch_checkpoint["prompt_version"],
            "validator_library_version": batch_checkpoint["validator_version"],
            "config_version": batch_checkpoint.get("config_version", "v1"),
            "engine": batch_checkpoint.get("inner_engine", "claude"),
            "model": batch_checkpoint.get("inner_model", "unknown"),
            "inner_mode": batch_checkpoint.get("inner_mode"),
            "experiment_id": batch_checkpoint.get("experiment_id"),
            "treatment_id": batch_checkpoint.get("treatment_id"),
            "target": target,
            "problem_id": problem["id"],
            "verifier_version": verifier["verifier_version"],
            "n_nodes": verifier["n_nodes"],
            "n_edges": verifier["n_edges"],
            "node_truth": verifier["node_truth"],
            "edge_summary": verifier["edge_summary"],
            "edge_results": verifier["edge_results"],
            "canvas_check": {
                "check_version": cc["check_version"],
                "n_nodes": cc["n_nodes"],
                "summary": cc["summary"],
                "n_duplicates": cc["n_duplicates"],
                "duplicates": cc["duplicates"],
            } if cc else None,
            "judge_eval": {
                "judge_version": judge["judge_version"],
                "backend": judge.get("backend", "claude"),
                "model": judge["model"],
                "verdicts": judge["verdicts"],
                "overall": judge["overall"],
            } if judge else None,
            "target_check": {
                "target_check_version": target_check.get("target_check_version"),
                "status": target_check.get("status"),
                "reason": target_check.get("reason"),
                "goal_node": target_check.get("goal_node"),
                "goal_sympy_srepr": target_check.get("goal_sympy_srepr"),
                "expected_goals": target_check.get("expected_goals", []),
            } if target_check else None,
        }
        records.append(rec)
    return records


def backfill_batch(batch_dir: Path) -> int:
    checkpoint_path = batch_dir / "checkpoint.json"
    if not checkpoint_path.exists():
        print(f"[backfill] skip {batch_dir.name}: no checkpoint.json", file=sys.stderr)
        return 0
    cp = json.loads(checkpoint_path.read_text())
    epoch = cp["epoch"]
    epoch_dir = ROOT / "logs" / f"epoch_{epoch:03d}"
    epoch_dir.mkdir(parents=True, exist_ok=True)
    out_path = epoch_dir / f"batch_{cp['batch_id']}.jsonl"

    records = []
    for target_dir in sorted((batch_dir / "targets").glob("target_*")):
        target_json = target_dir / "target.json"
        if not target_json.exists():
            continue
        target_text = json.loads(target_json.read_text())["target"]
        records.extend(emit_from_target(target_dir, cp, target_text))

    with out_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"[backfill] {batch_dir.name} -> {out_path.name} ({len(records)} records)", file=sys.stderr)
    return len(records)


def main() -> int:
    batches_dir = ROOT / "_evolutions" / "batches"
    if not batches_dir.exists():
        print("[backfill] no batches dir", file=sys.stderr)
        return 0
    if len(sys.argv) > 1:
        targets = [batches_dir / sys.argv[1]]
    else:
        targets = sorted(d for d in batches_dir.iterdir() if d.is_dir() and not d.name.startswith("test_"))
    total = 0
    for bd in targets:
        total += backfill_batch(bd)
    print(f"[backfill] total records: {total}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
