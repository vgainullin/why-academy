#!/usr/bin/env python3
"""Closure test: did implementing a proposal lift pass rates on the targets that previously failed?

Reads a proposal file, extracts the affected rule from its frontmatter, scans
all jsonl logs for targets where THAT rule's edges previously FAILed, builds
a focused mini-batch queue, runs it under the current pipeline, and computes:

  lift_fraction = resolved prior failed edges / prior failed edges

The post-change surface is exactly one generated attempt per target: the
accepted iteration if one exists, otherwise the final attempted iteration.

A lift_fraction >= runner.auto_promote.min_lift_fraction (with zero holdout
regression if required) is the promote signal.

Outputs:
  <reports_dir>/proposal_NN_closure.json   { rule, candidates, queue, pre_metrics, post_metrics, lift_fraction, holdout_regressed }
"""
from __future__ import annotations
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
from config import load_config  # noqa: E402
from autonomous_epoch import (  # noqa: E402
    is_system_bug_rule,
    judge_fixture_from_proposal,
    kind_from_proposal,
    reproduction_from_proposal,
    seed_id_from_proposal,
    target_check_fixture_from_proposal,
)


RULE_RE = re.compile(r"^\*\*Affected rule\*\*:\s*`?([^\s`]+)`?", re.MULTILINE)


def rule_from_proposal(path: Path) -> str | None:
    text = path.read_text()
    m = RULE_RE.search(text)
    return m.group(1) if m else None


def _holdout_regression() -> str | None:
    """Return the name of the first regressing legacy holdout problem, or None.

    Legacy verifier-format holdout is the only set verify.py parses without
    modification. Shared by the standard lift-based closure path and the
    BUGFIX reproduction path.
    """
    legacy_dir = PROJECT_ROOT / "derivations" / "test_corpus" / "holdout" / "problems_legacy_verifier"
    if not legacy_dir.exists():
        return None
    for p in legacy_dir.glob("*.json"):
        if p.name.endswith((".verifier.json", ".canvas_check.json")):
            continue
        r = subprocess.run(
            [os.environ.get("DERIVATION_PYTHON") or sys.executable, str(ROOT / "verify.py"), str(p)],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        )
        if r.returncode != 0:
            return p.name
    return None


def _run_reproduction(rule: str, repro: dict) -> tuple[str, str]:
    """Run the current validator for `rule` on a reproduction case.

    Uses verify.verify_edge so the same validator-loading path as the inner
    loop is exercised. Imported lazily so this module stays importable in
    environments without sympy (e.g. unit tests that mock this helper).
    """
    from verify import verify_edge  # noqa: E402
    from sympy_eval import parse_srepr  # noqa: E402
    from_expr = parse_srepr(repro["from_srepr"])
    to_expr = parse_srepr(repro["to_srepr"])
    return verify_edge(from_expr, to_expr, rule, repro.get("args") or {})


def _judge_criterion_statuses(record: dict) -> list[str]:
    verdicts = record.get("verdicts") or {}
    if not isinstance(verdicts, dict):
        return []
    statuses: list[str] = []
    for payload in verdicts.values():
        raw = payload.get("verdict") if isinstance(payload, dict) else payload
        if isinstance(raw, str) and raw.strip():
            statuses.append(raw.strip().upper())
    return statuses


def _judge_aggregation_mismatch(record: dict) -> str | None:
    overall = str(record.get("overall") or "").strip().upper()
    statuses = _judge_criterion_statuses(record)
    if not overall or not statuses:
        return None
    if overall == "PASS" and any(s in ("FAIL", "ERROR") for s in statuses):
        return "overall_pass_with_failed_criterion"
    if overall in ("FAIL", "ERROR") and all(s in ("PASS", "SKIP") for s in statuses):
        return "overall_nonpass_with_no_failed_criteria"
    return None


