#!/usr/bin/env python3
"""Build one jsonl log line from a verifier sidecar + invocation metadata.

Schema matches what prompts/outer_loop_epoch.md expects to aggregate.
Writes to derivations/logs/epoch_<NNN>/run_<RUN_ID>.jsonl (one line per run; append-safe).
"""
from __future__ import annotations
import argparse
import json
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sidecar", required=True, help="path to <problem>.verifier.json")
    ap.add_argument("--target", required=True, help="the target equation passed as $ARG to the inner-loop prompt")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--model", default="unknown")
    args = ap.parse_args()

    state = json.loads((ROOT / "state.json").read_text())
    sidecar_path = Path(args.sidecar)
    sidecar = json.loads(sidecar_path.read_text())

    # Auto-discover sidecars written by other wrapper steps.
    canvas_path = sidecar_path.with_name(sidecar_path.name.replace(".verifier.json", ".canvas_check.json"))
    judge_path  = sidecar_path.with_name(sidecar_path.name.replace(".verifier.json", ".judge.json"))

    canvas_section = None
    if canvas_path.exists():
        cdata = json.loads(canvas_path.read_text())
        canvas_section = {
            "check_version": cdata["check_version"],
            "n_nodes": cdata["n_nodes"],
            "summary": cdata["summary"],
            "n_duplicates": cdata["n_duplicates"],
            "duplicates": cdata["duplicates"],
        }

    judge_section = None
    if judge_path.exists():
        jdata = json.loads(judge_path.read_text())
        judge_section = {
            "judge_version": jdata["judge_version"],
            "model": jdata["model"],
            "verdicts": jdata["verdicts"],
            "overall": jdata["overall"],
        }

    record = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "run_id": args.run_id,
        "epoch": state["epoch"],
        "prompt_version": state["prompt_version"],
        "validator_library_version": state["validator_version"],
        "config_version": state.get("config_version", "v1"),
        "model": args.model,
        "target": args.target,
        "problem_id": sidecar["problem_id"],
        "verifier_version": sidecar["verifier_version"],
        "n_nodes": sidecar["n_nodes"],
        "n_edges": sidecar["n_edges"],
        "node_truth": sidecar["node_truth"],
        "edge_summary": sidecar["edge_summary"],
        "edge_results": sidecar["edge_results"],
        "canvas_check": canvas_section,
        "judge_eval": judge_section,
    }

    epoch_dir = ROOT / "logs" / f"epoch_{state['epoch']:03d}"
    epoch_dir.mkdir(parents=True, exist_ok=True)
    out = epoch_dir / f"run_{args.run_id}.jsonl"
    with out.open("a") as f:
        f.write(json.dumps(record) + "\n")

    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
