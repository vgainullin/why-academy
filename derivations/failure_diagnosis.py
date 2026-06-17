#!/usr/bin/env python3
"""Normalize per-iteration failures into a repairable diagnosis record."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        return {"_parse_error": str(e)}


def diagnose_judge(judge_path: Path) -> dict:
    judge = _read_json(judge_path) or {}
    verdicts = judge.get("verdicts") or {}
    for criterion, payload in verdicts.items():
        if payload.get("verdict") == "FAIL":
            return {
                "gate": "judge",
                "failure_class": criterion,
                "rule": None,
                "details": payload.get("reason", ""),
                "severity": "blocking",
                "repair_scope": "prompt",
                "source_path": str(judge_path),
                "raw": {"overall": judge.get("overall"), "verdicts": verdicts},
            }
    return {
        "gate": "judge",
        "failure_class": "judge_error",
        "rule": None,
        "details": f"judge overall={judge.get('overall', 'missing')}",
        "severity": "blocking",
        "repair_scope": "prompt",
        "source_path": str(judge_path),
        "raw": judge,
    }


def diagnose_verifier(verifier_path: Path) -> dict:
    verifier = _read_json(verifier_path) or {}
    parse_errors = verifier.get("parse_errors") or []
    if parse_errors:
        return {
            "gate": "verify",
            "failure_class": "parse_error",
            "rule": None,
            "details": "; ".join(str(e) for e in parse_errors[:3]),
            "severity": "blocking",
            "repair_scope": "prompt",
            "source_path": str(verifier_path),
            "raw": {"parse_errors": parse_errors},
        }

    failures = [
        e for e in verifier.get("edge_results", [])
        if e.get("status") in ("FAIL", "ERROR")
    ]
    if failures:
        first = failures[0]
        rule = first.get("rule")
        reason = first.get("reason", "")
        unknown_rule = isinstance(reason, str) and reason.startswith("unknown rule ")
        return {
            "gate": "verify",
            "failure_class": (
                "unknown_rule"
                if unknown_rule else
                "rule_error" if first.get("status") == "ERROR" else "rule_fail"
            ),
            "rule": rule,
            "details": reason,
            "severity": "blocking",
            "repair_scope": "prompt" if unknown_rule or not rule else "validator",
            "source_path": str(verifier_path),
            "raw": {
                "edge_summary": verifier.get("edge_summary"),
                "failures": failures[:10],
            },
        }

    return {
        "gate": "verify",
        "failure_class": "verifier_missing_failure",
        "rule": None,
        "details": "verifier was treated as failed, but no FAIL/ERROR edge was found",
        "severity": "blocking",
        "repair_scope": "prompt",
        "source_path": str(verifier_path),
        "raw": verifier,
    }


def diagnose_canvas(canvas_path: Path, log_path: Path | None = None) -> dict:
    canvas = _read_json(canvas_path) or {}
    summary = canvas.get("summary") or {}
    failure_class = "canvas_fail"
    if summary.get("PARSE_ERROR_IN", 0):
        failure_class = "parse_in"
    elif summary.get("RENDER_ERROR", 0):
        failure_class = "render_error"
    elif summary.get("PARSE_ERROR_OUT", 0):
        failure_class = "parse_out"
    elif canvas.get("n_duplicates", 0):
        failure_class = "duplicate_forms"
    details = json.dumps({
        "summary": summary,
        "n_duplicates": canvas.get("n_duplicates", 0),
        "duplicates": canvas.get("duplicates", [])[:5],
    }, sort_keys=True)
    if log_path and log_path.exists():
        log_tail = log_path.read_text()[-1200:]
        if log_tail.strip():
            details += "\n" + log_tail
    return {
        "gate": "canvas",
        "failure_class": failure_class,
        "rule": None,
        "details": details,
        "severity": "blocking",
        "repair_scope": "prompt",
        "source_path": str(canvas_path),
        "raw": canvas,
    }


def diagnose_target(target_path: Path) -> dict:
    target = _read_json(target_path) or {}
    return {
        "gate": "target",
        "failure_class": str(target.get("status", "target_mismatch")).lower(),
        "rule": None,
        "details": target.get("reason", "goal_node did not match requested target"),
        "severity": "blocking",
        "repair_scope": "prompt",
        "source_path": str(target_path),
        "raw": target,
    }


def diagnose_iter(iter_dir: Path, gate: str | None = None) -> dict:
    if gate is None:
        status_path = iter_dir / "status.txt"
        status = status_path.read_text().strip() if status_path.exists() else ""
        if status == "PASS":
            return {
                "gate": "accepted",
                "failure_class": "accepted",
                "rule": None,
                "details": "accepted",
                "severity": "none",
                "repair_scope": "none",
                "source_path": str(status_path),
                "raw": {},
            }
        if status == "canvas_fail":
            gate = "canvas"
        elif status == "verify_fail":
            gate = "verify"
        elif status == "target_fail":
            gate = "target"
        elif status == "FAIL":
            gate = "judge"
        else:
            gate = "runtime"

    if gate == "judge":
        return diagnose_judge(iter_dir / "problem.judge.json")
    if gate == "verify":
        return diagnose_verifier(iter_dir / "problem.verifier.json")
    if gate == "canvas":
        return diagnose_canvas(iter_dir / "problem.canvas_check.json", iter_dir / "canvas_check.log")
    if gate == "target":
        return diagnose_target(iter_dir / "problem.target_check.json")
    parse_error = _read_json(iter_dir / "problem_parse_error.json")
    if parse_error:
        return {
            "gate": gate,
            "failure_class": "problem_json_invalid",
            "rule": None,
            "details": parse_error.get("error", ""),
            "severity": "blocking",
            "repair_scope": "prompt",
            "source_path": str(iter_dir / "problem_parse_error.json"),
            "raw": {
                "error": parse_error.get("error"),
                "raw_preview": str(parse_error.get("raw", ""))[:1200],
            },
        }
    rule_plan_error = _read_json(iter_dir / "rule_plan_parse_error.json")
    if rule_plan_error:
        return {
            "gate": gate,
            "failure_class": "rule_plan_invalid",
            "rule": None,
            "details": rule_plan_error.get("error", ""),
            "severity": "blocking",
            "repair_scope": "prompt",
            "source_path": str(iter_dir / "rule_plan_parse_error.json"),
            "raw": {
                "error": rule_plan_error.get("error"),
                "raw_preview": str(rule_plan_error.get("raw", ""))[:1200],
            },
        }
    bridge_error = _read_json(iter_dir / "normalization_bridge_error.json")
    if bridge_error:
        failure_class = bridge_error.get("failure_class", "normalization_bridge_fail")
        return {
            "gate": gate,
            "failure_class": failure_class,
            "rule": None,
            "details": bridge_error.get("error", ""),
            "severity": "blocking",
            "repair_scope": "normalizer",
            "source_path": str(iter_dir / "normalization_bridge_error.json"),
            "raw": bridge_error,
        }
    executor_error = _read_json(iter_dir / "rule_executor_error.json")
    if executor_error:
        failure_class = executor_error.get("failure_class", "rule_executor_fail")
        return {
            "gate": gate,
            "failure_class": failure_class,
            "rule": None,
            "details": executor_error.get("error", ""),
            "severity": "blocking",
            "repair_scope": "executor" if failure_class == "rule_executor_coverage_gap" else "prompt",
            "source_path": str(iter_dir / "rule_executor_error.json"),
            "raw": executor_error,
        }
    return {
        "gate": gate,
        "failure_class": "runtime_failure",
        "rule": None,
        "details": (iter_dir / "status.txt").read_text().strip() if (iter_dir / "status.txt").exists() else "",
        "severity": "blocking",
        "repair_scope": "runtime",
        "source_path": str(iter_dir),
        "raw": {},
    }


def diagnosis_key(d: dict | None) -> str:
    if not d:
        return "none"
    rule = d.get("rule")
    return ":".join(str(x) for x in (d.get("gate"), d.get("failure_class"), rule or "-"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("iter_dir")
    ap.add_argument("--gate", choices=["verify", "canvas", "judge", "target", "runtime"], default=None)
    args = ap.parse_args()
    print(json.dumps(diagnose_iter(Path(args.iter_dir), args.gate), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