def _judge_fixture_record(fixture: dict) -> dict:
    judge_eval = fixture.get("judge_eval") if isinstance(fixture, dict) else None
    if not isinstance(judge_eval, dict):
        raise ValueError("judge fixture must contain a judge_eval object")
    # Isolate closure replay from in-place mutations by judge helpers.
    return json.loads(json.dumps(judge_eval))


def _run_judge_fixture(fixture: dict) -> tuple[str, str, dict | None]:
    """Replay a judge/system BUGFIX fixture against the current judge normalizer."""
    try:
        before = _judge_fixture_record(fixture)
    except Exception as e:
        return "ERROR", f"invalid judge fixture: {e}", None
    mismatch = _judge_aggregation_mismatch(before)
    if not mismatch:
        return "FAIL", "fixture is not a judge aggregation mismatch", before
    try:
        import judge  # noqa: E402
        normalizer = getattr(judge, "normalize_primary_record", None)
    except Exception as e:
        return "ERROR", f"could not import judge normalizer: {e}", before
    if not callable(normalizer):
        return "FAIL", "judge.normalize_primary_record is missing", before
    try:
        after = normalizer(before)
    except Exception as e:
        return "ERROR", f"judge normalizer raised: {e}", before
    if not isinstance(after, dict):
        return "ERROR", "judge normalizer returned non-object", before

    expected_overall = fixture.get("expected_overall")
    if expected_overall is None and isinstance(fixture.get("expected"), dict):
        expected_overall = fixture["expected"].get("overall")
    if expected_overall:
        actual = str(after.get("overall") or "").upper()
        if actual != str(expected_overall).upper():
            return "FAIL", f"expected overall {expected_overall}, got {actual}", after
        return "PASS", "judge fixture matched expected overall", after

    after_mismatch = _judge_aggregation_mismatch(after)
    rejected = str(after.get("overall") or "").upper() == "ERROR" and bool(
        after.get("consistency_error") or after.get("_consistency_error")
    )
    if after_mismatch and not rejected:
        return "FAIL", f"judge aggregation mismatch still present: {after_mismatch}", after
    return "PASS", "judge aggregation mismatch resolved", after


def _run_target_check_fixture(fixture: dict) -> tuple[str, str, dict | None]:
    """Replay a target-check BUGFIX fixture against the current target checker."""
    target = fixture.get("target") if isinstance(fixture, dict) else None
    problem = fixture.get("problem") if isinstance(fixture, dict) else None
    if not isinstance(target, str) or not target.strip() or not isinstance(problem, dict):
        return "ERROR", "invalid target_check fixture", None
    try:
        import target_check  # noqa: E402
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "problem.json"
            path.write_text(json.dumps(problem))
            _rc, payload = target_check.check(path, target)
    except Exception as e:
        return "ERROR", f"target_check replay raised: {type(e).__name__}: {e}", None
    status = str(payload.get("status") or "ERROR")
    reason = str(payload.get("reason") or "")
    return status, reason, payload


def _run_target_check_bugfix_closure(cfg: dict, cfg_version: str, runner: dict,
                                     proposal_path: Path, rule: str, fixture: dict) -> int:
    expected = fixture.get("expected") if isinstance(fixture.get("expected"), dict) else {}
    expected_status = str(expected.get("status") or "PASS")
    status, reason, payload = _run_target_check_fixture(fixture)
    passes = status == expected_status
    lift_fraction = 1.0 if passes else 0.0
    holdout_regressed = _holdout_regression()
    seed_id = seed_id_from_proposal(proposal_path)

    record = {
        "rule": rule,
        "kind": "BUGFIX",
        "proposal_path": str(proposal_path),
        "seed_hypothesis": seed_id,
        "target_check_fixture": fixture,
        "expected_status": expected_status,
        "actual_status": status,
        "target_check_reason": reason,
        "target_check_payload": payload,
        "lift_fraction": lift_fraction,
        "holdout_regressed": holdout_regressed,
        "scoring_surface": "target_check fixture",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "config_version": cfg_version,
        "min_lift_threshold": runner.get("auto_promote", {}).get("min_lift_fraction", 0.4),
    }
    out_path = proposal_path.with_name(proposal_path.stem + "_closure.json")
    out_path.write_text(json.dumps(record, indent=2))

    print()
    print(f"[closure] BUGFIX target_check fixture rule={rule} seed={seed_id}")
    print(f"[closure] actual={status} reason={reason}")
    print(f"[closure] lift fraction: {lift_fraction:.2%}")
    print(f"[closure] holdout regression: {holdout_regressed or 'none'}")
    verdict = "REPRO_CONFIRMED" if passes and not holdout_regressed else "REPRO_FAILED"
    print(f"[closure] verdict: {verdict}")
    print(f"[closure] sidecar: {out_path}")
    return 0 if (passes and not holdout_regressed) else 1


