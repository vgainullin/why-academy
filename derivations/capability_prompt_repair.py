#!/usr/bin/env python3
"""Turn failed capability candidates into prompt addenda.

This is the feedback path for "not a safe validator promotion". A proposal that
is rejected or fails capability_eval still contains useful learning signal: the
generator should stop emitting that unsafe edge shape, or should emit the rule
with a stricter local contract.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
CAPABILITIES = ROOT / "_evolutions" / "capabilities"


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def proposal_dirs(paths: list[str], latest_index: Path | None) -> list[Path]:
    out: list[Path] = []
    if paths:
        for raw in paths:
            p = Path(raw)
            if (p / "proposal.json").exists():
                out.append(p)
            elif p.is_dir():
                out.extend(sorted(q.parent for q in p.glob("*/proposal.json")))
    else:
        index_path = latest_index or CAPABILITIES / "latest_index.json"
        index = read_json(index_path) or {}
        out.extend(Path(p) for p in index.get("written", []))
    deduped = []
    seen = set()
    for p in out:
        key = str(p)
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def failed_eval_reasons(eval_payload: dict[str, Any]) -> list[str]:
    reasons = []
    for key in ("results", "closure_results", "orientation_results"):
        for row in eval_payload.get(key) or []:
            if not row.get("ok", True):
                desc = row.get("description", "")
                reason = row.get("reason", "")
                reasons.append(f"{desc}: {reason}".strip(": "))
    return reasons[:12]


def addendum_for_missing_args(rule: str) -> str:
    if rule == "take_positive_square_root":
        return (
            "## Addendum (capability repair): take_positive_square_root requires explicit assumptions\n\n"
            "Gate: capability_synthesis/capability_eval found unsafe `take_positive_square_root` edges. "
            "When emitting `take_positive_square_root`, include rule_args "
            '`{ "var": "Symbol(\'<name>\')", "assume_nonnegative": true }` with the actual solved symbol, '
            "and only use the rule when the positive branch is justified by the target or givens. "
            "If those assumptions are absent, do not use this edge; leave the verifier failure visible instead of "
            "silently choosing a branch or weakening the requested goal.\n"
        )
    return (
        f"## Addendum (capability repair): {rule} requires complete rule_args\n\n"
        f"Gate: capability closure found that `{rule}` cannot be safely validated with the recorded args. "
        f"Do not emit `{rule}` with empty or inferred `rule_args`; include the complete local contract required "
        "by the rule, or decompose the derivation into smaller verifier-backed edges.\n"
    )


def addendum_for_orientation(rule: str) -> str:
    return (
        f"## Addendum (capability repair): {rule} preserves Eq side orientation\n\n"
        f"Gate: capability_eval orientation guard rejected `{rule}` because it accepted a result only after "
        "swapping Eq left and right sides. A non-swap rule must preserve equation side orientation exactly. "
        f"If the derivation needs both `{rule}` and a side swap, emit `{rule}` as one edge and then emit a "
        "separate `swap_sides` edge; never fuse both transformations into one rule edge.\n"
    )


def addendum_for_general_failure(rule: str, reasons: list[str]) -> str:
    sample = " ".join(reasons[:3])[:500]
    return (
        f"## Addendum (capability repair): avoid unsafe {rule} edge shapes\n\n"
        f"Gate: capability_eval failed for `{rule}`. Do not repeat the failed edge shape; use only the exact "
        "local transformation named by the rule, with complete `rule_args`, and split any extra algebra into "
        f"separate edges. Failure sample: {sample}\n"
    )


def build_repair(proposal_dir: Path) -> dict[str, Any] | None:
    proposal = read_json(proposal_dir / "proposal.json") or {}
    if not proposal:
        return None
    rule = str(proposal.get("rule_name") or proposal_dir.name)
    candidate_dir = proposal_dir / "candidate"
    rejected = read_json(candidate_dir / "rejected.json")
    eval_payload = read_json(candidate_dir / "eval.json")

    addenda: list[str] = []
    reasons: list[str] = []
    status = "none"

    if rejected:
        status = "rejected"
        reason = str(rejected.get("reason", ""))
        reasons.append(reason)
        if "rule_args" in reason or "assumption" in reason or "nonnegative" in reason or rule == "take_positive_square_root":
            addenda.append(addendum_for_missing_args(rule))
        else:
            addenda.append(addendum_for_general_failure(rule, [reason]))

    if eval_payload and eval_payload.get("status") not in ("PASS", "REJECTED"):
        status = "eval_failed" if status == "none" else f"{status}+eval_failed"
        eval_reasons = failed_eval_reasons(eval_payload)
        reasons.extend(eval_reasons)
        orientation_failed = eval_payload.get("orientation_status") == "FAIL"
        if eval_payload.get("closure_status") == "FAIL":
            joined = " ".join(eval_reasons)
            if "missing" in joined or "args" in joined or "assumption" in joined:
                addenda.append(addendum_for_missing_args(rule))
            elif not orientation_failed:
                addenda.append(addendum_for_general_failure(rule, eval_reasons))
        if orientation_failed:
            addenda.append(addendum_for_orientation(rule))
        if eval_payload.get("unit_status") == "FAIL" and not addenda:
            addenda.append(addendum_for_general_failure(rule, eval_reasons))

    unique_addenda = []
    seen = set()
    for text in addenda:
        if text not in seen:
            seen.add(text)
            unique_addenda.append(text)
    if not unique_addenda:
        return None

    repair = {
        "schema_version": "capability_prompt_repair.v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "proposal_dir": rel(proposal_dir),
        "rule_name": rule,
        "status": status,
        "reasons": reasons[:12],
        "addenda": unique_addenda,
    }
    (proposal_dir / "prompt_repair.json").write_text(json.dumps(repair, indent=2) + "\n")
    (proposal_dir / "prompt_repair.md").write_text("\n".join(unique_addenda).rstrip() + "\n")
    return repair


def write_outputs(repairs: list[dict[str, Any]], out_path: Path, json_out: Path | None) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Capability Prompt Repairs",
        "",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        "",
    ]
    for repair in repairs:
        lines.extend(repair["addenda"])
        lines.append("")
    out_path.write_text("\n".join(lines).rstrip() + "\n")

    payload = {
        "schema_version": "capability_prompt_repairs.v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "out": rel(out_path),
        "repairs": repairs,
    }
    json_path = json_out or out_path.with_suffix(".json")
    json_path.write_text(json.dumps(payload, indent=2) + "\n")
    (CAPABILITIES / "latest_prompt_repair.md").write_text(out_path.read_text())
    (CAPABILITIES / "latest_prompt_repair.json").write_text(json.dumps(payload, indent=2) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal-dir", action="append", default=[],
                    help="proposal dir or parent dir containing proposals; repeatable")
    ap.add_argument("--latest-index", default=None)
    ap.add_argument("--out", default=str(CAPABILITIES / "prompt_repair.md"))
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    dirs = proposal_dirs(args.proposal_dir, Path(args.latest_index) if args.latest_index else None)
    repairs = []
    for proposal_dir in dirs:
        repair = build_repair(proposal_dir)
        if repair:
            repairs.append(repair)
            print(f"[capability_prompt_repair] repair for {proposal_dir}")

    if not repairs:
        print("[capability_prompt_repair] no failed/rejected capability candidates")
        return 1

    write_outputs(repairs, Path(args.out), Path(args.json_out) if args.json_out else None)
    print(f"[capability_prompt_repair] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
