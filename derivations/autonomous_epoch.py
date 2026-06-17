#!/usr/bin/env python3
"""Autonomous epoch runner.

State machine that drives one full epoch end-to-end:
  GENERATE   -> batch generation across the cohort
  ANALYZE    -> outer loop drafts proposals
  EXPERIMENT -> optional A/B test of pipeline changes (control vs treatment)
  IMPLEMENT  -> for each proposal, implement+closure_test+auto-promote-or-revert
  CLOSE      -> holdout regression + bump epoch in state.json

All thresholds, gates, and limits are config-driven (configs/v<N>.json runner section).

Resumable: re-running picks up at the current phase. Disk artifacts are the
truth; _epoch_state.json is a hint. Catches QuotaExhaustedError, writes
PAUSED_QUOTA state, and exits 0 (so a wrapper cron can re-launch later).
Any other unexpected exception writes PAUSED_ERROR with a traceback so the
runner can be re-launched after the underlying issue is fixed.
"""
from __future__ import annotations
import argparse
import datetime
import json
import os
import re
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
from config import load_config  # noqa: E402


PHASES = ["GENERATE", "ANALYZE", "EXPERIMENT", "IMPLEMENT", "CLOSE", "DONE"]
RULE_RE = re.compile(r"^\*\*Affected rule\*\*:\s*`?([^\s`]+)`?", re.MULTILINE)
RESUMABLE_PAUSE_STATES = {"PAUSED_QUOTA", "PAUSED_ERROR", "PAUSED_WALLCLOCK", "PAUSED_SIGNAL"}
STATE_JSON = "derivations/state.json"

# Exit codes from batch.py that indicate "no useful work done" (don't advance).
BATCH_FATAL_EXIT_CODES = {2, 70}


def _state_path(cfg: dict) -> Path:
    rel = cfg.get("runner", {}).get("state_file", "derivations/_epoch_state.json")
    return PROJECT_ROOT / rel


def load_state(cfg: dict) -> dict:
    p = _state_path(cfg)
    if not p.exists():
        return {"phase": "GENERATE", "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    return json.loads(p.read_text())


def save_state(cfg: dict, state: dict) -> None:
    p = _state_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    p.write_text(json.dumps(state, indent=2))


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(str(c) for c in cmd)}", file=sys.stderr)
    return subprocess.run(cmd, cwd=str(PROJECT_ROOT), **kw)


def _state_json_path() -> Path:
    return PROJECT_ROOT / STATE_JSON


def _read_state_json() -> dict:
    return json.loads(_state_json_path().read_text())


def epoch_num() -> int:
    return int(_read_state_json()["epoch"])


def validator_version() -> str:
    return _read_state_json()["validator_version"]


def bump_state_field(field: str, new_val) -> None:
    p = _state_json_path()
    d = json.loads(p.read_text())
    d[field] = new_val
    p.write_text(json.dumps(d, indent=2))


def snapshot_state_json() -> bytes:
    """Snapshot the full state.json so phase_implement can restore it atomically."""
    p = _state_json_path()
    return p.read_bytes()


def restore_state_json(snapshot: bytes) -> None:
    p = _state_json_path()
    p.write_bytes(snapshot)


def affected_rule_from_proposal(path: Path) -> str | None:
    m = RULE_RE.search(path.read_text())
    return m.group(1) if m else None


def snapshot_validator(rule: str | None) -> dict | None:
    if not rule:
        return None
    path = PROJECT_ROOT / "derivations" / "validators" / f"{rule}.py"
    existed = path.exists()
    return {
        "path": path,
        "existed": existed,
        "content": path.read_bytes() if existed else None,
    }


