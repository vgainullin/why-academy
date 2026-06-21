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


PHASES = ["GENERATE", "ANALYZE", "BUG_INVESTIGATE", "EXPERIMENT", "IMPLEMENT", "CLOSE", "DONE"]
RULE_RE = re.compile(r"^\*\*Affected rule\*\*:\s*`?([^\s`]+)`?", re.MULTILINE)
KIND_RE = re.compile(r"^\*\*Kind\*\*:\s*`?([A-Za-z_]+)`?", re.MULTILINE)
SEED_RE = re.compile(r"^\*\*Seed hypothesis\*\*:\s*`?([^\s`]+)`?", re.MULTILINE)
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


def kind_from_proposal(path: Path) -> str:
    m = KIND_RE.search(path.read_text())
    return m.group(1) if m else ""


def seed_id_from_proposal(path: Path) -> str | None:
    m = SEED_RE.search(path.read_text())
    return m.group(1) if m else None


def reproduction_from_proposal(path: Path) -> dict | None:
    """Parse the `## Reproduction case` block emitted by _write_bugfix_proposal.

    The block may contain a trailing "A negative (must-FAIL) regression case:"
    sub-block with its own from_srepr/to_srepr/args/expected lines. Those are
    parsed into a nested `negative` dict so they don't overwrite the main
    reproduction fields.
    """
    text = path.read_text()
    idx = text.find("## Reproduction case")
    if idx < 0:
        return None
    block = text[idx:]
    # Stop at the next section header after the reproduction block.
    next_hdr = block.find("\n## ", 1)
    if next_hdr >= 0:
        block = block[:next_hdr]

    fields: dict = {}
    negative: dict = {}
    in_negative = False
    for line in block.splitlines():
        stripped = line.strip()
        if "negative" in stripped.lower() and "regression" in stripped.lower():
            in_negative = True
            continue
        if not stripped.startswith("- "):
            continue
        body = stripped[2:]
        if ":" not in body:
            continue
        key, _, val = body.partition(":")
        key = key.strip()
        val = val.strip()
        target = negative if in_negative else fields
        if key == "args":
            try:
                target["args"] = json.loads(val)
            except Exception:
                target["args"] = {}
        elif key in ("from_srepr", "to_srepr"):
            target[key] = val
        elif key in ("expected", "actual"):
            target[key] = val

    if "from_srepr" in fields and "to_srepr" in fields:
        fields.setdefault("args", {})
        fields.setdefault("expected", "PASS")
        fields.setdefault("actual", "FAIL")
        if negative.get("from_srepr") and negative.get("to_srepr"):
            negative.setdefault("args", {})
            negative.setdefault("expected", "FAIL")
            fields["negative"] = negative
        return fields
    return None


def is_bugfix_proposal(path: Path) -> bool:
    return kind_from_proposal(path) == "BUGFIX"


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


def _epoch_log_count(epoch: int) -> int:
    """Count total jsonl records across all files for an epoch."""
    logs_dir = PROJECT_ROOT / "derivations" / "logs" / f"epoch_{epoch:03d}"
    if not logs_dir.exists():
        return 0
    total = 0
    for jsonl in logs_dir.glob("*.jsonl"):
        try:
            with jsonl.open() as f:
                total += sum(1 for line in f if line.strip())
        except Exception:
            continue
    return total


