#!/usr/bin/env python3
"""One-command e2e probe for autonomous derivation learning.

The probe owns the temporal part of the test: it runs multiple internal
batches, scopes memory lookup to those batches, then verifies that repair and
cross-run memory artifacts exist and that the final outcome improved or passed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
BATCHES = ROOT / "derivations" / "_evolutions" / "batches"
PROBES = ROOT / "derivations" / "_evolutions" / "probes"
SMOKE_LOGS = ROOT / "derivations" / "logs" / "smoke"

TARGET_ALIASES = {
    "mass_spring": (
        "derive omega = sqrt(k/m) for a mass-spring system from m*xddot = -k*x "
        "and the trial-solution result xddot = -omega^2 * x"
    ),
    "vertical_loop": (
        "derive the minimum drop height h = 5R/2 for a ball completing a vertical loop, "
        "given (1) centripetal: m*g = m*v^2/R and (2) energy: "
        "(1/2)*m*v^2 + m*g*(2R) = m*g*h"
    ),
    "linear": "solve x + 2 = 5 for x",
}


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        return {"_error": str(e)}


def target_text(value: str) -> str:
    return TARGET_ALIASES.get(value, value)


def run_cmd(cmd: list[str], *, env: dict[str, str], log_path: Path | None = None) -> dict[str, Any]:
    started = time.time()
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w") as log:
            proc = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    else:
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)
    return {"returncode": proc.returncode, "duration_s": round(time.time() - started, 3)}


def iter_records(target_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for iter_dir in sorted(target_dir.glob("iter_*")):
        status_path = iter_dir / "status.txt"
        result = read_json(iter_dir / "result_event.json") or {}
        evolve = read_json(iter_dir / "evolve_result_event.json") or {}
        transition = read_json(iter_dir / "transition_score.json") or {}
        diagnosis = read_json(iter_dir / "failure_diagnosis.json") or {}
        target_check = read_json(iter_dir / "problem.target_check.json") or {}
        rows.append({
            "iter": iter_dir.name,
            "status": status_path.read_text().strip() if status_path.exists() else "missing",
            "has_problem": (iter_dir / "problem.json").exists(),
            "has_verifier": (iter_dir / "problem.verifier.json").exists(),
            "has_canvas": (iter_dir / "problem.canvas_check.json").exists(),
            "has_judge": (iter_dir / "problem.judge.json").exists(),
            "has_target_check": (iter_dir / "problem.target_check.json").exists(),
            "target_check_status": target_check.get("status"),
            "has_diagnosis": (iter_dir / "failure_diagnosis.json").exists(),
            "has_transition": (iter_dir / "transition_score.json").exists(),
            "has_evolve_event": (iter_dir / "evolve_result_event.json").exists(),
            "duration_ms": result.get("duration_ms"),
            "session_id": result.get("session_id") or result.get("thread_id"),
            "resumed": bool(result.get("resumed")),
            "evolve_via": evolve.get("via"),
            "evolve_session_id": evolve.get("session_id"),
            "evolve_resumed": bool((evolve.get("result") or {}).get("resumed")),
            "diagnosis_key": ":".join(str(x) for x in (
                diagnosis.get("gate"),
                diagnosis.get("failure_class"),
                diagnosis.get("rule") or "-",
            )) if diagnosis else None,
            "transition_verdict": transition.get("verdict"),
            "transition_score": transition.get("score"),
        })
    return rows


def analyze_batch(batch_id: str) -> dict[str, Any]:
    batch_dir = BATCHES / batch_id
    target_dir = batch_dir / "targets" / "target_000"
    metrics = read_json(target_dir / "target_metrics.json") or {}
    checkpoint = read_json(batch_dir / "checkpoint.json") or {}
    seed = read_json(target_dir / "seed_variant.json")
    iters = iter_records(target_dir)
    return {
        "batch_id": batch_id,
        "batch_dir": str(batch_dir),
        "exists": batch_dir.exists(),
        "checkpoint": checkpoint,
        "metrics": metrics,
        "accepted": bool(metrics.get("accepted")),
        "failure_reason": metrics.get("failure_reason"),
        "n_iterations": metrics.get("n_iterations", len(iters)),
        "seed": seed,
        "seed_batch_id": seed.get("batch_id") if isinstance(seed, dict) else None,
        "iters": iters,
        "has_diagnosis": any(i["has_diagnosis"] for i in iters),
        "has_addendum": bool(list(target_dir.glob("iter_*/addendum.md"))),
        "has_evolve_event": any(i["has_evolve_event"] for i in iters),
        "has_transition": any(i["has_transition"] for i in iters),
        "warm_reuse_seen": any(i["resumed"] or i["evolve_resumed"] for i in iters),
    }


def summarize_batch(batch_id: str, report_dir: Path, env: dict[str, str]) -> None:
    batch_dir = BATCHES / batch_id
    run_cmd([
        "scripts/distill.sh", "summarize-batch", batch_id,
        "--out", str(report_dir / f"{batch_id}.distill.json"),
        "--markdown", str(report_dir / f"{batch_id}.distill.md"),
    ], env=env)
    run_cmd(["scripts/coalesce_batch.sh", str(batch_dir)], env=env)


def classify(rounds: list[dict[str, Any]], batch_prefix: str) -> tuple[str, list[str]]:
    reasons = []
    if not rounds:
        return "FAIL_INFRA", ["no rounds executed"]

    for r in rounds:
        if not r["exists"]:
            return "FAIL_INFRA", [f"missing batch dir for {r['batch_id']}"]
        if r.get("checkpoint", {}).get("inner_mode") != "json":
            reasons.append(f"{r['batch_id']} did not run inner_mode=json")

    had_repair = any(r["has_diagnosis"] and r["has_addendum"] and r["has_evolve_event"] for r in rounds)
    later_seeded = any(
        isinstance(r.get("seed"), dict)
        and str(r.get("seed_batch_id", "")).startswith(batch_prefix)
        for r in rounds[1:]
    )
    accepted = any(r["accepted"] for r in rounds)
    target_drift = any(
        r.get("accepted")
        and any(i.get("status") == "PASS" and i.get("target_check_status") == "FAIL" for i in r["iters"])
        for r in rounds
    )
    improved_transition = any(
        i.get("transition_verdict") in ("improved", "accepted")
        for r in rounds
        for i in r["iters"]
    )

    if reasons:
        return "FAIL_INFRA", reasons
    if target_drift:
        return "FAIL_TARGET_DRIFT", ["a round was accepted even though target_check failed"]
    if not had_repair:
        if accepted:
            return "FAIL_NO_EVOLVE", ["target accepted before repair was needed; this did not test learning"]
        return "FAIL_NO_EVOLVE", ["no round produced diagnosis + addendum + evolve_result_event"]
    if len(rounds) > 1 and not later_seeded:
        return "FAIL_NO_MEMORY", ["later round did not seed from this probe prefix"]
    if accepted and later_seeded:
        return "PASS_ACCEPTED", ["accepted with scoped prior memory available"]
    if improved_transition and later_seeded:
        return "PASS_IMPROVED", ["memory/repaired run produced an improved transition"]
    return "FAIL_NO_IMPROVEMENT", ["repair/memory artifacts exist but no acceptance or improved transition was observed"]


def write_reports(report: dict[str, Any], report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        f"# E2E Learning Probe: {report['probe_id']}",
        "",
        f"- Verdict: `{report['verdict']}`",
        f"- Target: {report['target']}",
        f"- Rounds: {len(report['rounds'])}",
        f"- Report dir: `{report['report_dir']}`",
        f"- Validator dirs: `{os.pathsep.join(report.get('validator_dirs') or []) or 'none'}`",
        f"- Validator prepend: `{report.get('validator_prepend', False)}`",
        f"- Prompt addenda: `{os.pathsep.join(report.get('prompt_addenda') or []) or 'none'}`",
        "",
        "## Reasons",
    ]
    lines.extend(f"- {r}" for r in report["reasons"])
    if report.get("capability_repair_runs"):
        lines += ["", "## Capability Repair"]
        for run in report["capability_repair_runs"]:
            lines.append(
                f"- returncode={run['returncode']} duration_s={run['duration_s']} "
                f"out=`{run.get('out', '')}` log=`{run.get('log_path', '')}`"
            )
    lines += ["", "## Rounds"]
    for idx, r in enumerate(report["rounds"], start=1):
        lines += [
            f"### Round {idx}: `{r['batch_id']}`",
            f"- Accepted: {r['accepted']}",
            f"- Failure: `{r['failure_reason']}`",
            f"- Iterations: {r['n_iterations']}",
            f"- Seed batch: `{r['seed_batch_id']}`",
            f"- Diagnosis/addendum/evolve: {r['has_diagnosis']} / {r['has_addendum']} / {r['has_evolve_event']}",
            f"- Transition: {r['has_transition']}",
            f"- Warm reuse seen: {r['warm_reuse_seen']}",
            "",
            "| Iter | Status | Target | Duration ms | Resumed | Evolve Via | Evolve Resumed | Diagnosis | Transition |",
            "| --- | --- | --- | ---: | --- | --- | --- | --- | --- |",
        ]
        for it in r["iters"]:
            lines.append(
                f"| {it['iter']} | `{it['status']}` | `{it['target_check_status'] or ''}` | {it['duration_ms'] or ''} | "
                f"{it['resumed']} | `{it['evolve_via'] or ''}` | {it['evolve_resumed']} | "
                f"`{it['diagnosis_key'] or ''}` | `{it['transition_verdict'] or ''}` |"
            )
        lines.append("")
    (report_dir / "report.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="mass_spring",
                    help=f"target text or alias: {', '.join(sorted(TARGET_ALIASES))}")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--max-iter", type=int, default=3)
    ap.add_argument("--batch-prefix", default=None)
    ap.add_argument("--parallel", type=int, default=1)
    ap.add_argument("--inner-engine", default="codex")
    ap.add_argument("--inner-model", default="gpt-5.2")
    ap.add_argument("--inner-mode", default="json", choices=["json", "agent"])
    ap.add_argument("--judge-engine", default="deepseek")
    ap.add_argument("--judge-model", default="deepseek-v4-flash")
    ap.add_argument("--evolve-engine", default="codex")
    ap.add_argument("--evolve-model", default="gpt-5.2")
    ap.add_argument("--validator-dir", action="append", default=[],
                    help="trial validator directory to expose to verify.py without promotion")
    ap.add_argument("--validator-prepend", action="store_true",
                    help="load trial validator dirs before live validators so they can override rules")
    ap.add_argument("--prompt-addendum", action="append", default=[],
                    help="prompt addendum markdown file to append to the inner prompt")
    ap.add_argument("--capability-repair-dir", action="append", default=[],
                    help="failed/rejected capability proposal dir, or parent dir of proposals, to convert into prompt repairs")
    ap.add_argument("--keep-going", action="store_true",
                    help="run all rounds even if one round exits with an infra return code")
    args = ap.parse_args()

    if args.rounds < 2:
        print("[e2e] rounds must be >= 2 to test cross-run memory", file=sys.stderr)
        return 2

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_prefix = args.batch_prefix or f"e2e_learning_probe_{stamp}"
    probe_id = batch_prefix
    report_dir = PROBES / probe_id
    report_dir.mkdir(parents=True, exist_ok=True)
    SMOKE_LOGS.mkdir(parents=True, exist_ok=True)

    target = target_text(args.target)
    queue_path = report_dir / "target.txt"
    queue_path.write_text(target + "\n")

    env = os.environ.copy()
    prompt_addenda = [
        p for p in os.environ.get("DERIVATION_PROMPT_ADDENDA", "").split(os.pathsep)
        if p.strip()
    ] + args.prompt_addendum
    repair_runs = []
    if args.capability_repair_dir:
        repair_out = report_dir / "capability_prompt_repair.md"
        repair_cmd = ["scripts/capability_prompt_repair.sh", "--out", str(repair_out)]
        for proposal_dir in args.capability_repair_dir:
            repair_cmd.extend(["--proposal-dir", proposal_dir])
        repair_log = report_dir / "capability_prompt_repair.log"
        repair_run = run_cmd(repair_cmd, env=env, log_path=repair_log)
        repair_run.update({"log_path": str(repair_log), "out": str(repair_out)})
        repair_runs.append(repair_run)
        if repair_run["returncode"] != 0:
            print(f"[e2e] capability prompt repair failed; see {repair_log}", file=sys.stderr)
            return 2
        prompt_addenda.append(str(repair_out))

    env.update({
        "INNER_ENGINE": args.inner_engine,
        "INNER_MODEL": args.inner_model,
        "INNER_MODE": args.inner_mode,
        "JUDGE_ENGINE": args.judge_engine,
        "JUDGE_MODEL": args.judge_model,
        "EVOLVE_ENGINE": args.evolve_engine,
        "EVOLVE_MODEL": args.evolve_model,
        "BATCH_PARALLEL": str(args.parallel),
        "MAX_ITER": str(args.max_iter),
        "EVOLUTION_MEMORY_BATCH_PREFIX": batch_prefix,
    })
    if prompt_addenda:
        env["DERIVATION_PROMPT_ADDENDA"] = os.pathsep.join(prompt_addenda)
    if args.validator_dir:
        env["DERIVATION_VALIDATOR_DIRS"] = os.pathsep.join(args.validator_dir)
        if args.validator_prepend:
            env["DERIVATION_VALIDATOR_PREPEND"] = "1"

    runs = []
    for idx in range(args.rounds):
        batch_id = f"{batch_prefix}_r{idx + 1:02d}"
        log_path = SMOKE_LOGS / f"{batch_id}.log"
        print(f"[e2e] round {idx + 1}/{args.rounds}: {batch_id}", file=sys.stderr)
        run = run_cmd([
            "scripts/batch.sh",
            "--batch-id", batch_id,
            "--inner-mode", args.inner_mode,
            str(queue_path),
        ], env=env, log_path=log_path)
        run.update({"batch_id": batch_id, "log_path": str(log_path)})
        summarize_batch(batch_id, report_dir, env)
        analysis = analyze_batch(batch_id)
        analysis["run"] = run
        runs.append(analysis)
        if run["returncode"] in (75, 127) and not args.keep_going:
            break

    verdict, reasons = classify(runs, batch_prefix)
    report = {
        "probe_id": probe_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "target": target,
        "batch_prefix": batch_prefix,
        "report_dir": str(report_dir),
        "validator_dirs": args.validator_dir,
        "validator_prepend": args.validator_prepend,
        "prompt_addenda": prompt_addenda,
        "capability_repair_runs": repair_runs,
        "verdict": verdict,
        "reasons": reasons,
        "rounds": runs,
    }
    write_reports(report, report_dir)
    print(json.dumps({
        "verdict": verdict,
        "report": str(report_dir / "report.md"),
        "probe_id": probe_id,
    }, indent=2))
    return 0 if verdict.startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