def _run_judge_bugfix_closure(cfg: dict, cfg_version: str, runner: dict,
                              proposal_path: Path, rule: str, fixture: dict) -> int:
    seed_id = seed_id_from_proposal(proposal_path)
    status, reason, normalized = _run_judge_fixture(fixture)
    passes = status == "PASS"
    lift_fraction = 1.0 if passes else 0.0
    holdout_regressed = _holdout_regression()

    record = {
        "rule": rule,
        "kind": "BUGFIX",
        "proposal_path": str(proposal_path),
        "seed_hypothesis": seed_id,
        "judge_fixture": fixture,
        "actual_status": status,
        "judge_reason": reason,
        "normalized_judge_eval": normalized,
        "lift_fraction": lift_fraction,
        "holdout_regressed": holdout_regressed,
        "scoring_surface": "judge aggregation fixture",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "config_version": cfg_version,
        "min_lift_threshold": runner.get("auto_promote", {}).get("min_lift_fraction", 0.4),
    }
    out_path = proposal_path.with_name(proposal_path.stem + "_closure.json")
    out_path.write_text(json.dumps(record, indent=2))

    print()
    print(f"[closure] BUGFIX judge fixture rule={rule} seed={seed_id}")
    print(f"[closure] actual={status} reason={reason}")
    print(f"[closure] lift fraction: {lift_fraction:.2%}")
    print(f"[closure] holdout regression: {holdout_regressed or 'none'}")
    verdict = "REPRO_CONFIRMED" if passes and not holdout_regressed else "REPRO_FAILED"
    print(f"[closure] verdict: {verdict}")
    print(f"[closure] sidecar: {out_path}")
    return 0 if (passes and not holdout_regressed) else 1


