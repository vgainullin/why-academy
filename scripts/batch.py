#!/usr/bin/env python3
"""Run inner_evolve.process_target across a targets file, sharing an LLM worker pool.

Usage:
  scripts/batch.sh derivations/targets/queue.txt                # evolution mode (default now)
  scripts/batch.sh --no-evolution derivations/targets/queue.txt # fall back to inner.sh per-target
  BATCH_PARALLEL=8 scripts/batch.sh derivations/targets/queue.txt
  scripts/batch.sh --inner-mode rule_executor --allow-treatment-failures derivations/targets/queue.txt

Evolution mode (default): batch.py owns an engine-specific pool of size
--parallel. Claude uses long-running sessions for cache reuse. Codex uses
resumable `codex exec` threads, bound target-locally across iterations.

--no-evolution: legacy path -- spawns scripts/inner.sh subprocesses per target,
no shared session, no per-target evolution. Kept for direct A/B vs the new path.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "derivations"))

TREATMENT_FAILURE_STATUSES = {
    "rule_plan_invalid",
    "rule_executor_coverage_gap",
    "rule_executor_fail",
    "substitution_structural_fail",
}


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def read_targets(path: Path) -> list[str]:
    out = []
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def current_epoch() -> int:
    state = json.loads((ROOT / "derivations" / "state.json").read_text())
    return int(state["epoch"])


def treatment_failure_status(metrics: dict) -> str | None:
    reason = metrics.get("failure_reason")
    if not reason:
        return None
    return re.sub(r"_iter_\d+$", "", str(reason))


def batch_exit_code(results: list[tuple[str, int, object]], *,
                    evolution_mode: bool,
                    inner_mode: str | None,
                    allow_treatment_failures: bool) -> tuple[int, dict[str, int]]:
    failures = [(target, rc, payload) for target, rc, payload in results if rc != 0]
    if not failures:
        return 0, {}
    if not (evolution_mode and inner_mode == "rule_executor" and allow_treatment_failures):
        return 1, {}

    expected: dict[str, int] = {}
    unexpected = 0
    for _target, _rc, payload in failures:
        status = treatment_failure_status(payload) if isinstance(payload, dict) else None
        if status in TREATMENT_FAILURE_STATUSES:
            expected[status] = expected.get(status, 0) + 1
        else:
            unexpected += 1
    if unexpected:
        expected["unexpected"] = unexpected
        return 1, expected
    return 0, expected


def run_one_legacy(target: str, out_dir: Path, *, batch_id: str,
                   target_index: int) -> tuple[str, int, str]:
    """Legacy --no-evolution path: spawn inner.sh per target."""
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    log_name = f"batch_{datetime.datetime.now().strftime('%H%M%S%f')}_t{target_index:03d}.log"
    log_path = out_dir / log_name
    with log_path.open("w") as f:
        f.write(f"# target: {target}\n# started: {started}\n\n")
        f.flush()
        proc = subprocess.run(
            [str(ROOT / "scripts" / "inner.sh"), target],
            stdout=f, stderr=subprocess.STDOUT,
            cwd=str(ROOT), env={**os.environ},
        )
    return (target, proc.returncode, str(log_path))


def run_one_pooled(target: str, target_index: int, batch_id: str, pool,
                   max_iter: int, inner_engine: str, judge_engine: str,
                   evolve_engine: str, judge_model: str, evolve_model: str,
                   inner_mode: str, experiment_id: str | None,
                   treatment_id: str | None
                   ) -> tuple[str, int, dict]:
    """Pooled path: in-thread process_target call sharing the worker pool."""
    from inner_evolve import process_target  # imported here so legacy path doesn't pay
    if hasattr(pool, "begin_target"):
        pool.begin_target(target_index)
    try:
        metrics = process_target(target, target_index, batch_id, pool,
                                 max_iter=max_iter,
                                 inner_engine=inner_engine,
                                 inner_mode=inner_mode,
                                 experiment_id=experiment_id,
                                 treatment_id=treatment_id,
                                 judge_engine=judge_engine,
                                 evolve_engine=evolve_engine,
                                 judge_model=judge_model,
                                 evolve_model=evolve_model)
        rc = 0 if metrics["accepted"] else 1
        return (target, rc, metrics)
    finally:
        if hasattr(pool, "end_target"):
            pool.end_target()


def main() -> int:
    ap = argparse.ArgumentParser()
    # Load config defaults
    sys.path.insert(0, str(ROOT / "derivations"))
    from config import load_config  # type: ignore
    from llm_cli import step_engine  # type: ignore
    cfg, cfg_version = load_config()

    ap.add_argument("queue", help="path to targets file")
    ap.add_argument("--parallel", type=int,
                    default=int(os.environ.get("BATCH_PARALLEL", cfg["batch"]["parallel"])))
    ap.add_argument("--no-evolution", action="store_true",
                    help="legacy: spawn inner.sh per target (no shared session, no evolution)")
    ap.add_argument("--evolution", action="store_true",
                    help="explicit opt-in for evolution mode (now the default)")
    ap.add_argument("--max-iter", type=int,
                    default=int(os.environ.get("MAX_ITER", cfg["evolution"]["max_iter"])),
                    help="max evolution iterations per target (evolution mode only)")
    ap.add_argument("--batch-id", default=None,
                    help="override the batch id (default: timestamp). Used to name the evolution workspace.")
    ap.add_argument("--inner-mode", choices=["agent", "json", "rule_executor"],
                    default=os.environ.get("INNER_MODE"),
                    help="inner generation mode. Default: json for Codex, agent for other engines.")
    ap.add_argument("--experiment-id", default=os.environ.get("EXPERIMENT_ID"),
                    help="optional experiment id recorded in checkpoint.json")
    ap.add_argument("--treatment-id", default=os.environ.get("TREATMENT_ID"),
                    help="optional treatment id recorded in checkpoint.json")
    ap.add_argument("--allow-treatment-failures", action="store_true",
                    default=env_flag("ALLOW_TREATMENT_FAILURES"),
                    help=("rule_executor pilot mode: return success when all failed targets are "
                          "explicit treatment failures or coverage gaps"))
    args = ap.parse_args()
    evolution_mode = not args.no_evolution
    inner_model = os.environ.get("INNER_MODEL", cfg["models"]["inner"])
    judge_model = os.environ.get("JUDGE_MODEL", cfg["models"]["judge"])
    evolve_model = os.environ.get("EVOLVE_MODEL", cfg["models"]["evolve"])
    inner_timeout = os.environ.get("INNER_TIMEOUT", cfg["timeouts_s"]["inner"])
    inner_budget = os.environ.get("INNER_BUDGET", cfg["budgets_usd"]["inner"])

    queue_path = Path(args.queue)
    targets = read_targets(queue_path)

    epoch = current_epoch()
    batch_log_dir = ROOT / "derivations" / "logs" / f"epoch_{epoch:03d}" / "batch"
    batch_log_dir.mkdir(parents=True, exist_ok=True)

    batch_id = args.batch_id or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "evolution (pooled)" if evolution_mode else "legacy (inner.sh per target)"
    print(f"[batch] queue={queue_path}  targets={len(targets)}  parallel={args.parallel}  "
          f"epoch={epoch}  mode={mode}  config={cfg_version}", file=sys.stderr)
    if evolution_mode:
        inner_engine = step_engine(cfg, "inner")
        judge_engine = step_engine(cfg, "judge")
        evolve_engine = step_engine(cfg, "evolve")
        inner_mode = args.inner_mode or ("json" if inner_engine == "codex" else "agent")
        print(f"[batch] batch_id={batch_id}  max_iter={args.max_iter}", file=sys.stderr)
        print(f"[batch] engines: inner={inner_engine} judge={judge_engine} evolve={evolve_engine}", file=sys.stderr)
        print(f"[batch] inner_mode={inner_mode}", file=sys.stderr)
        print(f"[batch] workspace: derivations/_evolutions/batches/{batch_id}/", file=sys.stderr)

    results = []
    active_inner_mode: str | None = None

    if not evolution_mode:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as ex:
            future_to_target = {
                ex.submit(run_one_legacy, t, batch_log_dir,
                          batch_id=batch_id, target_index=i): (i, t)
                for i, t in enumerate(targets)
            }
            for fut in concurrent.futures.as_completed(future_to_target):
                i, t = future_to_target[fut]
                target, rc, log = fut.result()
                tag = "OK" if rc == 0 else f"EXIT-{rc}"
                results.append((target, rc, log))
                print(f"[batch] {tag:8s}  t{i:03d}  {target[:90]}", file=sys.stderr)
    else:
        # Pooled evolution path: one engine-specific pool shared across targets.
        inner_engine = step_engine(cfg, "inner")
        inner_mode = args.inner_mode or ("json" if inner_engine == "codex" else "agent")
        active_inner_mode = inner_mode
        if inner_engine == "claude":
            from claude_worker import ClaudeWorkerPool
            pool = ClaudeWorkerPool(
                size=args.parallel,
                model=inner_model,
            )
        elif inner_engine == "codex":
            from llm_cli import CodexWorkerPool
            pool = CodexWorkerPool(
                size=args.parallel,
                model=inner_model,
                timeout_s=inner_timeout,
                cwd=ROOT,
            )
        else:
            from llm_cli import LLMExecPool
            pool = LLMExecPool(
                engine=inner_engine,
                model=inner_model,
                timeout_s=inner_timeout,
                budget=str(inner_budget),
            )
        try:
            print(f"[batch] worker pool: size={args.parallel}  inner_engine={inner_engine}  inner_model={inner_model}", file=sys.stderr)
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as ex:
                from claude_worker import QuotaExhaustedError as ClaudeQuotaExhaustedError
                from llm_cli import QuotaExhaustedError as LLMQuotaExhaustedError
                future_to_target = {
                    ex.submit(run_one_pooled, t, i, batch_id, pool,
                              args.max_iter, inner_engine, step_engine(cfg, "judge"),
                              step_engine(cfg, "evolve"), judge_model,
                              evolve_model, inner_mode, args.experiment_id,
                              args.treatment_id): (i, t)
                    for i, t in enumerate(targets)
                }
                for fut in concurrent.futures.as_completed(future_to_target):
                    i, t = future_to_target[fut]
                    try:
                        target, rc, metrics = fut.result()
                    except (ClaudeQuotaExhaustedError, LLMQuotaExhaustedError) as e:
                        print(f"[batch] quota exhausted while processing t{i:03d}: {e}", file=sys.stderr)
                        return 75
                    tag = "OK" if rc == 0 else f"EXIT-{rc}"
                    iters = metrics.get("n_iterations", "?")
                    reason = metrics.get("failure_reason") or ""
                    results.append((target, rc, metrics))
                    print(f"[batch] {tag:8s}  t{i:03d}  iters={iters}  {reason:25s}  {target[:70]}",
                          file=sys.stderr)
        finally:
            pool.close()

    n_ok = sum(1 for _, rc, _ in results if rc == 0)
    n_fail = len(results) - n_ok
    print(f"[batch] done: {n_ok}/{len(results)} OK ({n_fail} fail)", file=sys.stderr)
    if evolution_mode:
        # Emit per-batch jsonl into logs/epoch_NNN/ so the outer loop sees this
        # batch's data alongside any prior batches. Single-shot at batch close
        # so we avoid concurrency on the jsonl writer.
        bf = subprocess.run(
            [os.environ.get("DERIVATION_PYTHON") or sys.executable,
             str(ROOT / "derivations" / "backfill_logs.py"), batch_id],
            capture_output=True, text=True,
        )
        print(bf.stderr.strip(), file=sys.stderr)
        print(f"[batch] next: scripts/coalesce_batch.sh derivations/_evolutions/batches/{batch_id}", file=sys.stderr)
    else:
        print(f"[batch] per-run logs: {batch_log_dir}", file=sys.stderr)

    exit_code, allowed_counts = batch_exit_code(
        results,
        evolution_mode=evolution_mode,
        inner_mode=active_inner_mode,
        allow_treatment_failures=args.allow_treatment_failures,
    )
    if allowed_counts and exit_code == 0:
        print(f"[batch] allowing treatment failures: {json.dumps(dict(sorted(allowed_counts.items())))}",
              file=sys.stderr)
    elif allowed_counts:
        print(f"[batch] treatment failure allowance blocked by unexpected failures: "
              f"{json.dumps(dict(sorted(allowed_counts.items())))}",
              file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
