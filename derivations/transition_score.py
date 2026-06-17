#!/usr/bin/env python3
"""Score whether one evolution iteration improved over the previous failure."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from failure_diagnosis import diagnosis_key, diagnose_iter  # noqa: E402


GATE_RANK = {
    "runtime": 0,
    "verify": 1,
    "canvas": 2,
    "judge": 3,
    "target": 4,
    "accepted": 5,
}


def score_transition(prev_iter: Path, next_iter: Path) -> dict:
    prev = diagnose_iter(prev_iter)
    nxt = diagnose_iter(next_iter)
    prev_key = diagnosis_key(prev)
    next_key = diagnosis_key(nxt)
    prev_rank = GATE_RANK.get(prev.get("gate"), 0)
    next_rank = GATE_RANK.get(nxt.get("gate"), 0)

    score = float(next_rank - prev_rank)
    resolved = []
    introduced = []
    if next_key != prev_key:
        resolved.append(prev_key)
        if nxt.get("gate") != "accepted":
            introduced.append(next_key)
    else:
        score -= 0.5

    if nxt.get("gate") == "accepted":
        score += 2.0
        verdict = "accepted"
    elif next_rank > prev_rank:
        score += 0.5
        verdict = "improved"
    elif next_rank == prev_rank and next_key != prev_key:
        verdict = "changed_same_gate"
    else:
        verdict = "regressed"

    return {
        "previous_iter": prev_iter.name,
        "next_iter": next_iter.name,
        "previous_gate": prev.get("gate"),
        "next_gate": nxt.get("gate"),
        "previous_key": prev_key,
        "next_key": next_key,
        "resolved_classes": resolved,
        "introduced_classes": introduced,
        "score": score,
        "verdict": verdict,
        "previous": prev,
        "next": nxt,
    }


def write_transition(prev_iter: Path, next_iter: Path) -> dict:
    rec = score_transition(prev_iter, next_iter)
    (next_iter / "transition_score.json").write_text(json.dumps(rec, indent=2))
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("previous_iter")
    ap.add_argument("next_iter")
    args = ap.parse_args()
    print(json.dumps(write_transition(Path(args.previous_iter), Path(args.next_iter)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
