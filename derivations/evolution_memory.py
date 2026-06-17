#!/usr/bin/env python3
"""Reuse prior per-target evolution variants across batches.

The evolution loop already writes target-local prompt variants under
derivations/_evolutions/batches/<batch>/targets/<target>/iter_*/variant.md.
This module selects the best prior variant for the same target so the next
batch continues from accumulated local learning instead of restarting cold from
the canonical prompt.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BATCHES = ROOT / "_evolutions" / "batches"


def normalize_target(target: str) -> str:
    return re.sub(r"\s+", " ", target.strip())


def iter_dir_for_metrics(target_dir: Path, metrics: dict) -> Path | None:
    accepted_at = metrics.get("accepted_at_iter")
    if metrics.get("accepted") and isinstance(accepted_at, int):
        p = target_dir / f"iter_{accepted_at:02d}"
        return p if p.exists() else None

    statuses = metrics.get("iter_statuses") or []
    if statuses:
        p = target_dir / str(statuses[-1][0])
        return p if p.exists() else None

    iters = sorted(target_dir.glob("iter_*"))
    return iters[-1] if iters else None


def variant_has_addendum(path: Path) -> bool:
    try:
        return "\n## Addendum" in path.read_text()
    except Exception:
        return False


def batch_started_at(batch_dir: Path) -> str:
    checkpoint = batch_dir / "checkpoint.json"
    if not checkpoint.exists():
        return ""
    try:
        return json.loads(checkpoint.read_text()).get("started_at", "")
    except Exception:
        return ""


def transition_for_iter(iter_dir: Path) -> dict:
    path = iter_dir / "transition_score.json"
    if not path.exists():
        return {"score": 0.0, "verdict": "unknown"}
    try:
        rec = json.loads(path.read_text())
        return {
            "score": float(rec.get("score", 0.0) or 0.0),
            "verdict": rec.get("verdict", "unknown"),
            "previous_key": rec.get("previous_key"),
            "next_key": rec.get("next_key"),
        }
    except Exception:
        return {"score": 0.0, "verdict": "unreadable"}


def find_seed_variant(target: str, *, current_batch_id: str | None = None) -> dict | None:
    """Return metadata for the best prior prompt variant for this target.

    Ranking favors accepted variants, then variants that contain learned
    addenda, then higher iteration count, then recency. Failed addenda are only
    reused target-locally; global prompt promotion remains handled separately by
    coalesce/promote.
    """
    want = normalize_target(target)
    candidates: list[dict] = []
    if not BATCHES.exists():
        return None

    for target_json in BATCHES.glob("*/targets/target_*/target.json"):
        batch_dir = target_json.parents[2]
        batch_id = batch_dir.name
        if current_batch_id and batch_id == current_batch_id:
            continue
        batch_prefix = os.environ.get("EVOLUTION_MEMORY_BATCH_PREFIX")
        if batch_prefix and not batch_id.startswith(batch_prefix):
            continue
        try:
            tmeta = json.loads(target_json.read_text())
        except Exception:
            continue
        if normalize_target(tmeta.get("target", "")) != want:
            continue

        target_dir = target_json.parent
        metrics_path = target_dir / "target_metrics.json"
        if not metrics_path.exists():
            continue
        try:
            metrics = json.loads(metrics_path.read_text())
        except Exception:
            continue
        iter_dir = iter_dir_for_metrics(target_dir, metrics)
        if not iter_dir:
            continue
        variant = iter_dir / "variant.md"
        if not variant.exists():
            continue

        n_iters = int(metrics.get("n_iterations", 0) or 0)
        has_addendum = variant_has_addendum(variant)
        if not has_addendum:
            continue
        accepted = bool(metrics.get("accepted"))
        transition = transition_for_iter(iter_dir)
        candidates.append({
            "batch_id": batch_id,
            "target_dir": str(target_dir),
            "variant_path": str(variant),
            "selected_iter": iter_dir.name,
            "accepted": accepted,
            "failure_reason": metrics.get("failure_reason"),
            "n_iterations": n_iters,
            "has_addendum": has_addendum,
            "transition": transition,
            "started_at": batch_started_at(batch_dir),
            "rank": [
                1 if accepted else 0,
                transition["score"],
                n_iters,
                batch_started_at(batch_dir),
            ],
        })

    if not candidates:
        return None
    candidates.sort(key=lambda c: c["rank"], reverse=True)
    winner = candidates[0]
    winner.pop("rank", None)
    winner["selected_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return winner


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--current-batch-id", default=None)
    args = ap.parse_args()
    seed = find_seed_variant(args.target, current_batch_id=args.current_batch_id)
    print(json.dumps(seed or {}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
