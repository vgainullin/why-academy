#!/usr/bin/env python3
"""Stub judge that echoes the human label from the sibling case.json.

Used by judge calibration tests as a perfect-agreement oracle: it produces the
exact verdict a flawless judge would, so the harness should report 100%
agreement and zero false passes. It deliberately ignores the rubric prompt and
any model -- it only exercises the calibration harness's plumbing and scoring.
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
    labels = json.loads((problem_path.parent / "case.json").read_text())["labels"]
    verdicts = {
        k: {"verdict": labels.get(k), "reason": "oracle"}
        for k in ("one_rule_per_edge", "given_facts_visible", "target_goal_reached")
    }
    record = {
        "problem_id": json.loads(problem_path.read_text()).get("id"),
        "backend": "stub_oracle",
        "target": args.target,
        "verdicts": verdicts,
        "overall": labels.get("overall"),
        "adversarial": {"status": "disabled"},
    }
    sidecar = problem_path.with_name(problem_path.stem + args.out_suffix)
    sidecar.write_text(json.dumps(record, indent=2))
    return 0 if record["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
