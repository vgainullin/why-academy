#!/usr/bin/env python3
"""Calibrate the pedagogical judge against the human-labeled holdout corpus.

The verifier checks math; this harness checks the JUDGE. It mirrors production
gate ordering exactly:

  1. Run the verifier on each holdout graph.
  2. Graphs the verifier rejects never reach the judge in production, so they
     are reported in a separate `verifier_caught` bucket and excluded from
     judge-agreement stats. (A verifier-rejected graph can never be a judge
     false-pass, so it is safe by construction.)
  3. For graphs the verifier passes, run the judge (primary, optionally with
     the adversarial second pass) and compare its verdict to the human label.

The metric that gates promotion is FALSE PASSES: cases a human labeled FAIL
that the judge passed. A false pass ships a bad lesson; a false fail only costs
a regeneration. Thresholds come from the `judge_calibration` section of the
pipeline config and can be overridden on the CLI.

The judge is invoked as a subprocess (default: derivations/judge.py) writing a
sidecar this harness then reads, so the exact production code path is measured.
`--judge-cmd` allows substituting a stub for offline/CI runs.

Exit code: 0 iff calibration passes its thresholds; 1 if it regresses; 2 on a
harness error (missing corpus, contradictory case, etc.).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
from config import load_config  # noqa: E402

CALIBRATION_VERSION = "0.1"
CORPUS = ROOT / "test_corpus" / "judge_holdout" / "cases"
REPORTS = ROOT / "test_corpus" / "judge_holdout" / "reports"
RUBRIC_KEYS = ("one_rule_per_edge", "given_facts_visible", "target_goal_reached")


def load_cases(corpus: Path) -> list[dict[str, Any]]:
    cases = []
    for case_dir in sorted(p for p in corpus.iterdir() if p.is_dir()):
        case_file = case_dir / "case.json"
        problem_file = case_dir / "problem.json"
        if not (case_file.exists() and problem_file.exists()):
            continue
        meta = json.loads(case_file.read_text())
        cases.append({
            "id": case_dir.name,
            "dir": case_dir,
            "target": meta["target"],
            "labels": meta["labels"],
            "rationale": meta.get("rationale", ""),
            "label_provenance": meta.get("label_provenance", "seed"),
        })
    return cases


def run_verifier(python: str, problem_path: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [python, str(ROOT / "verify.py"), str(problem_path)],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=120,
    )
    return proc.returncode == 0, proc.stdout + proc.stderr


def run_judge(judge_cmd: list[str], problem_path: Path, target: str,
              sidecar_suffix: str, adversarial: bool, timeout: int) -> dict[str, Any]:
    """Invoke the judge subprocess and return its sidecar record (or an error
    record). The judge writes <problem_stem><suffix>; we read it back."""
    sidecar = problem_path.with_name(problem_path.stem + sidecar_suffix)
    sidecar.unlink(missing_ok=True)
    cmd = [*judge_cmd, str(problem_path), "--target", target, "--out-suffix", sidecar_suffix]
    if not adversarial:
        cmd.append("--no-adversarial")
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=timeout)
    if not sidecar.exists():
        return {
            "overall": "ERROR",
            "_harness_error": f"judge wrote no sidecar (rc={proc.returncode})",
            "_stderr_tail": proc.stderr[-300:],
        }
    record = json.loads(sidecar.read_text())
    record["_judge_rc"] = proc.returncode
    return record


def judge_verdict(record: dict[str, Any], key: str) -> str | None:
    v = (record.get("verdicts") or {}).get(key)
    if isinstance(v, dict):
        return v.get("verdict")
    return v


def score_case(case: dict[str, Any], verifier_ok: bool, judge_record: dict[str, Any] | None) -> dict[str, Any]:
    labels = case["labels"]
    label_overall = labels.get("overall")

    if not verifier_ok:
        # The graph never reaches the judge in production.
        return {
            "id": case["id"],
            "bucket": "verifier_caught",
            "label_overall": label_overall,
            "judge_overall": None,
            "contradiction": label_overall == "PASS",
            "false_pass": False,
            "false_fail": False,
            "overall_agree": None,
            "criteria": {},
            "label_provenance": case["label_provenance"],
        }

    judge_overall = judge_record.get("overall") if judge_record else "ERROR"
    criteria = {}
    for key in RUBRIC_KEYS:
        label_v = labels.get(key)
        judge_v = judge_verdict(judge_record or {}, key)
        # SKIP vs PASS are both non-failing; only compare when the human asserted a hard verdict.
        agree = None
        if label_v in ("PASS", "FAIL") and judge_v in ("PASS", "FAIL", "SKIP"):
            agree = (label_v == judge_v) or (label_v == "PASS" and judge_v == "SKIP")
        criteria[key] = {"label": label_v, "judge": judge_v, "agree": agree}

    overall_agree = (judge_overall == label_overall)
    false_pass = (label_overall == "FAIL" and judge_overall == "PASS")
    false_fail = (label_overall == "PASS" and judge_overall == "FAIL")
    return {
        "id": case["id"],
        "bucket": "judged",
        "label_overall": label_overall,
        "judge_overall": judge_overall,
        "contradiction": False,
        "false_pass": false_pass,
        "false_fail": false_fail,
        "overall_agree": overall_agree,
        "criteria": criteria,
        "adversarial": (judge_record or {}).get("adversarial"),
        "label_provenance": case["label_provenance"],
        "harness_error": (judge_record or {}).get("_harness_error"),
    }


def aggregate(scored: list[dict[str, Any]], thresholds: dict[str, Any]) -> dict[str, Any]:
    judged = [s for s in scored if s["bucket"] == "judged"]
    verifier_caught = [s for s in scored if s["bucket"] == "verifier_caught"]
    contradictions = [s for s in scored if s["contradiction"]]

    false_passes = [s["id"] for s in judged if s["false_pass"]]
    false_fails = [s["id"] for s in judged if s["false_fail"]]
    harness_errors = [s["id"] for s in judged if s.get("harness_error")]

    overall_agree = [s for s in judged if s["overall_agree"]]
    overall_agreement = (len(overall_agree) / len(judged)) if judged else 0.0

    per_criterion = {}
    for key in RUBRIC_KEYS:
        compared = [s["criteria"][key] for s in judged if s["criteria"].get(key, {}).get("agree") is not None]
        agreed = [c for c in compared if c["agree"]]
        per_criterion[key] = {
            "compared": len(compared),
            "agreed": len(agreed),
            "agreement": (len(agreed) / len(compared)) if compared else None,
        }

    unconfirmed = [s["id"] for s in scored if s["label_provenance"] != "human_confirmed"]

    max_false_pass = int(thresholds.get("max_false_pass", 0))
    min_agreement = float(thresholds.get("min_overall_agreement", 0.8))
    passed = (
        not contradictions
        and not harness_errors
        and len(false_passes) <= max_false_pass
        and (overall_agreement >= min_agreement if judged else False)
    )
    return {
        "n_cases": len(scored),
        "n_judged": len(judged),
        "n_verifier_caught": len(verifier_caught),
        "verifier_caught_ids": [s["id"] for s in verifier_caught],
        "contradictions": [s["id"] for s in contradictions],
        "false_passes": false_passes,
        "false_fails": false_fails,
        "harness_errors": harness_errors,
        "overall_agreement": round(overall_agreement, 4),
        "per_criterion": per_criterion,
        "unconfirmed_labels": unconfirmed,
        "thresholds": {"max_false_pass": max_false_pass, "min_overall_agreement": min_agreement},
        "passed": passed,
    }


def main() -> int:
    cfg, cfg_version = load_config()
    cal_cfg = cfg.get("judge_calibration", {})
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--judge-cmd", default=None,
                    help="judge invocation (space-separated); default: <python> derivations/judge.py")
    ap.add_argument("--adversarial", action="store_true",
                    help="run the adversarial second pass (the verdict the pipeline actually uses)")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--max-false-pass", type=int, default=None)
    ap.add_argument("--min-overall-agreement", type=float, default=None)
    ap.add_argument("--out", default=None, help="report path; default: timestamped under reports/")
    args = ap.parse_args()

    corpus = Path(args.corpus)
    if not corpus.exists():
        print(f"[calibration] FAIL: corpus not found at {corpus}", file=sys.stderr)
        return 2
    cases = load_cases(corpus)
    if not cases:
        print(f"[calibration] FAIL: no cases under {corpus}", file=sys.stderr)
        return 2

    python = os.environ.get("DERIVATION_PYTHON") or sys.executable
    judge_cmd = args.judge_cmd.split() if args.judge_cmd else [python, str(ROOT / "judge.py")]
    suffix = ".judge_calibration.json"

    scored = []
    for case in cases:
        problem_path = case["dir"] / "problem.json"
        verifier_ok, _ = run_verifier(python, problem_path)
        judge_record = None
        if verifier_ok:
            judge_record = run_judge(judge_cmd, problem_path, case["target"], suffix, args.adversarial, args.timeout)
        scored.append(score_case(case, verifier_ok, judge_record))

    thresholds = {
        "max_false_pass": args.max_false_pass if args.max_false_pass is not None
        else cal_cfg.get("max_false_pass", 0),
        "min_overall_agreement": args.min_overall_agreement if args.min_overall_agreement is not None
        else cal_cfg.get("min_overall_agreement", 0.8),
    }
    summary = aggregate(scored, thresholds)
    report = {
        "calibration_version": CALIBRATION_VERSION,
        "config_version": cfg_version,
        "judge_cmd": judge_cmd,
        "adversarial": args.adversarial,
        "summary": summary,
        "cases": scored,
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else (REPORTS / "latest.json")
    out_path.write_text(json.dumps(report, indent=2) + "\n")

    print(f"JUDGE CALIBRATION  (config {cfg_version}, adversarial={args.adversarial})")
    print(f"  cases:            {summary['n_cases']}  (judged {summary['n_judged']}, "
          f"verifier-caught {summary['n_verifier_caught']})")
    print(f"  overall agreement: {summary['overall_agreement']:.0%}  "
          f"(threshold >= {thresholds['min_overall_agreement']:.0%})")
    for key in RUBRIC_KEYS:
        pc = summary["per_criterion"][key]
        agr = f"{pc['agreement']:.0%}" if pc["agreement"] is not None else "n/a"
        print(f"    {key:22s} {agr:>5s}  ({pc['agreed']}/{pc['compared']})")
    print(f"  FALSE PASSES:      {len(summary['false_passes'])}  {summary['false_passes'] or ''}  "
          f"(threshold <= {thresholds['max_false_pass']})")
    print(f"  false fails:       {len(summary['false_fails'])}  {summary['false_fails'] or ''}")
    if summary["contradictions"]:
        print(f"  CONTRADICTIONS:    {summary['contradictions']}  (PASS-labeled but verifier-rejected -- fix the corpus)")
    if summary["harness_errors"]:
        print(f"  HARNESS ERRORS:    {summary['harness_errors']}")
    if summary["unconfirmed_labels"]:
        print(f"  note: {len(summary['unconfirmed_labels'])} case(s) still have seed (unconfirmed) labels; "
              f"verdict measures consistency with the harness author, not ground truth")
    print(f"  report:            {out_path}")
    print(f"  VERDICT:           {'PASS' if summary['passed'] else 'REGRESSED'}")

    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
