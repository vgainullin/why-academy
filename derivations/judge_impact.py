#!/usr/bin/env python3
"""Report whether the hardened judge materially changed real e2e batch results.

For each generated problem.json in a batch, compare:

  old gate:      primary_overall if present, else overall
  hardened gate: final overall

Current production judge sidecars include primary_overall only when the
adversarial pass ran. That lets this script quantify which candidates the old
primary-only gate would have accepted but the hardened gate blocked, and whether
that delayed or prevented target acceptance.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
DEFAULT_REPORT_NAME = "judge_impact"


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        return {"_error": str(e), "_path": str(path)}


def discover_batch_problems(batch_dir: Path) -> list[Path]:
    return sorted(batch_dir.glob("targets/target_*/iter_*/problem.json"))


def target_text(problem_path: Path) -> str:
    target_file = problem_path.parent.parent / "target.json"
    meta = read_json(target_file) or {}
    if isinstance(meta.get("target"), str):
        return meta["target"]
    problem = read_json(problem_path) or {}
    return str(problem.get("id", problem_path.stem))


def iter_number(problem_path: Path) -> int | None:
    name = problem_path.parent.name
    if not name.startswith("iter_"):
        return None
    try:
        return int(name.removeprefix("iter_"))
    except ValueError:
        return None


def target_id(problem_path: Path) -> str:
    return problem_path.parent.parent.name


def run_production_judge(problem_path: Path, target: str, suffix: str, timeout: int) -> dict[str, Any]:
    python = os.environ.get("DERIVATION_PYTHON") or sys.executable
    sidecar = problem_path.with_name(problem_path.stem + suffix)
    sidecar.unlink(missing_ok=True)
    proc = subprocess.run(
        [
            python,
            str(ROOT / "judge.py"),
            str(problem_path),
            "--target",
            target,
            "--out-suffix",
            suffix,
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    record = read_json(sidecar)
    if record is None:
        return {
            "overall": "ERROR",
            "_impact_error": f"judge wrote no sidecar (rc={proc.returncode})",
            "_stderr_tail": proc.stderr[-300:],
        }
    record["_impact_judge_rc"] = proc.returncode
    return record


def candidate_row(problem_path: Path, record: dict[str, Any]) -> dict[str, Any]:
    primary = record.get("primary_overall", record.get("overall"))
    hardened = record.get("overall")
    adversarial = record.get("adversarial") or {}
    status = adversarial.get("status")
    changed = primary == "PASS" and hardened != "PASS"
    if changed and status == "refuted":
        impact = "blocked_by_refutation"
    elif changed and status == "error":
        impact = "blocked_by_error"
    elif primary == "PASS" and hardened == "PASS":
        impact = "accepted_by_both"
    elif primary != "PASS" and hardened != "PASS":
        impact = "rejected_by_both"
    elif primary != "PASS" and hardened == "PASS":
        impact = "accepted_only_hardened"
    else:
        impact = "other"

    return {
        "target_id": target_id(problem_path),
        "iter": problem_path.parent.name,
        "iter_number": iter_number(problem_path),
        "problem": str(problem_path),
        "problem_id": (read_json(problem_path) or {}).get("id"),
        "target": target_text(problem_path),
        "primary_overall": primary,
        "hardened_overall": hardened,
        "adversarial_status": status,
        "adversarial_reason": adversarial.get("reason") or adversarial.get("error") or "",
        "impact": impact,
        "changed": changed,
    }


def target_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_target: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_target.setdefault(row["target_id"], []).append(row)

    out = []
    for tid, group in sorted(by_target.items()):
        group = sorted(group, key=lambda r: (r["iter_number"] is None, r["iter_number"] or 0))
        old_accept = next((r for r in group if r["primary_overall"] == "PASS"), None)
        hard_accept = next((r for r in group if r["hardened_overall"] == "PASS"), None)
        if old_accept and hard_accept:
            old_i = old_accept["iter_number"]
            hard_i = hard_accept["iter_number"]
            if old_i is not None and hard_i is not None and hard_i > old_i:
                impact = "delayed_acceptance"
            else:
                impact = "same_acceptance"
        elif old_accept and not hard_accept:
            impact = "prevented_acceptance"
        elif not old_accept and hard_accept:
            impact = "accepted_only_hardened"
        else:
            impact = "same_rejection"
        out.append({
            "target_id": tid,
            "target": group[0]["target"] if group else "",
            "old_first_accept_iter": old_accept["iter"] if old_accept else None,
            "hardened_first_accept_iter": hard_accept["iter"] if hard_accept else None,
            "impact": impact,
        })
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    target_summary = target_rows(rows)
    changed = [r for r in rows if r["changed"]]
    return {
        "n_candidates": len(rows),
        "n_targets": len(target_summary),
        "old_accept_candidates": sum(1 for r in rows if r["primary_overall"] == "PASS"),
        "hardened_accept_candidates": sum(1 for r in rows if r["hardened_overall"] == "PASS"),
        "changed_candidates": len(changed),
        "blocked_by_refutation": [r["problem_id"] for r in rows if r["impact"] == "blocked_by_refutation"],
        "blocked_by_error": [r["problem_id"] for r in rows if r["impact"] == "blocked_by_error"],
        "changed_targets": [
            t for t in target_summary
            if t["impact"] in ("delayed_acceptance", "prevented_acceptance", "accepted_only_hardened")
        ],
        "material_difference": bool(
            changed
            or any(t["impact"] in ("delayed_acceptance", "prevented_acceptance", "accepted_only_hardened")
                   for t in target_summary)
        ),
        "targets": target_summary,
    }


def write_markdown(report: dict[str, Any], out_path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# Judge Impact Report",
        "",
        f"- Material difference: `{summary['material_difference']}`",
        f"- Candidates: {summary['n_candidates']}",
        f"- Targets: {summary['n_targets']}",
        f"- Old primary-only accepts: {summary['old_accept_candidates']}",
        f"- Hardened accepts: {summary['hardened_accept_candidates']}",
        f"- Changed candidates: {summary['changed_candidates']}",
        "",
        "## Target Outcomes",
        "",
        "| Target | Old first accept | Hardened first accept | Impact |",
        "| --- | --- | --- | --- |",
    ]
    for target in summary["targets"]:
        lines.append(
            f"| {target['target_id']} | `{target['old_first_accept_iter'] or ''}` | "
            f"`{target['hardened_first_accept_iter'] or ''}` | `{target['impact']}` |"
        )
    lines += [
        "",
        "## Candidate Deltas",
        "",
        "| Problem | Target | Iter | Primary | Hardened | Adversarial | Impact |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["rows"]:
        if not row["changed"]:
            continue
        reason = str(row.get("adversarial_reason") or "").replace("\n", " ")[:120]
        lines.append(
            f"| `{row['problem_id']}` | `{row['target_id']}` | `{row['iter']}` | "
            f"`{row['primary_overall']}` | `{row['hardened_overall']}` | "
            f"`{row['adversarial_status']}` | `{row['impact']}: {reason}` |"
        )
    out_path.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_dir", nargs="?", help="derivations/_evolutions/batches/<batch_id>")
    ap.add_argument("--files", nargs="*", default=None, help="explicit problem.json files")
    ap.add_argument("--run-missing", action="store_true",
                    help="run production judge for problems without a sidecar")
    ap.add_argument("--refresh", action="store_true",
                    help="rerun production judge even when a sidecar exists")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--out", default=None, help="JSON report path")
    args = ap.parse_args()

    if args.files:
        problems = [Path(f) for f in args.files]
        base = Path.cwd()
    elif args.batch_dir:
        base = Path(args.batch_dir)
        problems = discover_batch_problems(base)
    else:
        print("usage: judge_impact.py <batch_dir>|--files problem.json ...", file=sys.stderr)
        return 2

    if not problems:
        print("[judge-impact] no problem.json files found", file=sys.stderr)
        return 2

    rows = []
    skipped = []
    for problem_path in problems:
        sidecar = problem_path.with_name(problem_path.stem + ".judge.json")
        record = None if args.refresh else read_json(sidecar)
        if record is None and args.run_missing:
            record = run_production_judge(problem_path, target_text(problem_path), ".judge.json", args.timeout)
        if record is None:
            skipped.append(str(problem_path))
            continue
        rows.append(candidate_row(problem_path, record))

    report = {
        "batch_dir": str(args.batch_dir or ""),
        "summary": summarize(rows),
        "rows": rows,
        "skipped_without_sidecar": skipped,
    }

    out_json = Path(args.out) if args.out else (base / f"{DEFAULT_REPORT_NAME}.json")
    out_md = out_json.with_suffix(".md")
    out_json.write_text(json.dumps(report, indent=2) + "\n")
    write_markdown(report, out_md)

    s = report["summary"]
    print("JUDGE IMPACT")
    print(f"  candidates:         {s['n_candidates']}  (skipped {len(skipped)})")
    print(f"  targets:            {s['n_targets']}")
    print(f"  primary accepts:    {s['old_accept_candidates']}")
    print(f"  hardened accepts:   {s['hardened_accept_candidates']}")
    print(f"  changed candidates: {s['changed_candidates']}")
    print(f"  material:           {s['material_difference']}")
    print(f"  report:             {out_md}")
    return 0 if s["material_difference"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
