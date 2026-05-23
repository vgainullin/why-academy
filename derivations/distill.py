#!/usr/bin/env python3
"""Structured distillation utilities.

These commands turn local derivation runs into reproducible frontier and job
records. They are deliberately deterministic so the same logs + targets produce
the same target status map.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
SCHEMA_VERSION = "distillation.v1"


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_target(target: str) -> str:
    return re.sub(r"\s+", " ", target.strip())


def target_hash(target: str) -> str:
    return sha256_text(normalize_target(target))[:16]


def read_targets(path: Path) -> list[str]:
    targets: list[str] = []
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        targets.append(normalize_target(s))
    return targets


def load_state() -> dict:
    return json.loads((ROOT / "state.json").read_text())


def load_config() -> tuple[dict, str]:
    sys.path.insert(0, str(ROOT))
    from config import load_config as _load_config  # type: ignore

    return _load_config()


def iter_jsonl_records(log_root: Path | None = None):
    base = log_root or (ROOT / "logs")
    if not base.exists():
        return
    for jsonl in sorted(base.glob("epoch_*/*.jsonl")):
        with jsonl.open() as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception as e:
                    yield {
                        "_parse_error": f"{jsonl}:{line_no}: {e}",
                        "source_jsonl": str(jsonl),
                    }
                    continue
                rec["source_jsonl"] = str(jsonl)
                yield rec


def classify_record(rec: dict) -> str:
    edge_summary = rec.get("edge_summary") or {}
    if (edge_summary.get("FAIL", 0) or 0) + (edge_summary.get("ERROR", 0) or 0) > 0:
        return "verify_fail"
    canvas = rec.get("canvas_check")
    if canvas:
        summary = canvas.get("summary") or {}
        canvas_errors = (
            (summary.get("PARSE_ERROR_IN", 0) or 0)
            + (summary.get("RENDER_ERROR", 0) or 0)
            + (summary.get("PARSE_ERROR_OUT", 0) or 0)
            + (canvas.get("n_duplicates", 0) or 0)
        )
        if canvas_errors:
            return "canvas_fail"
    judge = rec.get("judge_eval")
    if judge:
        return "accepted" if judge.get("overall") == "PASS" else "judge_fail"
    return "unjudged"


def build_frontier(queue_path: Path, log_root: Path | None = None) -> dict:
    state = load_state()
    cfg, cfg_version = load_config()
    targets = read_targets(queue_path)
    records_by_hash: dict[str, list[dict]] = {target_hash(t): [] for t in targets}

    for rec in iter_jsonl_records(log_root):
        if rec.get("_parse_error"):
            continue
        target = rec.get("target")
        if not target:
            continue
        h = target_hash(target)
        records_by_hash.setdefault(h, []).append(rec)

    entries = []
    for index, target in enumerate(targets):
        h = target_hash(target)
        records = records_by_hash.get(h, [])
        classes: dict[str, int] = {}
        accepted = 0
        first_accept_iter = None
        engines = sorted({r.get("engine", "unknown") for r in records})
        models = sorted({r.get("model", "unknown") for r in records})
        for rec in records:
            cls = classify_record(rec)
            classes[cls] = classes.get(cls, 0) + 1
            if cls == "accepted":
                accepted += 1
                it = rec.get("iter")
                if isinstance(it, int) and (first_accept_iter is None or it < first_accept_iter):
                    first_accept_iter = it
        attempts = len(records)
        if accepted:
            status = "distilled"
        elif attempts:
            status = "explored_unaccepted"
        else:
            status = "unexplored"
        priority = 100 if status == "unexplored" else 50 if status == "explored_unaccepted" else 10
        priority += classes.get("verify_fail", 0) * 4
        priority += classes.get("canvas_fail", 0) * 3
        priority += classes.get("judge_fail", 0) * 2
        entries.append({
            "index": index,
            "target_hash": h,
            "target": target,
            "status": status,
            "priority": priority,
            "attempts": attempts,
            "accepted_attempts": accepted,
            "first_accept_iter": first_accept_iter,
            "failure_taxonomy": classes,
            "engines_seen": engines,
            "models_seen": models,
        })

    entries.sort(key=lambda e: (-e["priority"], e["index"]))
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "frontier",
        "created_at": utc_now(),
        "queue": str(queue_path),
        "state": state,
        "config_version": cfg_version,
        "engine_defaults": cfg.get("engines", {}),
        "model_defaults": cfg.get("models", {}),
        "target_count": len(entries),
        "status_counts": counts,
        "prompt_hashes": {
            "generate_derivation": file_hash(ROOT / "prompts" / "generate_derivation.md"),
            "evolve_prompt": file_hash(ROOT / "prompts" / "evolve_prompt.md"),
            "judge_eval": file_hash(ROOT / "prompts" / "judge_eval.md"),
        },
        "targets": entries,
    }


def write_frontier_markdown(frontier: dict, out_path: Path) -> None:
    lines = [
        "# Derivation Distillation Frontier",
        "",
        f"Generated: {frontier['created_at']}",
        f"Queue: `{frontier['queue']}`",
        f"Targets: {frontier['target_count']}",
        "",
        "## Status Counts",
        "",
    ]
    for k, v in sorted(frontier.get("status_counts", {}).items()):
        lines.append(f"- `{k}`: {v}")
    lines += [
        "",
        "## Targets",
        "",
        "| Priority | Status | Attempts | Accepted | Target |",
        "| ---: | --- | ---: | ---: | --- |",
    ]
    for e in frontier["targets"]:
        target = e["target"].replace("|", "\\|")
        lines.append(
            f"| {e['priority']} | `{e['status']}` | {e['attempts']} | "
            f"{e['accepted_attempts']} | {target} |"
        )
    out_path.write_text("\n".join(lines) + "\n")


def make_jobs(frontier: dict, *, limit: int, inner_engine: str, inner_model: str,
              judge_engine: str, judge_model: str, evolve_engine: str,
              evolve_model: str) -> list[dict]:
    state = frontier["state"]
    jobs = []
    selected = [e for e in frontier["targets"] if e["status"] != "distilled"]
    if limit > 0:
        selected = selected[:limit]
    for rank, entry in enumerate(selected):
        job_id = f"job_{entry['target_hash']}_{rank:03d}"
        jobs.append({
            "schema_version": SCHEMA_VERSION,
            "kind": "contribution_job",
            "job_id": job_id,
            "created_at": frontier["created_at"],
            "target_hash": entry["target_hash"],
            "target": entry["target"],
            "frontier_status": entry["status"],
            "priority": entry["priority"],
            "state": {
                "epoch": state["epoch"],
                "prompt_version": state["prompt_version"],
                "validator_version": state["validator_version"],
                "config_version": state.get("config_version"),
            },
            "prompt_hashes": frontier["prompt_hashes"],
            "engine_plan": {
                "inner": {"engine": inner_engine, "model": inner_model},
                "judge": {"engine": judge_engine, "model": judge_model},
                "evolve": {"engine": evolve_engine, "model": evolve_model},
            },
            "expected_outputs": [
                "problem.json",
                "problem.verifier.json",
                "problem.canvas_check.json",
                "problem.judge.json",
                "target_metrics.json",
            ],
            "isolation": {
                "one_target_per_batch": True,
                "batch_id_prefix": job_id,
                "network_required": True,
                "untrusted_output": True,
            },
        })
    return jobs


def summarize_batch(batch_id: str) -> dict:
    batch_dir = ROOT / "_evolutions" / "batches" / batch_id
    if not batch_dir.exists():
        raise FileNotFoundError(f"batch not found: {batch_dir}")
    checkpoint = json.loads((batch_dir / "checkpoint.json").read_text()) if (batch_dir / "checkpoint.json").exists() else {}
    targets = []
    totals = {"accepted": 0, "failed": 0, "iterations": 0}
    failure_reasons: dict[str, int] = {}
    for mp in sorted(batch_dir.glob("targets/target_*/target_metrics.json")):
        metrics = json.loads(mp.read_text())
        target_path = mp.parent / "target.json"
        target = json.loads(target_path.read_text()).get("target") if target_path.exists() else ""
        accepted = bool(metrics.get("accepted"))
        totals["accepted" if accepted else "failed"] += 1
        totals["iterations"] += int(metrics.get("n_iterations", 0) or 0)
        reason = metrics.get("failure_reason")
        if reason:
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
        targets.append({
            "target_index": metrics.get("target_index"),
            "target": target,
            "accepted": accepted,
            "n_iterations": metrics.get("n_iterations"),
            "failure_reason": reason,
            "iter_statuses": metrics.get("iter_statuses", []),
        })
    jsonl_path = ROOT / "logs" / f"epoch_{checkpoint.get('epoch', 0):03d}" / f"batch_{batch_id}.jsonl"
    jsonl_records = 0
    if jsonl_path.exists():
        jsonl_records = len([line for line in jsonl_path.read_text().splitlines() if line.strip()])
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "batch_summary",
        "created_at": utc_now(),
        "batch_id": batch_id,
        "batch_dir": str(batch_dir),
        "checkpoint": checkpoint,
        "totals": totals,
        "failure_reasons": failure_reasons,
        "jsonl_path": str(jsonl_path) if jsonl_path.exists() else None,
        "jsonl_records": jsonl_records,
        "targets": targets,
    }


def write_batch_markdown(summary: dict, out_path: Path) -> None:
    totals = summary["totals"]
    lines = [
        f"# Batch Summary: {summary['batch_id']}",
        "",
        f"Generated: {summary['created_at']}",
        f"Accepted: {totals['accepted']}",
        f"Failed: {totals['failed']}",
        f"Iterations: {totals['iterations']}",
        f"JSONL records: {summary['jsonl_records']}",
        "",
        "## Engine Plan",
        "",
    ]
    cp = summary.get("checkpoint", {})
    for step in ("inner", "judge", "evolve"):
        lines.append(f"- `{step}`: {cp.get(step + '_engine', '?')} / {cp.get(step + '_model', '?')}")
    lines += [
        "",
        "## Failure Reasons",
        "",
    ]
    if summary["failure_reasons"]:
        for reason, count in sorted(summary["failure_reasons"].items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"- `{reason}`: {count}")
    else:
        lines.append("- none")
    lines += [
        "",
        "## Targets",
        "",
        "| Target | Result | Iterations | Failure |",
        "| --- | --- | ---: | --- |",
    ]
    for t in summary["targets"]:
        result = "accepted" if t["accepted"] else "failed"
        target = (t.get("target") or "").replace("|", "\\|")
        lines.append(f"| t{int(t['target_index']):03d} {target} | {result} | {t['n_iterations']} | {t.get('failure_reason') or '-'} |")
    out_path.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("frontier", help="build target frontier from queue + logs")
    f.add_argument("--queue", default="derivations/targets/queue.txt")
    f.add_argument("--out", default="derivations/frontier/frontier.json")
    f.add_argument("--markdown", default="derivations/frontier/frontier.md")

    j = sub.add_parser("jobs", help="emit contribution jobs for undistilled targets")
    j.add_argument("--queue", default="derivations/targets/queue.txt")
    j.add_argument("--out", default="derivations/frontier/jobs.jsonl")
    j.add_argument("--limit", type=int, default=0, help="0 means all undistilled targets")
    j.add_argument("--inner-engine", default="codex")
    j.add_argument("--inner-model", default="gpt-5.2")
    j.add_argument("--judge-engine", default="deepseek")
    j.add_argument("--judge-model", default="deepseek-v4-flash")
    j.add_argument("--evolve-engine", default="codex")
    j.add_argument("--evolve-model", default="gpt-5.2")

    b = sub.add_parser("summarize-batch", help="write JSON/Markdown batch summary")
    b.add_argument("batch_id")
    b.add_argument("--out", default=None)
    b.add_argument("--markdown", default=None)

    args = ap.parse_args()

    if args.cmd == "frontier":
        out = Path(args.out)
        md = Path(args.markdown)
        out.parent.mkdir(parents=True, exist_ok=True)
        md.parent.mkdir(parents=True, exist_ok=True)
        frontier = build_frontier(PROJECT_ROOT / args.queue)
        out.write_text(json.dumps(frontier, indent=2))
        write_frontier_markdown(frontier, md)
        print(out)
        print(md)
        return 0

    if args.cmd == "jobs":
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        frontier = build_frontier(PROJECT_ROOT / args.queue)
        jobs = make_jobs(
            frontier,
            limit=args.limit,
            inner_engine=args.inner_engine,
            inner_model=args.inner_model,
            judge_engine=args.judge_engine,
            judge_model=args.judge_model,
            evolve_engine=args.evolve_engine,
            evolve_model=args.evolve_model,
        )
        with out.open("w") as fobj:
            for job in jobs:
                fobj.write(json.dumps(job) + "\n")
        print(out)
        print(f"jobs={len(jobs)}")
        return 0

    if args.cmd == "summarize-batch":
        summary = summarize_batch(args.batch_id)
        out = Path(args.out) if args.out else ROOT / "logs" / "smoke" / f"{args.batch_id}.summary.json"
        md = Path(args.markdown) if args.markdown else ROOT / "logs" / "smoke" / f"{args.batch_id}.summary.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        md.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2))
        write_batch_markdown(summary, md)
        print(out)
        print(md)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