def _run_bugfix_closure(cfg: dict, cfg_version: str, runner: dict,
                        proposal_path: Path, rule: str) -> int:
    """Closure path for BUGFIX proposals: verify the reproduction case now passes.

    BUGFIX proposals bypass the 100-attempt evidence floor; their closure
    signal is a single, concrete reproduction case. lift_fraction is 1.0 when
    the validator now returns the expected status on that case, else 0.0.
    Holdout regression is still enforced.
    """
    if is_system_bug_rule(rule):
        fixture = target_check_fixture_from_proposal(proposal_path)
        if fixture:
            return _run_target_check_bugfix_closure(cfg, cfg_version, runner, proposal_path, rule, fixture)
        fixture = judge_fixture_from_proposal(proposal_path)
        if fixture:
            return _run_judge_bugfix_closure(cfg, cfg_version, runner, proposal_path, rule, fixture)

    repro = reproduction_from_proposal(proposal_path)
    seed_id = seed_id_from_proposal(proposal_path)
    if not repro:
        print(f"[closure] BUGFIX: no parseable reproduction case in {proposal_path.name}",
              file=sys.stderr)
        record = {
            "rule": rule,
            "kind": "BUGFIX",
            "proposal_path": str(proposal_path),
            "seed_hypothesis": seed_id,
            "lift_fraction": 0.0,
            "holdout_regressed": None,
            "error": "no reproduction case",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "config_version": cfg_version,
            "min_lift_threshold": runner.get("auto_promote", {}).get("min_lift_fraction", 0.4),
        }
        out_path = proposal_path.with_name(proposal_path.stem + "_closure.json")
        out_path.write_text(json.dumps(record, indent=2))
        return 1

    expected = repro.get("expected", "PASS")
    try:
        status, reason = _run_reproduction(rule, repro)
    except Exception as e:
        print(f"[closure] BUGFIX: validator raised on reproduction case: {e}", file=sys.stderr)
        status, reason = "ERROR", f"validator raised: {e}"

    passes = (status == expected)
    lift_fraction = 1.0 if passes else 0.0
    holdout_regressed = _holdout_regression()

    record = {
        "rule": rule,
        "kind": "BUGFIX",
        "proposal_path": str(proposal_path),
        "seed_hypothesis": seed_id,
        "reproduction": repro,
        "expected_status": expected,
        "actual_status": status,
        "validator_reason": reason,
        "lift_fraction": lift_fraction,
        "holdout_regressed": holdout_regressed,
        "scoring_surface": "reproduction case",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "config_version": cfg_version,
        "min_lift_threshold": runner.get("auto_promote", {}).get("min_lift_fraction", 0.4),
    }
    out_path = proposal_path.with_name(proposal_path.stem + "_closure.json")
    out_path.write_text(json.dumps(record, indent=2))

    print()
    print(f"[closure] BUGFIX rule={rule} seed={seed_id}")
    print(f"[closure] reproduction: {repro.get('from_srepr')} -> {repro.get('to_srepr')}")
    print(f"[closure] expected={expected} actual={status} reason={reason}")
    print(f"[closure] lift fraction: {lift_fraction:.2%}")
    print(f"[closure] holdout regression: {holdout_regressed or 'none'}")
    verdict = "REPRO_CONFIRMED" if passes and not holdout_regressed else "REPRO_FAILED"
    print(f"[closure] verdict: {verdict}")
    print(f"[closure] sidecar: {out_path}")
    return 0 if (passes and not holdout_regressed) else 1


def previously_failing_targets(rule: str, epoch: int) -> list[dict]:
    """Walk jsonl logs for the given epoch and find target attempts where
    `rule` had at least one FAIL edge."""
    logs_dir = PROJECT_ROOT / "derivations" / "logs" / f"epoch_{epoch:03d}"
    seen_targets: dict = {}  # target_text -> {n_fail_edges, batch_ids}
    if not logs_dir.exists():
        return []
    for jsonl in sorted(logs_dir.glob("*.jsonl")):
        with jsonl.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                fails = [e for e in rec.get("edge_results", [])
                         if e.get("rule") == rule and e.get("status") in ("FAIL", "ERROR")]
                if not fails:
                    continue
                tgt = rec.get("target")
                if not tgt:
                    continue
                entry = seen_targets.setdefault(tgt, {"target": tgt, "n_fail_edges": 0, "batches": set()})
                entry["n_fail_edges"] += len(fails)
                entry["batches"].add(rec.get("batch_id", "unknown"))
    out = []
    for v in seen_targets.values():
        v["batches"] = sorted(v["batches"])
        out.append(v)
    return sorted(out, key=lambda v: -v["n_fail_edges"])