def restore_validator_snapshot(snapshot: dict | None) -> None:
    if not snapshot:
        return
    path = snapshot["path"]
    if snapshot["existed"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(snapshot["content"])
    else:
        path.unlink(missing_ok=True)


def clear_stale_proposals(epoch_dir: Path, handled: set[str]) -> int:
    """Remove proposal_*.md files that have no closure sidecar and aren't in proposals_handled.

    Called before re-running ANALYZE so a partial outer-loop crash doesn't leave
    duplicate or stale proposals for IMPLEMENT to process.
    Returns the count of removed files.
    """
    removed = 0
    for prop in epoch_dir.glob("proposal_*.md"):
        if "_closure" in prop.name:
            continue
        if prop.name in handled:
            continue
        closure_sidecar = prop.with_name(prop.stem + "_closure.json")
        if closure_sidecar.exists():
            continue
        prop.unlink()
        removed += 1
    return removed


# ── PHASE: GENERATE ─────────────────────────────────────────────────────
def phase_generate(cfg: dict, state: dict, queue_path: Path) -> None:
    """Run the inner-loop batch. Resumable via batch_id."""
    if "batch_id" not in state:
        state["batch_id"] = f"epoch_{epoch_num():03d}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        save_state(cfg, state)
    bid = state["batch_id"]
    print(f"[runner] GENERATE: batch_id={bid}  queue={queue_path}", file=sys.stderr)
    r = run([str(PROJECT_ROOT / "scripts" / "batch.sh"),
             "--batch-id", bid, str(queue_path)])
    if r.returncode == 75:
        state["resume_phase"] = "GENERATE"
        state["phase"] = "PAUSED_QUOTA"
        state["paused_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save_state(cfg, state)
        return
    if r.returncode in BATCH_FATAL_EXIT_CODES:
        # Preflight failure (70) or config/contract violation (2): no work was
        # done. Don't advance to ANALYZE with an empty log set.
        state["resume_phase"] = "GENERATE"
        state["phase"] = "PAUSED_ERROR"
        state["error"] = f"batch.sh exited {r.returncode} (fatal; no generation occurred)"
        state["paused_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save_state(cfg, state)
        return
    if r.returncode != 0:
        # Exit code 1: partial completion (some targets failed). That's OK;
        # the batch is resumable and the outer loop can analyze partial data.
        print(f"[runner] GENERATE returned {r.returncode} (partial completion; some targets failed)", file=sys.stderr)
    state["phase"] = "ANALYZE"
    save_state(cfg, state)


# ── PHASE: ANALYZE ──────────────────────────────────────────────────────
def phase_analyze(cfg: dict, state: dict) -> None:
    """Run the outer loop. Resumable: skip if summary.md already exists."""
    epoch_dir = PROJECT_ROOT / "derivations" / "reports" / f"epoch_{epoch_num():03d}"
    summary = epoch_dir / "summary.md"
    if summary.exists():
        print(f"[runner] ANALYZE: summary.md exists; skipping outer call", file=sys.stderr)
    else:
        # Clear stale proposals from a partial outer-loop crash before re-running.
        handled = set(state.get("proposals_handled", []))
        removed = clear_stale_proposals(epoch_dir, handled)
        if removed:
            print(f"[runner] ANALYZE: cleared {removed} stale proposal(s) from prior partial run", file=sys.stderr)
        print(f"[runner] ANALYZE: running outer loop on epoch_{epoch_num():03d}", file=sys.stderr)
        r = run([str(PROJECT_ROOT / "scripts" / "outer.sh"),
                 f"epoch_{epoch_num():03d}"])
        if r.returncode != 0:
            print(f"[runner] ANALYZE failed rc={r.returncode}", file=sys.stderr)
    state["phase"] = "EXPERIMENT"
    state["proposals_handled"] = state.get("proposals_handled", [])
    save_state(cfg, state)


# ── PHASE: EXPERIMENT ───────────────────────────────────────────────────
def _experiment_targets(cfg: dict, state: dict, queue_path: Path) -> list[str]:
    """Select up to max_targets targets for the A/B experiment."""
    exp_cfg = cfg.get("runner", {}).get("experiment", {})
    max_targets = int(exp_cfg.get("max_targets", 5))
    targets = []
    for line in queue_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            targets.append(line)
            if len(targets) >= max_targets:
                break
    return targets


def _write_experiment_queue(targets: list[str], batch_id: str) -> Path:
    """Write a temp queue file for the experiment batches."""
    queue_path = PROJECT_ROOT / "derivations" / "targets" / f".experiment_{batch_id}.txt"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(f"# Experiment queue for {batch_id}\n\n" + "\n".join(targets) + "\n")
    return queue_path


def _run_experiment_batch(batch_id: str, queue_path: Path, *, inner_mode: str,
                          experiment_id: str, treatment_id: str | None = None,
                          normalization_mode: str | None = None,
                          allow_treatment_failures: bool = False) -> int:
    """Run one batch (control or treatment) and return its exit code."""
    cmd = [
        str(PROJECT_ROOT / "scripts" / "batch.sh"),
        "--batch-id", batch_id,
        "--inner-mode", inner_mode,
        "--experiment-id", experiment_id,
        str(queue_path),
    ]
    if treatment_id:
        cmd += ["--treatment-id", treatment_id]
    if normalization_mode:
        cmd += ["--normalization-mode", normalization_mode]
    if allow_treatment_failures:
        cmd += ["--allow-treatment-failures"]
    r = run(cmd)
    return r.returncode


def phase_experiment(cfg: dict, state: dict, queue_path: Path) -> None:
    """Optional A/B experiment: test a pipeline change (e.g. rule_executor) against control.

    If experiment is not enabled in config, or no proposals from ANALYZE,
    skip directly to IMPLEMENT.
    """
    exp_cfg = cfg.get("runner", {}).get("experiment", {})
    if not exp_cfg.get("enabled", False):
        print("[runner] EXPERIMENT: disabled in config; skipping to IMPLEMENT", file=sys.stderr)
        state["phase"] = "IMPLEMENT"
        save_state(cfg, state)
        return

    epoch = epoch_num()
    epoch_dir = PROJECT_ROOT / "derivations" / "reports" / f"epoch_{epoch:03d}"

    # Use the experiment_id from state, or create one
    if "experiment_id" not in state:
        state["experiment_id"] = f"epoch_{epoch:03d}_experiment_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        save_state(cfg, state)
    exp_id = state["experiment_id"]

    # If we already have a verdict, skip
    verdict_path = epoch_dir / "experiment_verdict.json"
    if verdict_path.exists():
        print(f"[runner] EXPERIMENT: verdict exists; skipping to IMPLEMENT", file=sys.stderr)
        state["phase"] = "IMPLEMENT"
        save_state(cfg, state)
        return

    print(f"[runner] EXPERIMENT: experiment_id={exp_id}", file=sys.stderr)

    # Select targets
    targets = _experiment_targets(cfg, state, queue_path)
    if len(targets) < 2:
        print(f"[runner] EXPERIMENT: need >=2 targets, got {len(targets)}; skipping", file=sys.stderr)
        state["phase"] = "IMPLEMENT"
        save_state(cfg, state)
        return

    queue = _write_experiment_queue(targets, exp_id)

    control_bid = f"{exp_id}_control"
    treatment_bid = f"{exp_id}_treatment"
    control_dir = PROJECT_ROOT / "derivations" / "_evolutions" / "batches" / control_bid
    treatment_dir = PROJECT_ROOT / "derivations" / "_evolutions" / "batches" / treatment_bid

    # Resume: skip batches that already completed
    control_done = (control_dir / "checkpoint.json").exists() and \
        any((control_dir / "targets").glob("target_*/target_metrics.json"))
    treatment_done = (treatment_dir / "checkpoint.json").exists() and \
        any((treatment_dir / "targets").glob("target_*/target_metrics.json"))

    # 1. Control batch
    if not control_done:
        print(f"[runner] EXPERIMENT: running control batch ({exp_cfg.get('control_inner_mode', 'json')})", file=sys.stderr)
        rc = _run_experiment_batch(control_bid, queue,
                                   inner_mode=exp_cfg.get("control_inner_mode", "json"),
                                   experiment_id=exp_id)
        if rc == 75:
            state["resume_phase"] = "EXPERIMENT"
            _write_pause_state(cfg, state, "PAUSED_QUOTA", resume_phase="EXPERIMENT")
            queue.unlink(missing_ok=True)
            return
        if rc in BATCH_FATAL_EXIT_CODES:
            _write_pause_state(cfg, state, "PAUSED_ERROR",
                               resume_phase="EXPERIMENT",
                               error=f"control batch exited {rc}")
            queue.unlink(missing_ok=True)
            return
    else:
        print(f"[runner] EXPERIMENT: control batch already complete; skipping", file=sys.stderr)

    # 2. Treatment batch
    treatment_mode = exp_cfg.get("treatment_inner_mode", "rule_executor")
    norm_mode = exp_cfg.get("treatment_normalization_mode", "preserve-executor-boundaries")
    if not treatment_done:
        print(f"[runner] EXPERIMENT: running treatment batch ({treatment_mode})", file=sys.stderr)
        rc = _run_experiment_batch(treatment_bid, queue,
                                   inner_mode=treatment_mode,
                                   experiment_id=exp_id,
                                   treatment_id="experiment_treatment",
                                   normalization_mode=norm_mode,
                                   allow_treatment_failures=True)
        if rc == 75:
            state["resume_phase"] = "EXPERIMENT"
            _write_pause_state(cfg, state, "PAUSED_QUOTA", resume_phase="EXPERIMENT")
            queue.unlink(missing_ok=True)
            return
        if rc in BATCH_FATAL_EXIT_CODES:
            _write_pause_state(cfg, state, "PAUSED_ERROR",
                               resume_phase="EXPERIMENT",
                               error=f"treatment batch exited {rc}")
            queue.unlink(missing_ok=True)
            return
    else:
        print(f"[runner] EXPERIMENT: treatment batch already complete; skipping", file=sys.stderr)

    # 3. A/B comparison
    print(f"[runner] EXPERIMENT: running ab_compare", file=sys.stderr)
    ab_py = PROJECT_ROOT / "derivations" / "ab_compare.py"
    r = run([os.environ.get("DERIVATION_PYTHON") or sys.executable,
             str(ab_py),
             "--control", str(control_dir),
             "--treatment", str(treatment_dir),
             "--experiment-id", exp_id])
    comparison_path = treatment_dir / "ab_comparison.json"
    if r.returncode != 0 or not comparison_path.exists():
        print(f"[runner] EXPERIMENT: ab_compare failed rc={r.returncode}; skipping", file=sys.stderr)
        verdict = {
            "experiment_id": exp_id,
            "status": "comparison_failed",
            "ab_compare_rc": r.returncode,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    else:
        comparison = json.loads(comparison_path.read_text())
        paired = comparison.get("paired", {})
        delta = paired.get("acceptance_delta", 0.0)
        min_delta = float(exp_cfg.get("min_acceptance_delta", 0.0))
        won = delta > min_delta

        verdict = {
            "experiment_id": exp_id,
            "status": "treatment_won" if won else "control_won" if delta < 0 else "neutral",
            "acceptance_delta": delta,
            "control_acceptance_rate": paired.get("control_acceptance_rate"),
            "treatment_acceptance_rate": paired.get("treatment_acceptance_rate"),
            "first_try_pass_delta": paired.get("first_try_pass_delta"),
            "n_pairs": paired.get("n_pairs"),
            "both_accepted": paired.get("both_accepted"),
            "treatment_only_accepted": paired.get("treatment_only_accepted"),
            "control_only_accepted": paired.get("control_only_accepted"),
            "both_failed": paired.get("both_failed"),
            "promote_on_win": bool(exp_cfg.get("promote_on_win", False)),
            "comparison_path": str(comparison_path),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        if won and exp_cfg.get("promote_on_win", False):
            print(f"[runner] EXPERIMENT: treatment won (delta={delta:.2%}); promoting config", file=sys.stderr)
            # Promote treatment settings as the new default for next epoch's GENERATE
            state["promoted_experiment"] = {
                "inner_mode": treatment_mode,
                "normalization_mode": norm_mode,
            }

    epoch_dir.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(verdict, indent=2))
    print(f"[runner] EXPERIMENT: verdict={verdict['status']}  delta={verdict.get('acceptance_delta', 'n/a')}", file=sys.stderr)

    queue.unlink(missing_ok=True)
    state["phase"] = "IMPLEMENT"
    save_state(cfg, state)


# ── PHASE: IMPLEMENT ────────────────────────────────────────────────────
def phase_implement(cfg: dict, state: dict) -> None:
    """For each top-K proposal: implement, closure_test, auto-promote or auto-revert."""
    runner_cfg = cfg.get("runner", {})
    epoch_cfg = runner_cfg.get("epoch", {})
    max_proposals = int(epoch_cfg.get("max_proposals_per_epoch", 5))
    stop_on_fail = bool(epoch_cfg.get("stop_on_first_failed_promotion", False))
    min_lift = float(runner_cfg.get("auto_promote", {}).get("min_lift_fraction", 0.4))
    revert_on_regress = bool(runner_cfg.get("auto_promote", {}).get("revert_on_holdout_regression", True))

    epoch_dir = PROJECT_ROOT / "derivations" / "reports" / f"epoch_{epoch_num():03d}"
    proposals = sorted(p for p in epoch_dir.glob("proposal_*.md") if "_closure" not in p.name)
    proposals = proposals[:max_proposals]
    handled = set(state.get("proposals_handled", []))

    for prop in proposals:
        if prop.name in handled:
            print(f"[runner] IMPLEMENT: skip {prop.name} (already handled)", file=sys.stderr)
            continue
        print(f"[runner] IMPLEMENT: {prop.name}", file=sys.stderr)

        # Skip non-actionable proposals (INVESTIGATE etc.)
        kind = ""
        for line in prop.read_text().splitlines():
            if line.startswith("**Kind**:"):
                kind = line.split(":", 1)[1].strip()
                break

        # PROMPT_UPDATE proposals go through promote_prompt.sh, not implement.sh.
        if kind == "PROMPT_UPDATE":
            print(f"  -> PROMPT_UPDATE: promoting via promote_prompt.sh", file=sys.stderr)
            pre_state_json = snapshot_state_json()
            pre_prompt = (PROJECT_ROOT / "derivations" / "prompts" / "generate_derivation.md").read_bytes()

            def _revert_prompt() -> None:
                restore_state_json(pre_state_json)
                (PROJECT_ROOT / "derivations" / "prompts" / "generate_derivation.md").write_bytes(pre_prompt)

            r = run([str(PROJECT_ROOT / "scripts" / "promote_prompt.sh"), str(prop)])
            if r.returncode == 75:
                _revert_prompt()
                state["resume_phase"] = "IMPLEMENT"
                _write_pause_state(cfg, state, "PAUSED_QUOTA", resume_phase="IMPLEMENT")
                return
            if r.returncode != 0:
                # promote_prompt.sh exits 2 (DENIED), 3 (no Promote section), 4 (no addenda),
                # 5 (checkpoint exists). All are safe no-ops or explicit rejections.
                print(f"  -> promote_prompt.sh rc={r.returncode}; marking handled", file=sys.stderr)
                _revert_prompt()
                handled.add(prop.name)
                state["proposals_handled"] = sorted(handled)
                save_state(cfg, state)
                if stop_on_fail:
                    break
                continue

            print(f"  -> PROMOTED prompt (promote_prompt.sh rc=0)", file=sys.stderr)
            handled.add(prop.name)
            state["proposals_handled"] = sorted(handled)
            save_state(cfg, state)
            continue

        if kind not in ("NEW_VALIDATOR", "STRENGTHEN_VALIDATOR", "WEAKEN_VALIDATOR"):
            print(f"  -> skip kind={kind!r} (not a validator or prompt change)", file=sys.stderr)
            handled.add(prop.name)
            state["proposals_handled"] = sorted(handled)
            save_state(cfg, state)
            continue

        rule = affected_rule_from_proposal(prop)
        if not rule:
            print("  -> skip: validator proposal has no affected rule", file=sys.stderr)
            handled.add(prop.name)
            state["proposals_handled"] = sorted(handled)
            save_state(cfg, state)
            continue
        pre_validator_v = validator_version()
        pre_validator_snapshot = snapshot_validator(rule)
        pre_state_json = snapshot_state_json()

        def _revert_to_pre() -> None:
            restore_validator_snapshot(pre_validator_snapshot)
            restore_state_json(pre_state_json)

        # 1. Implement
        r = run([str(PROJECT_ROOT / "scripts" / "implement.sh"), str(prop)])
        if r.returncode == 75:
            _revert_to_pre()
            state["resume_phase"] = "IMPLEMENT"
            state["phase"] = "PAUSED_QUOTA"
            state["paused_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            save_state(cfg, state)
            return
        if r.returncode != 0:
            print(f"  -> implement.sh failed rc={r.returncode}; marking handled", file=sys.stderr)
            _revert_to_pre()
            handled.add(prop.name)
            state["proposals_handled"] = sorted(handled)
            save_state(cfg, state)
            if stop_on_fail:
                break
            continue

        # 2. Closure test
        r = run([str(PROJECT_ROOT / "scripts" / "closure_test.sh"), str(prop)])
        if r.returncode == 75:
            _revert_to_pre()
            state["resume_phase"] = "IMPLEMENT"
            state["phase"] = "PAUSED_QUOTA"
            state["paused_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            save_state(cfg, state)
            return
        closure_sidecar = prop.with_name(prop.stem + "_closure.json")
        if not closure_sidecar.exists():
            print(f"  -> closure_test produced no sidecar; treating as FAILED", file=sys.stderr)
            _revert_to_pre()
            handled.add(prop.name)
            state["proposals_handled"] = sorted(handled)
            save_state(cfg, state)
            if stop_on_fail:
                break
            continue
        closure = json.loads(closure_sidecar.read_text())
        lift = closure.get("lift_fraction", 0.0)
        regressed = closure.get("holdout_regressed")

        if lift >= min_lift and (not regressed or not revert_on_regress):
            print(f"  -> PROMOTED  lift={lift:.2%}  regressed={regressed}", file=sys.stderr)
            # validator_version was bumped by implement.sh after LLM success; nothing more to do
        else:
            print(f"  -> REVERTED  lift={lift:.2%}  regressed={regressed}", file=sys.stderr)
            # Revert validator code AND state.json to exact pre-implementation state.
            _revert_to_pre()
            if stop_on_fail:
                handled.add(prop.name)
                state["proposals_handled"] = sorted(handled)
                save_state(cfg, state)
                break

        handled.add(prop.name)
        state["proposals_handled"] = sorted(handled)
        save_state(cfg, state)

    state["phase"] = "CLOSE"
    save_state(cfg, state)


# ── PHASE: CLOSE ────────────────────────────────────────────────────────
def phase_close(cfg: dict, state: dict) -> None:
    """Bump the epoch. Holdout runs as part of implement.sh; we don't redo it here."""
    new_epoch = epoch_num() + 1
    print(f"[runner] CLOSE: epoch_{epoch_num():03d} -> epoch_{new_epoch:03d}", file=sys.stderr)
    bump_state_field("epoch", new_epoch)
    state["phase"] = "DONE"
    state["closed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    state["closed_epoch"] = new_epoch - 1
    save_state(cfg, state)


# ── DRIVER ──────────────────────────────────────────────────────────────
def _resume_from_pause(state: dict, cfg: dict) -> None:
    """Clear any pause state and set phase to the resume point."""
    phase = state.get("phase", "GENERATE")
    if phase in RESUMABLE_PAUSE_STATES:
        resume = state.get("resume_phase", "GENERATE")
        print(f"[runner] {phase} from previous run; resuming at phase={resume}", file=sys.stderr)
        state["phase"] = resume
        state.pop("resume_phase", None)
        state.pop("error", None)
        state.pop("paused_at", None)
        save_state(cfg, state)


def _write_pause_state(cfg: dict, state: dict, pause_phase: str,
                       resume_phase: str | None = None, error: str | None = None) -> None:
    """Write a pause state and persist it."""
    state["phase"] = pause_phase
    if resume_phase:
        state["resume_phase"] = resume_phase
    if error:
        state["error"] = error
    state["paused_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_state(cfg, state)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="derivations/targets/cohort_v1.txt",
                    help="path to cohort queue for the GENERATE phase")
    ap.add_argument("--reset", action="store_true",
                    help="clear _epoch_state.json before starting (start the epoch fresh)")
    args = ap.parse_args()

    cfg, cfg_version = load_config()
    state_path = _state_path(cfg)

    if args.reset and state_path.exists():
        state_path.unlink()

    state = load_state(cfg)
    _resume_from_pause(state, cfg)

    epoch_start_wall = time.time()
    max_wall = float(cfg.get("runner", {}).get("epoch", {}).get("max_wall_clock_s_per_epoch", 7200))

    # Signal handler: write PAUSED_SIGNAL and exit 0 so a cron wrapper can re-launch.
    _signal_received = None

    def _signal_handler(signum, frame):
        nonlocal _signal_received
        _signal_received = signum

    prev_term = signal.signal(signal.SIGTERM, _signal_handler)
    prev_int = signal.signal(signal.SIGINT, _signal_handler)

    try:
        while state.get("phase") not in ("DONE", "PAUSED_QUOTA", "PAUSED_ERROR", "PAUSED_SIGNAL"):
            if _signal_received is not None:
                sig_name = signal.Signals(_signal_received).name
                print(f"[runner] received {sig_name}; writing PAUSED_SIGNAL and exiting", file=sys.stderr)
                _write_pause_state(cfg, state, "PAUSED_SIGNAL",
                                   resume_phase=state.get("phase", "GENERATE"),
                                   error=f"signal: {sig_name}")
                return 0

            phase = state["phase"]
            if phase == "GENERATE":
                phase_generate(cfg, state, Path(args.queue))
            elif phase == "ANALYZE":
                phase_analyze(cfg, state)
            elif phase == "EXPERIMENT":
                phase_experiment(cfg, state, Path(args.queue))
            elif phase == "IMPLEMENT":
                phase_implement(cfg, state)
            elif phase == "CLOSE":
                phase_close(cfg, state)
            else:
                print(f"[runner] unknown phase {phase!r}; exiting", file=sys.stderr)
                return 2

            if state.get("phase") in RESUMABLE_PAUSE_STATES:
                break

            if time.time() - epoch_start_wall > max_wall:
                print(f"[runner] wall-clock cap ({max_wall}s) exceeded; pausing", file=sys.stderr)
                _write_pause_state(cfg, state, "PAUSED_WALLCLOCK",
                                   resume_phase=state.get("phase", "GENERATE"))
                return 0
    except Exception as e:
        from llm_cli import QuotaExhaustedError  # noqa: E402
        if isinstance(e, QuotaExhaustedError):
            print(f"[runner] QUOTA EXHAUSTED ({e}); writing PAUSED_QUOTA and exiting", file=sys.stderr)
            _write_pause_state(cfg, state, "PAUSED_QUOTA",
                               resume_phase=state.get("phase", "GENERATE"))
            return 0
        tb = traceback.format_exc()
        print(f"[runner] UNEXPECTED ERROR in phase={state.get('phase')}; writing PAUSED_ERROR", file=sys.stderr)
        print(tb, file=sys.stderr)
        _write_pause_state(cfg, state, "PAUSED_ERROR",
                           resume_phase=state.get("phase", "GENERATE"),
                           error=f"{type(e).__name__}: {e}\n{tb}")
        return 0
    finally:
        signal.signal(signal.SIGTERM, prev_term)
        signal.signal(signal.SIGINT, prev_int)

    print(f"[runner] phase={state.get('phase')}; exiting 0", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
