#!/usr/bin/env python3
"""Stub judge that always returns PASS -- the worst-case rubber stamp.

Used to prove the calibration harness actually catches a broken judge: every
FAIL-labeled case that reaches it becomes a false pass, so the harness must
report false_passes > 0 and a REGRESSED verdict.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("problem")
    ap.add_argument("--target", required=True)
    ap.add_argument("--out-suffix", default=".judge.json")
    ap.add_argument("--no-adversarial", action="store_true")
    ap.add_argument("--engine", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    problem_path = Path(args.problem)
    verdicts = {
        k: {"verdict": "PASS", "reason": "rubber stamp"}
        for k in ("one_rule_per_edge", "given_facts_visible", "target_goal_reached")
    }
    record = {
        "problem_id": json.loads(problem_path.read_text()).get("id"),
        "backend": "stub_lazy",
        "target": args.target,
        "verdicts": verdicts,
        "overall": "PASS",
        "adversarial": {"status": "disabled"},
    }
    sidecar = problem_path.with_name(problem_path.stem + args.out_suffix)
    sidecar.write_text(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
