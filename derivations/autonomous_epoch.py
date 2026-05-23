#!/usr/bin/env python3
"""Autonomous epoch runner.

State machine that drives one full epoch end-to-end:
  GENERATE  -> batch generation across the cohort
  ANALYZE   -> outer loop drafts proposals
  IMPLEMENT -> for each proposal, implement+closure_test+auto-promote-or-revert
  CLOSE     -> holdout regression + bump epoch in state.json

All thresholds, gates, and limits are config-driven (configs/v<N>.json runner section).

Resumable: re-running picks up at the current phase. Disk artifacts are the
truth; _epoch_state.json is a hint. Catches QuotaExhaustedError, writes
PAUSED_QUOTA state, and exits 0 (so a wrapper cron can re-launch later).
"""
from __future__ import annotations
import argparse
import datetime
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
from config import load_config  # noqa: E402


PHASES = ["GENERATE", "ANALYZE", "IMPLEMENT", "CLOSE", "DONE"]
RULE_RE = re.compile(r"^\*\*Affected rule\*\*:\s*`?([^\s`]+)`?", re.MULTILINE)


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


def epoch_num() -> int:
    return int(json.loads((PROJECT_ROOT / "derivations" / "state.json").read_text())["epoch"])


def validator_version() -> str:
    return json.loads((PROJECT_ROOT / "derivations" / "state.json").read_text())["validator_version"]


def bump_state_field(field: str, new_val) -> None:
    p = PROJECT_ROOT / "derivations" / "state.json"
    d = json.loads(p.read_text())
    d[field] = new_val
    p.write_text(json.dumps(d, indent=2))


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
    if r.returncode != 0:
        # Partial completion is OK; batch is resumable.
        print(f"[runner] GENERATE returned {r.returncode} (likely some targets failed; that's OK)", file=sys.stderr)
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
        print(f"[runner] ANALYZE: running outer loop on epoch_{epoch_num():03d}", file=sys.stderr)
        r = run([str(PROJECT_ROOT / "scripts" / "outer.sh"),
                 f"epoch_{epoch_num():03d}"])
        if r.returncode != 0:
            print(f"[runner] ANALYZE failed rc={r.returncode}", file=sys.stderr)
    state["phase"] = "IMPLEMENT"
    state["proposals_handled"] = state.get("proposals_handled", [])
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

        # Skip non-validator proposals (INVESTIGATE etc.)
        kind = ""
        for line in prop.read_text().splitlines():
            if line.startswith("**Kind**:"):
                kind = line.split(":", 1)[1].strip()
                break
        if kind not in ("NEW_VALIDATOR", "STRENGTHEN_VALIDATOR", "WEAKEN_VALIDATOR"):
            print(f"  -> skip kind={kind!r} (not a validator change)", file=sys.stderr)
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

        # 1. Implement
        r = run([str(PROJECT_ROOT / "scripts" / "implement.sh"), str(prop)])
        if r.returncode == 75:
            restore_validator_snapshot(pre_validator_snapshot)
            bump_state_field("validator_version", pre_validator_v)
            state["resume_phase"] = "IMPLEMENT"
            state["phase"] = "PAUSED_QUOTA"
            state["paused_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            save_state(cfg, state)
            return
        if r.returncode != 0:
            print(f"  -> implement.sh failed rc={r.returncode}; marking handled", file=sys.stderr)
            restore_validator_snapshot(pre_validator_snapshot)
            bump_state_field("validator_version", pre_validator_v)
            handled.add(prop.name)
            state["proposals_handled"] = sorted(handled)
            save_state(cfg, state)
            if stop_on_fail:
                break
            continue

        # 2. Closure test
        r = run([str(PROJECT_ROOT / "scripts" / "closure_test.sh"), str(prop)])
        if r.returncode == 75:
            restore_validator_snapshot(pre_validator_snapshot)
            bump_state_field("validator_version", pre_validator_v)
            state["resume_phase"] = "IMPLEMENT"
            state["phase"] = "PAUSED_QUOTA"
            state["paused_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            save_state(cfg, state)
            return
        closure_sidecar = prop.with_name(prop.stem + "_closure.json")
        if not closure_sidecar.exists():
            print(f"  -> closure_test produced no sidecar; treating as FAILED", file=sys.stderr)
            restore_validator_snapshot(pre_validator_snapshot)
            bump_state_field("validator_version", pre_validator_v)
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
            # validator_version was already bumped by implement.sh; nothing more to do
        else:
            print(f"  -> REVERTED  lift={lift:.2%}  regressed={regressed}", file=sys.stderr)
            # Revert validator code to its exact pre-implementation state.
            restore_validator_snapshot(pre_validator_snapshot)
            bump_state_field("validator_version", pre_validator_v)
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

    if state.get("phase") == "PAUSED_QUOTA":
        print(f"[runner] PAUSED_QUOTA from previous run; clearing pause and resuming at "
              f"phase={state.get('resume_phase', 'GENERATE')}", file=sys.stderr)
        state["phase"] = state.get("resume_phase", "GENERATE")
        save_state(cfg, state)

    epoch_start_wall = time.time()
    max_wall = float(cfg.get("runner", {}).get("epoch", {}).get("max_wall_clock_s_per_epoch", 7200))

    try:
        while state.get("phase") not in ("DONE", "PAUSED_QUOTA"):
            phase = state["phase"]
            if phase == "GENERATE":
                phase_generate(cfg, state, Path(args.queue))
            elif phase == "ANALYZE":
                phase_analyze(cfg, state)
            elif phase == "IMPLEMENT":
                phase_implement(cfg, state)
            elif phase == "CLOSE":
                phase_close(cfg, state)
            else:
                print(f"[runner] unknown phase {phase!r}; exiting", file=sys.stderr)
                return 2

            if time.time() - epoch_start_wall > max_wall:
                print(f"[runner] wall-clock cap ({max_wall}s) exceeded; pausing", file=sys.stderr)
                state["resume_phase"] = state["phase"]
                state["phase"] = "PAUSED_WALLCLOCK"
                save_state(cfg, state)
                return 0
    except Exception as e:
        # Quota detection: import inside the try/except to avoid a circular cost
        from claude_worker import QuotaExhaustedError as ClaudeQuotaExhaustedError  # noqa: E402
        from llm_cli import QuotaExhaustedError as LLMQuotaExhaustedError  # noqa: E402
        if isinstance(e, (ClaudeQuotaExhaustedError, LLMQuotaExhaustedError)):
            print(f"[runner] QUOTA EXHAUSTED ({e}); writing PAUSED_QUOTA and exiting", file=sys.stderr)
            state["resume_phase"] = state.get("phase", "GENERATE")
            state["phase"] = "PAUSED_QUOTA"
            state["paused_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            save_state(cfg, state)
            return 0
        raise

    print(f"[runner] phase={state.get('phase')}; exiting 0", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