def final_scored_iter_dir(target_dir: Path) -> Path | None:
    """Return the one attempt that should represent this target post-change."""
    metrics_path = target_dir / "target_metrics.json"
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text())
        accepted_at = metrics.get("accepted_at_iter")
        if metrics.get("accepted") and isinstance(accepted_at, int):
            accepted_dir = target_dir / f"iter_{accepted_at:02d}"
            if accepted_dir.exists():
                return accepted_dir
        statuses = metrics.get("iter_statuses") or []
        if statuses:
            last_name = statuses[-1][0]
            last_dir = target_dir / last_name
            if last_dir.exists():
                return last_dir
    iters = sorted(target_dir.glob("iter_*"))
    return iters[-1] if iters else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("proposal", help="path to derivations/reports/epoch_NNN/proposal_NN_*.md")
    ap.add_argument("--epoch", type=int, default=None,
                    help="epoch to scan for previously-failing targets (default: current epoch from state.json)")
    ap.add_argument("--batch-id", default=None,
                    help="override the closure batch id (default: timestamped)")
    args = ap.parse_args()

    cfg, cfg_version = load_config()
    runner = cfg.get("runner", {})
    closure_cfg = runner.get("closure_test", {})
    max_targets = int(closure_cfg.get("max_targets_per_proposal", 8))
    min_targets = int(closure_cfg.get("min_targets_required", 3))
    parallel = int(closure_cfg.get("parallel", 3))

    proposal_path = Path(args.proposal)
    if not proposal_path.exists():
        print(f"[closure] FAIL: proposal not found at {proposal_path}", file=sys.stderr)
        return 2
    rule = rule_from_proposal(proposal_path)
    if not rule:
        print(f"[closure] FAIL: could not extract Affected rule from {proposal_path.name}", file=sys.stderr)
        return 2

    # BUGFIX proposals close on a single reproduction case, not a lift batch.
    if kind_from_proposal(proposal_path) == "BUGFIX":
        return _run_bugfix_closure(cfg, cfg_version, runner, proposal_path, rule)

    state = json.loads((PROJECT_ROOT / "derivations" / "state.json").read_text())
    epoch = args.epoch if args.epoch is not None else int(state["epoch"])

    candidates = previously_failing_targets(rule, epoch)
    if len(candidates) < min_targets:
        print(f"[closure] SKIP: only found {len(candidates)} prev-failing targets for rule '{rule}' "
              f"(need >= {min_targets}). Not enough to test.", file=sys.stderr)
        return 3

    queue_targets = [c["target"] for c in candidates[:max_targets]]
    pre_fail_total = sum(c["n_fail_edges"] for c in candidates[:max_targets])

    batch_id = args.batch_id or f"closure_{rule}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Stage a temp queue file
    queue_path = PROJECT_ROOT / "derivations" / "targets" / f".closure_{batch_id}.txt"
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(f"# Closure test for rule '{rule}'\n"
                          f"# Generated {datetime.datetime.now().isoformat()}\n\n"
                          + "\n".join(queue_targets) + "\n")

    print(f"[closure] rule={rule}", file=sys.stderr)
    print(f"[closure] prev-failing targets: {len(candidates)}; testing {len(queue_targets)}", file=sys.stderr)
    print(f"[closure] batch_id={batch_id}", file=sys.stderr)

    # Run the focused batch via batch.sh
    env = {**__import__("os").environ, "BATCH_PARALLEL": str(parallel)}
    proc = subprocess.run(
        [str(PROJECT_ROOT / "scripts" / "batch.sh"),
         "--batch-id", batch_id, str(queue_path)],
        cwd=str(PROJECT_ROOT), env=env,
    )
    if proc.returncode == 75:
        print("[closure] quota exhausted during closure batch", file=sys.stderr)
        queue_path.unlink(missing_ok=True)
        return 75

    # Post-metrics: score exactly one attempt per target against the original
    # failed-edge denominator. This prevents retries or extra generated rule
    # edges from inflating closure lift.
    batch_dir = PROJECT_ROOT / "derivations" / "_evolutions" / "batches" / batch_id
    pre_fail_by_target = {c["target"]: int(c["n_fail_edges"]) for c in candidates[:max_targets]}
    post_pass = 0
    post_fail = 0
    post_other = 0
    resolved_pre_fail_edges = 0
    scored_targets = []
    for target_dir in sorted(batch_dir.glob("targets/target_*")):
        target_path = target_dir / "target.json"
        target = json.loads(target_path.read_text()).get("target", "") if target_path.exists() else ""
        pre_fail_edges = pre_fail_by_target.get(target, 0)
        iter_dir = final_scored_iter_dir(target_dir)
        if iter_dir is None:
            scored_targets.append({
                "target": target,
                "pre_fail_edges": pre_fail_edges,
                "scored_iter": None,
                "post_pass": 0,
                "post_fail": 0,
                "post_other": 0,
            })
            continue
        vf = iter_dir / "problem.verifier.json"
        target_pass = 0
        target_fail = 0
        target_other = 0
        if not vf.exists():
            scored_targets.append({
                "target": target,
                "pre_fail_edges": pre_fail_edges,
                "scored_iter": iter_dir.name,
                "post_pass": 0,
                "post_fail": 0,
                "post_other": 0,
            })
            continue
        v = json.loads(vf.read_text())
        for e in v.get("edge_results", []):
            if e.get("rule") != rule:
                continue
            if e.get("status") == "PASS":
                target_pass += 1
            elif e.get("status") in ("FAIL", "ERROR"):
                target_fail += 1
            else:
                target_other += 1
        post_pass += target_pass
        post_fail += target_fail
        post_other += target_other
        resolved_pre_fail_edges += min(target_pass, pre_fail_edges)
        scored_targets.append({
            "target": target,
            "pre_fail_edges": pre_fail_edges,
            "scored_iter": iter_dir.name,
            "post_pass": target_pass,
            "post_fail": target_fail,
            "post_other": target_other,
            "resolved_pre_fail_edges": min(target_pass, pre_fail_edges),
        })

    rule_edges_total = post_pass + post_fail + post_other
    lift_fraction = (resolved_pre_fail_edges / pre_fail_total) if pre_fail_total else 0.0

    holdout_regressed = _holdout_regression()

    record = {
        "rule": rule,
        "proposal_path": str(proposal_path),
        "epoch_scanned": epoch,
        "batch_id": batch_id,
        "candidates_found": len(candidates),
        "candidates_tested": len(queue_targets),
        "pre_fail_total": pre_fail_total,
        "resolved_pre_fail_edges": resolved_pre_fail_edges,
        "scoring_surface": "final accepted attempt per target, else final attempted iteration",
        "post_pass": post_pass,
        "post_fail": post_fail,
        "post_other": post_other,
        "rule_edges_in_post_batch": rule_edges_total,
        "lift_fraction": lift_fraction,
        "holdout_regressed": holdout_regressed,
        "batch_returncode": proc.returncode,
        "scored_targets": scored_targets,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "config_version": cfg_version,
        "min_lift_threshold": runner.get("auto_promote", {}).get("min_lift_fraction", 0.4),
    }
    out_path = proposal_path.with_name(proposal_path.stem + "_closure.json")
    out_path.write_text(json.dumps(record, indent=2))

    print()
    print(f"[closure] rule={rule}")
    print(f"[closure] candidates tested:       {len(queue_targets)} of {len(candidates)} found")
    print(f"[closure] previously-failing edges: {pre_fail_total}")
    print(f"[closure] resolved prior failures:  {resolved_pre_fail_edges}")
    print(f"[closure] scored rule edges:         {rule_edges_total} (PASS={post_pass} FAIL={post_fail} other={post_other})")
    print(f"[closure] lift fraction:            {lift_fraction:.2%}")
    print(f"[closure] holdout regression:       {holdout_regressed or 'none'}")
    print(f"[closure] threshold:                {record['min_lift_threshold']:.2%}")
    print(f"[closure] verdict:                  {'LIFT_CONFIRMED' if lift_fraction >= record['min_lift_threshold'] and not holdout_regressed else 'INSUFFICIENT'}")
    print(f"[closure] sidecar:                  {out_path}")

    queue_path.unlink(missing_ok=True)
    return 0 if (lift_fraction >= record["min_lift_threshold"] and not holdout_regressed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