def _verify_epoch_logs(epoch: int, phase_name: str) -> bool:
    """Verify that jsonl logs exist and are non-empty for an epoch.

    Returns True if logs are present, False if missing/empty. Prints a clear
    warning so silent backfill failures don't leave downstream phases running
    on no data.
    """
    n = _epoch_log_count(epoch)
    if n == 0:
        print(f"[runner] {phase_name}: WARNING — 0 jsonl records for epoch_{epoch:03d}. "
              f"Backfill may have failed. ANALYZE and BUG_INVESTIGATE will have no data.",
              file=sys.stderr)
        return False
    print(f"[runner] {phase_name}: {n} jsonl records for epoch_{epoch:03d}", file=sys.stderr)
    return True


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
    # Verify that backfill produced jsonl data. If not, pause with an error
    # rather than advancing to ANALYZE with empty logs.
    if not _verify_epoch_logs(epoch_num(), "GENERATE"):
        state["resume_phase"] = "GENERATE"
        state["phase"] = "PAUSED_ERROR"
        state["error"] = (
            "backfill produced 0 jsonl records — the outer loop and bug "
            "investigator would have no data to analyze. Check that the batch "
            "workspace has checkpoint.json and target dirs with iter data."
        )
        state["paused_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save_state(cfg, state)
        return
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
        # Verify logs exist before running the outer loop. If backfill failed
        # silently, outer.sh would run against no data and produce no proposals.
        if not _verify_epoch_logs(epoch_num(), "ANALYZE"):
            print(f"[runner] ANALYZE: skipping outer loop (no jsonl data)", file=sys.stderr)
        else:
            print(f"[runner] ANALYZE: running outer loop on epoch_{epoch_num():03d}", file=sys.stderr)
            r = run([str(PROJECT_ROOT / "scripts" / "outer.sh"),
                     f"epoch_{epoch_num():03d}"])
            if r.returncode != 0:
                print(f"[runner] ANALYZE failed rc={r.returncode}", file=sys.stderr)
    state["phase"] = "BUG_INVESTIGATE"
    state["proposals_handled"] = state.get("proposals_handled", [])
    save_state(cfg, state)


# ── PHASE: BUG_INVESTIGATE ──────────────────────────────────────────────
def _validator_exists(rule: str) -> bool:
    return (PROJECT_ROOT / "derivations" / "validators" / f"{rule}.py").exists()


def _load_epoch_logs(epoch: int) -> list[dict]:
    """Load every jsonl record for the given epoch. Tolerant of bad lines."""
    logs_dir = PROJECT_ROOT / "derivations" / "logs" / f"epoch_{epoch:03d}"
    if not logs_dir.exists():
        return []
    out: list[dict] = []
    for jsonl in sorted(logs_dir.glob("*.jsonl")):
        with jsonl.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    return out


def _load_all_epoch_logs() -> list[dict]:
    """Load jsonl records from every epoch, not just the current one.

    Each record is annotated with ``_epoch`` (int) so callers can distinguish
    which epoch produced it. Records are returned in epoch order, then file
    order within each epoch.
    """
    logs_root = PROJECT_ROOT / "derivations" / "logs"
    if not logs_root.exists():
        return []
    out: list[dict] = []
    for epoch_dir in sorted(logs_root.glob("epoch_*")):
        m = re.match(r"epoch_(\d+)", epoch_dir.name)
        if not m:
            continue
        epoch = int(m.group(1))
        for jsonl in sorted(epoch_dir.glob("*.jsonl")):
            with jsonl.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        rec["_epoch"] = epoch
                        out.append(rec)
                    except Exception:
                        continue
    return out


def _match_seed_evidence(seed: dict, logs: list[dict]) -> list[dict]:
    """Find log evidence matching a seed hypothesis.

    A seed declares `evidence_signals` and `affected_rules`. Each signal is
    matched against the log records:

    - `VALIDATOR_REJECTED`: an edge whose rule is in `affected_rules`, whose
      status is FAIL/ERROR, and for which a validator file exists (i.e. the
      rule is covered, so the FAIL is a rejection rather than UNCOVERED).
    - any other signal (e.g. `one_rule_per_edge`): a judge-level rejection.
      Matched when the attempt has a `judge_eval` whose text/verdicts mention
      the signal substring AND at least one edge uses an affected rule.

    Returns one evidence entry per (epoch, record, signal, rule) match.
    """
    signals = seed.get("evidence_signals") or []
    rules = set(seed.get("affected_rules") or [])
    matches: list[dict] = []
    for idx, rec in enumerate(logs):
        epoch = rec.get("_epoch")
        edges = rec.get("edge_results") or []
        rec_rules = {e.get("rule") for e in edges if e.get("rule")}
        for sig in signals:
            if sig == "VALIDATOR_REJECTED":
                for e in edges:
                    rule = e.get("rule")
                    if rule in rules and e.get("status") in ("FAIL", "ERROR") \
                            and _validator_exists(rule):
                        matches.append({
                            "record_index": idx,
                            "epoch": epoch,
                            "signal": sig,
                            "rule": rule,
                            "detail": e.get("reason", ""),
                            "target": rec.get("target", ""),
                            "batch_id": rec.get("batch_id", ""),
                        })
            else:
                judge = rec.get("judge_eval")
                if not judge:
                    continue
                blob = json.dumps(judge).lower()
                if sig.lower() not in blob:
                    continue
                hit_rules = sorted(rec_rules & rules)
                if not hit_rules:
                    continue
                matches.append({
                    "record_index": idx,
                    "epoch": epoch,
                    "signal": sig,
                    "rule": hit_rules[0],
                    "detail": sig,
                    "target": rec.get("target", ""),
                    "batch_id": rec.get("batch_id", ""),
                })
    # Dedup by (epoch, record_index, signal, rule).
    seen = set()
    deduped: list[dict] = []
    for m in matches:
        key = (m.get("epoch"), m["record_index"], m["signal"], m["rule"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(m)
    return deduped


def _sanitized_seed_id(sid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", sid)


def _write_bugfix_proposal(epoch_dir: Path, seed: dict, matches: list[dict],
                           kind: str) -> Path:
    """Write a proposal_*.md for a confirmed seed hypothesis."""
    sid = seed["id"]
    fname = f"proposal_bug_{_sanitized_seed_id(sid)}.md"
    path = epoch_dir / fname
    rules = seed.get("affected_rules") or []
    repro = seed.get("reproduction")
    lines: list[str] = []
    lines.append(f"# Bugfix Proposal: {sid}")
    lines.append("")
    lines.append(f"**Kind**: {kind}")
    lines.append(f"**Affected rule**: {rules[0] if rules else 'none'}")
    lines.append(f"**Seed hypothesis**: {sid}")
    lines.append(f"**Evidence count**: {len(matches)}")
    lines.append("")
    lines.append("## Hypothesis")
    lines.append("")
    lines.append(seed.get("hypothesis", ""))
    lines.append("")
    lines.append("## Evidence (from epoch logs)")
    lines.append("")
    for m in matches[:10]:
        lines.append(
            f"- record={m['record_index']} signal={m['signal']} rule={m['rule']} "
            f"target={m.get('target', '')!r} batch={m.get('batch_id', '')!r}"
        )
    if len(matches) > 10:
        lines.append(f"- ... and {len(matches) - 10} more")
    lines.append("")
    if repro:
        lines.append("## Reproduction case")
        lines.append("")
        lines.append(f"- from_srepr: {repro.get('from_srepr', '')}")
        lines.append(f"- to_srepr: {repro.get('to_srepr', '')}")
        lines.append(f"- args: {json.dumps(repro.get('args', {}))}")
        lines.append(f"- expected: {repro.get('expected', 'PASS')}")
        lines.append(f"- actual: {repro.get('actual', 'FAIL')}")
        if repro.get("negative"):
            neg = repro["negative"]
            lines.append("")
            lines.append("A negative (must-FAIL) regression case:")
            lines.append(f"- from_srepr: {neg.get('from_srepr', '')}")
            lines.append(f"- to_srepr: {neg.get('to_srepr', '')}")
            lines.append(f"- args: {json.dumps(neg.get('args', {}))}")
            lines.append("- expected: FAIL")
        lines.append("")
        lines.append("## Proposed change")
        lines.append("")
        lines.append(repro.get("proposed_change", ""))
        lines.append("")
        lines.append("## Test cases required")
        lines.append("")
        lines.append("The reproduction case above must now PASS after the fix.")
        lines.append("")
    else:
        lines.append("## Proposed change")
        lines.append("")
        lines.append(
            "No reproduction case is available for this seed. This is an "
            "INVESTIGATE proposal: document the pattern for human follow-up; "
            "do not implement a validator change without a confirmed reproduction."
        )
        lines.append("")
    path.write_text("\n".join(lines))
    return path


def write_regression_tests(rule: str, reproduction: dict, seed_id: str,
                           corpus_root: Path | None = None) -> dict:
    """Auto-generate regression corpus entries from a confirmed reproduction.

    Writes the reproduction case into `test_corpus/<rule>/positive.json` (the
    case that must now PASS). If the seed supplies an explicit `negative`
    block, appends it to `negative.json`. Existing entries are preserved and
    de-duplicated by `description`.

    Returns a summary of what was written. This is the auto regression test
    step from the bug-investigate design: the reproduction case becomes a
    permanent part of the test suite so the fix cannot silently regress.
    """
    if corpus_root is None:
        corpus_root = PROJECT_ROOT / "derivations" / "test_corpus"
    rule_dir = corpus_root / rule
    rule_dir.mkdir(parents=True, exist_ok=True)

    pos_path = rule_dir / "positive.json"
    pos: list[dict] = []
    if pos_path.exists():
        try:
            pos = json.loads(pos_path.read_text())
        except Exception:
            pos = []
    pos_desc = f"[bugfix:{seed_id}] reproduction case (must PASS)"
    if not any(e.get("description") == pos_desc for e in pos):
        pos.append({
            "description": pos_desc,
            "from_srepr": reproduction.get("from_srepr", ""),
            "to_srepr": reproduction.get("to_srepr", ""),
            "args": reproduction.get("args", {}),
            "expected": "PASS",
        })
        pos_path.write_text(json.dumps(pos, indent=2))

    neg_written = 0
    neg = reproduction.get("negative")
    if neg:
        neg_path = rule_dir / "negative.json"
        neg_list: list[dict] = []
        if neg_path.exists():
            try:
                neg_list = json.loads(neg_path.read_text())
            except Exception:
                neg_list = []
        neg_desc = f"[bugfix:{seed_id}] negative regression case (must FAIL)"
        if not any(e.get("description") == neg_desc for e in neg_list):
            neg_list.append({
                "description": neg_desc,
                "from_srepr": neg.get("from_srepr", ""),
                "to_srepr": neg.get("to_srepr", ""),
                "args": neg.get("args", {}),
                "expected": "FAIL",
            })
            neg_path.write_text(json.dumps(neg_list, indent=2))
            neg_written = 1

    return {
        "rule": rule,
        "positive_path": str(pos_path),
        "negative_path": str(rule_dir / "negative.json") if neg else None,
        "positive_written": 1,
        "negative_written": neg_written,
        "seed_id": seed_id,
    }


def phase_bug_investigate(cfg: dict, state: dict) -> None:
    """Investigate seed hypotheses against the current epoch's logs.

    For each seed with enough matching evidence (>= min_occurrences), write a
    proposal. Seeds that carry a reproduction case produce `Kind: BUGFIX`
    proposals (which bypass the 100-attempt evidence floor in IMPLEMENT);
    seeds without a reproduction case produce `Kind: INVESTIGATE` proposals
    for human follow-up. Resumable via `bug_seeds_processed`.
    """
    bi_cfg = cfg.get("runner", {}).get("bug_investigate", {})
    if not bi_cfg.get("enabled", False):
        print("[runner] BUG_INVESTIGATE: disabled in config; skipping to EXPERIMENT", file=sys.stderr)
        state["phase"] = "EXPERIMENT"
        save_state(cfg, state)
        return

    epoch = epoch_num()
    epoch_dir = PROJECT_ROOT / "derivations" / "reports" / f"epoch_{epoch:03d}"
    epoch_dir.mkdir(parents=True, exist_ok=True)

    processed = set(state.get("bug_seeds_processed", []))
    # Track the evidence count seen so far for each seed so we can detect
    # when newly accumulated cross-epoch evidence pushes it over the threshold.
    prior_evidence = state.get("bug_seed_evidence", {})
    seeds = bi_cfg.get("seeds", []) or []
    default_min_occ = int(bi_cfg.get("min_occurrences", 2))
    max_proposals = int(bi_cfg.get("max_proposals_per_epoch", 3))

    logs = _load_all_epoch_logs()
    current_epoch = epoch_num()
    current_records = sum(1 for r in logs if r.get("_epoch") == current_epoch)
    print(f"[runner] BUG_INVESTIGATE: epoch={epoch:03d} seeds={len(seeds)} "
          f"total_log_records={len(logs)} (current_epoch={current_records})",
          file=sys.stderr)
    if not logs:
        print(f"[runner] BUG_INVESTIGATE: WARNING — no jsonl logs found across any epoch; "
              f"no seeds can be matched. Check that backfill ran successfully.",
              file=sys.stderr)

    written = 0
    new_evidence: dict[str, int] = {}
    for seed in seeds:
        sid = seed.get("id")
        if not sid:
            continue
        # Seeds that already produced a proposal are marked processed and skipped.
        # A seed that was below threshold last epoch is NOT in processed — it
        # gets re-evaluated against all accumulated logs.
        if sid in processed:
            new_evidence[sid] = prior_evidence.get(sid, 0)
            continue
        if written >= max_proposals:
            print(f"[runner] BUG_INVESTIGATE: hit max_proposals_per_epoch={max_proposals}; stopping",
                  file=sys.stderr)
            break
        min_occ = int(seed.get("min_occurrences", default_min_occ))
        matches = _match_seed_evidence(seed, logs)
        total_evidence = len(matches)
        new_evidence[sid] = total_evidence
        if total_evidence < min_occ:
            print(f"[runner] BUG_INVESTIGATE: seed={sid} evidence={total_evidence} < {min_occ} "
                  f"(accumulated across all epochs); skipping",
                  file=sys.stderr)
            continue
        repro = seed.get("reproduction")
        kind = "BUGFIX" if repro else "INVESTIGATE"
        path = _write_bugfix_proposal(epoch_dir, seed, matches, kind)
        written += 1
        processed.add(sid)
        print(f"[runner] BUG_INVESTIGATE: seed={sid} kind={kind} evidence={total_evidence} "
              f"(cross-epoch) -> {path.name}",
              file=sys.stderr)

    state["bug_seeds_processed"] = sorted(processed)
    state["bug_seed_evidence"] = new_evidence
    state["phase"] = "EXPERIMENT"
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
    all_proposals = sorted(p for p in epoch_dir.glob("proposal_*.md") if "_closure" not in p.name)
    # BUGFIX proposals bypass the evidence floor; prioritize them ahead of
    # ordinary validator/prompt proposals so they aren't squeezed out by the
    # per-epoch cap.
    all_proposals.sort(key=lambda p: (0 if is_bugfix_proposal(p) else 1, p.name))
    proposals = all_proposals[:max_proposals]
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

        if kind not in ("NEW_VALIDATOR", "STRENGTHEN_VALIDATOR", "WEAKEN_VALIDATOR", "BUGFIX"):
            print(f"  -> skip kind={kind!r} (not a validator, prompt, or bugfix change)", file=sys.stderr)
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
            # BUGFIX promotion: auto-generate regression corpus entries from
            # the reproduction case so the fix cannot silently regress.
            if kind == "BUGFIX":
                repro = reproduction_from_proposal(prop)
                seed_id = seed_id_from_proposal(prop) or "unknown"
                if repro:
                    try:
                        summary = write_regression_tests(rule, repro, seed_id)
                        print(f"  -> REGRESSION TESTS: "
                              f"positive={summary['positive_written']} "
                              f"negative={summary['negative_written']} "
                              f"-> {summary['positive_path']}", file=sys.stderr)
                    except Exception as e:
                        print(f"  -> WARN: regression test generation failed: {e}", file=sys.stderr)
                else:
                    print(f"  -> WARN: BUGFIX proposal has no parseable reproduction case; "
                          f"no auto regression tests written", file=sys.stderr)
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
            elif phase == "BUG_INVESTIGATE":
                phase_bug_investigate(cfg, state)
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
