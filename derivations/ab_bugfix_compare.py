#!/usr/bin/env python3
"""A/B comparison for bugfix workflow results across two worktrees.

Reads the BUGFIX closure sidecars (proposal_bug_*_closure.json) from two
worktrees that each ran the bug_investigate workflow, and produces a paired
comparison report in the same JSON + markdown style as ab_compare.py.

Unlike ab_compare.py (which compares generation-batch target outcomes), this
tool compares *bugfix results*: closure verdicts, lift fractions, holdout
regression, seed evidence counts, and regression test coverage. Both worktrees
should have run with identical config so the comparison measures the variance
of the bugfix workflow itself.

CLI:
  ab_bugfix_compare.py --control <worktree_path> --treatment <worktree_path>
                       [--experiment-id <id>] [--out-dir <path>]

Outputs (written to --out-dir, default: main repo root):
  ab_bugfix_comparison.json
  ab_bugfix_comparison.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _reexec_with_derivation_python() -> None:
    if os.environ.get("AB_BUGFIX_REEXECED") == "1":
        return
    candidates: list[Path] = []
    configured = os.environ.get("DERIVATION_PYTHON")
    if configured:
        candidates.append(Path(configured))
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "derivations" / ".venv" / "bin" / "python")
        candidates.append(parent / ".venv" / "bin" / "python")
    current = Path(sys.executable).resolve()
    for candidate in candidates:
        if candidate.exists() and candidate.resolve() != current:
            os.environ["AB_BUGFIX_REEXECED"] = "1"
            os.execv(str(candidate), [str(candidate), *sys.argv])


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def find_closure_sidecars(worktree: Path) -> list[dict[str, Any]]:
    """Find all proposal_bug_*_closure.json files in a worktree's reports dir.

    Returns a list of parsed closure records, each annotated with the source
    file path and the proposal file path.
    """
    reports_root = worktree / "derivations" / "reports"
    sidecars: list[dict[str, Any]] = []
    if not reports_root.exists():
        return sidecars
    for sc in sorted(reports_root.glob("epoch_*/proposal_bug_*_closure.json")):
        record = read_json(sc)
        if not isinstance(record, dict):
            continue
        record["_closure_path"] = str(sc)
        record["_proposal_path"] = record.get("proposal_path", "")
        sidecars.append(record)
    return sidecars


def find_proposals(worktree: Path) -> list[dict[str, Any]]:
    """Find all proposal_bug_*.md files and extract metadata."""
    reports_root = worktree / "derivations" / "reports"
    proposals: list[dict[str, Any]] = []
    if not reports_root.exists():
        return proposals
    import re
    kind_re = re.compile(r"^\*\*Kind\*\*:\s*`?([A-Za-z_]+)`?", re.MULTILINE)
    seed_re = re.compile(r"^\*\*Seed hypothesis\*\*:\s*`?([^\s`]+)`?", re.MULTILINE)
    rule_re = re.compile(r"^\*\*Affected rule\*\*:\s*`?([^\s`]+)`?", re.MULTILINE)
    evidence_re = re.compile(r"^\*\*Evidence count\*\*:\s*(\d+)", re.MULTILINE)
    for p in sorted(reports_root.glob("epoch_*/proposal_bug_*.md")):
        text = p.read_text()
        proposals.append({
            "_path": str(p),
            "kind": (kind_re.search(text) or [None, ""])[1] if kind_re.search(text) else "",
            "seed": (seed_re.search(text) or [None, ""])[1] if seed_re.search(text) else "",
            "rule": (rule_re.search(text) or [None, ""])[1] if rule_re.search(text) else "",
            "evidence_count": int((evidence_re.search(text) or [None, "0"])[1]) if evidence_re.search(text) else 0,
        })
    return proposals


def count_regression_tests(worktree: Path, rule: str) -> dict[str, int]:
    """Count positive/negative regression entries for a rule in the worktree."""
    corpus = worktree / "derivations" / "test_corpus" / rule
    pos = read_json(corpus / "positive.json", [])
    neg = read_json(corpus / "negative.json", [])
    bugfix_pos = sum(1 for e in pos if "bugfix:" in e.get("description", "")) if isinstance(pos, list) else 0
    bugfix_neg = sum(1 for e in neg if "bugfix:" in e.get("description", "")) if isinstance(neg, list) else 0
    return {
        "total_positive": len(pos) if isinstance(pos, list) else 0,
        "total_negative": len(neg) if isinstance(neg, list) else 0,
        "bugfix_positive": bugfix_pos,
        "bugfix_negative": bugfix_neg,
    }


def read_state(worktree: Path) -> dict[str, Any]:
    return read_json(worktree / "derivations" / "state.json", {})


def read_epoch_state(worktree: Path) -> dict[str, Any]:
    return read_json(worktree / "derivations" / "_epoch_state.json", {})


def summarize_worktree(worktree: Path) -> dict[str, Any]:
    """Build a per-worktree summary of bugfix results."""
    closures = find_closure_sidecars(worktree)
    proposals = find_proposals(worktree)
    state = read_state(worktree)
    epoch_state = read_epoch_state(worktree)

    # Index closures by seed for pairing.
    closures_by_seed: dict[str, dict[str, Any]] = {}
    for c in closures:
        seed = c.get("seed_hypothesis", "")
        if seed:
            closures_by_seed[seed] = c

    # Index proposals by seed.
    proposals_by_seed: dict[str, dict[str, Any]] = {}
    for p in proposals:
        seed = p.get("seed", "")
        if seed:
            proposals_by_seed[seed] = p

    all_seeds = sorted(set(closures_by_seed) | set(proposals_by_seed))

    seed_results: list[dict[str, Any]] = []
    for seed in all_seeds:
        closure = closures_by_seed.get(seed, {})
        proposal = proposals_by_seed.get(seed, {})
        rule = closure.get("rule") or proposal.get("rule", "")
        entry: dict[str, Any] = {
            "seed": seed,
            "kind": proposal.get("kind", closure.get("kind", "")),
            "rule": rule,
            "evidence_count": proposal.get("evidence_count", 0),
            "closure_verdict": None,
            "lift_fraction": None,
            "holdout_regressed": None,
            "actual_status": None,
            "expected_status": None,
            "regression_tests": {},
        }
        if closure:
            entry["closure_verdict"] = (
                "REPRO_CONFIRMED"
                if closure.get("lift_fraction", 0) >= closure.get("min_lift_threshold", 0.4)
                and not closure.get("holdout_regressed")
                else "REPRO_FAILED"
            )
            entry["lift_fraction"] = closure.get("lift_fraction")
            entry["holdout_regressed"] = closure.get("holdout_regressed")
            entry["actual_status"] = closure.get("actual_status")
            entry["expected_status"] = closure.get("expected_status")
        if rule:
            entry["regression_tests"] = count_regression_tests(worktree, rule)
        seed_results.append(entry)

    return {
        "worktree_path": str(worktree),
        "branch": epoch_state.get("batch_id", state.get("config_version", "")),
        "epoch": state.get("epoch"),
        "validator_version": state.get("validator_version"),
        "phase": epoch_state.get("phase"),
        "n_proposals": len(proposals),
        "n_bugfix_proposals": sum(1 for p in proposals if p.get("kind") == "BUGFIX"),
        "n_investigate_proposals": sum(1 for p in proposals if p.get("kind") == "INVESTIGATE"),
        "n_closures": len(closures),
        "seed_results": seed_results,
    }


def compare_worktrees(control: Path, treatment: Path,
                      experiment_id: str | None = None) -> dict[str, Any]:
    """Compare bugfix results from two worktrees.

    Pairs results by seed hypothesis. For each seed present in either worktree,
    reports the closure verdict and lift from both sides, plus a per-seed
    winner.
    """
    c_summary = summarize_worktree(control)
    t_summary = summarize_worktree(treatment)

    c_by_seed = {s["seed"]: s for s in c_summary["seed_results"]}
    t_by_seed = {s["seed"]: s for s in t_summary["seed_results"]}
    all_seeds = sorted(set(c_by_seed) | set(t_by_seed))

    pairs: list[dict[str, Any]] = []
    for seed in all_seeds:
        c_seed = c_by_seed.get(seed, {})
        t_seed = t_by_seed.get(seed, {})

        c_verdict = c_seed.get("closure_verdict")
        t_verdict = t_seed.get("closure_verdict")
        c_lift = c_seed.get("lift_fraction")
        t_lift = t_seed.get("lift_fraction")

        # Winner logic: REPRO_CONFIRMED beats REPRO_FAILED/None; higher lift wins ties.
        winner = "tie"
        if c_verdict == "REPRO_CONFIRMED" and t_verdict != "REPRO_CONFIRMED":
            winner = "control"
        elif t_verdict == "REPRO_CONFIRMED" and c_verdict != "REPRO_CONFIRMED":
            winner = "treatment"
        elif c_verdict == t_verdict:
            if c_lift is not None and t_lift is not None:
                if c_lift > t_lift:
                    winner = "control"
                elif t_lift > c_lift:
                    winner = "treatment"
            elif c_lift is not None and t_lift is None:
                winner = "control"
            elif t_lift is not None and c_lift is None:
                winner = "treatment"

        pairs.append({
            "seed": seed,
            "control": {
                "kind": c_seed.get("kind"),
                "evidence_count": c_seed.get("evidence_count"),
                "closure_verdict": c_verdict,
                "lift_fraction": c_lift,
                "holdout_regressed": c_seed.get("holdout_regressed"),
                "actual_status": c_seed.get("actual_status"),
                "regression_tests": c_seed.get("regression_tests", {}),
            },
            "treatment": {
                "kind": t_seed.get("kind"),
                "evidence_count": t_seed.get("evidence_count"),
                "closure_verdict": t_verdict,
                "lift_fraction": t_lift,
                "holdout_regressed": t_seed.get("holdout_regressed"),
                "actual_status": t_seed.get("actual_status"),
                "regression_tests": t_seed.get("regression_tests", {}),
            },
            "winner": winner,
        })

    c_confirmed = sum(1 for p in pairs if p["control"]["closure_verdict"] == "REPRO_CONFIRMED")
    t_confirmed = sum(1 for p in pairs if p["treatment"]["closure_verdict"] == "REPRO_CONFIRMED")
    c_regressed = sum(1 for p in pairs if p["control"]["holdout_regressed"])
    t_regressed = sum(1 for p in pairs if p["treatment"]["holdout_regressed"])
    c_wins = sum(1 for p in pairs if p["winner"] == "control")
    t_wins = sum(1 for p in pairs if p["winner"] == "treatment")
    ties = sum(1 for p in pairs if p["winner"] == "tie")

    overall_winner = "tie"
    if c_wins > t_wins:
        overall_winner = "control"
    elif t_wins > c_wins:
        overall_winner = "treatment"

    return {
        "experiment_id": experiment_id or f"bugfix_ab_{control.name}_vs_{treatment.name}",
        "control_worktree": c_summary,
        "treatment_worktree": t_summary,
        "paired": {
            "n_seeds": len(all_seeds),
            "control_confirmed": c_confirmed,
            "treatment_confirmed": t_confirmed,
            "control_holdout_regressed": c_regressed,
            "treatment_holdout_regressed": t_regressed,
            "control_wins": c_wins,
            "treatment_wins": t_wins,
            "ties": ties,
            "overall_winner": overall_winner,
        },
        "pairs": pairs,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    c = summary["control_worktree"]
    t = summary["treatment_worktree"]
    p = summary["paired"]
    lines = [
        f"# A/B Bugfix Comparison: {summary.get('experiment_id', '')}",
        "",
        f"- Control worktree: `{c['worktree_path']}`",
        f"- Treatment worktree: `{t['worktree_path']}`",
        f"- Seeds compared: {p['n_seeds']}",
        f"- Closure confirmed: control {p['control_confirmed']}, treatment {p['treatment_confirmed']}",
        f"- Holdout regressed: control {p['control_holdout_regressed']}, treatment {p['treatment_holdout_regressed']}",
        f"- Per-seed wins: control {p['control_wins']}, treatment {p['treatment_wins']}, ties {p['ties']}",
        f"- **Overall winner: {p['overall_winner']}**",
        "",
        "## Worktree summaries",
        "",
        "| Metric | Control | Treatment |",
        "|--------|---------|-----------|",
        f"| Epoch | {c.get('epoch', '?')} | {t.get('epoch', '?')} |",
        f"| Validator version | {c.get('validator_version', '?')} | {t.get('validator_version', '?')} |",
        f"| BUGFIX proposals | {c['n_bugfix_proposals']} | {t['n_bugfix_proposals']} |",
        f"| INVESTIGATE proposals | {c['n_investigate_proposals']} | {t['n_investigate_proposals']} |",
        f"| Closures | {c['n_closures']} | {t['n_closures']} |",
        "",
        "## Per-seed comparison",
        "",
        "| Seed | Kind | Ctrl Verdict | Ctrl Lift | Ctrl Holdout | Treat Verdict | Treat Lift | Treat Holdout | Winner |",
        "|------|------|-------------|-----------|-------------|---------------|------------|---------------|--------|",
    ]
    for pair in summary["pairs"]:
        cv = pair["control"]
        tv = pair["treatment"]
        c_lift = f"{cv['lift_fraction']:.2%}" if cv.get("lift_fraction") is not None else "-"
        t_lift = f"{tv['lift_fraction']:.2%}" if tv.get("lift_fraction") is not None else "-"
        c_ho = cv.get("holdout_regressed") or "none"
        t_ho = tv.get("holdout_regressed") or "none"
        lines.append(
            f"| {pair['seed']} | {cv.get('kind') or tv.get('kind', '')} | "
            f"{cv.get('closure_verdict') or '-'} | {c_lift} | {c_ho} | "
            f"{tv.get('closure_verdict') or '-'} | {t_lift} | {t_ho} | "
            f"{pair['winner']} |"
        )

    lines.extend([
        "",
        "## Regression test coverage",
        "",
        "| Seed | Side | Bugfix + | Bugfix - | Total + | Total - |",
        "|------|------|----------|----------|---------|---------|",
    ])
    for pair in summary["pairs"]:
        for side_label, side_key in [("Control", "control"), ("Treatment", "treatment")]:
            rt = pair[side_key].get("regression_tests", {})
            lines.append(
                f"| {pair['seed']} | {side_label} | "
                f"{rt.get('bugfix_positive', 0)} | {rt.get('bugfix_negative', 0)} | "
                f"{rt.get('total_positive', 0)} | {rt.get('total_negative', 0)} |"
            )

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    _reexec_with_derivation_python()

    ap = argparse.ArgumentParser(description="A/B comparison for bugfix workflow results")
    ap.add_argument("--control", required=True, type=Path,
                    help="path to control worktree")
    ap.add_argument("--treatment", required=True, type=Path,
                    help="path to treatment worktree")
    ap.add_argument("--experiment-id", default=None)
    ap.add_argument("--out-dir", type=Path, default=None,
                    help="where to write comparison artifacts (default: repo root)")
    args = ap.parse_args()

    if not args.control.exists():
        print(f"control worktree not found: {args.control}", file=sys.stderr)
        return 2
    if not args.treatment.exists():
        print(f"treatment worktree not found: {args.treatment}", file=sys.stderr)
        return 2

    summary = compare_worktrees(args.control.resolve(), args.treatment.resolve(),
                                experiment_id=args.experiment_id)

    out_dir = (args.out_dir or PROJECT_ROOT).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ab_bugfix_comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out_dir / "ab_bugfix_comparison.md").write_text(render_markdown(summary) + "\n")

    print(json.dumps(summary["paired"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
