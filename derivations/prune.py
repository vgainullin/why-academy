#!/usr/bin/env python3
"""Apply retention policy to derivations/_evolutions/batches/.

Each batch is either kept-in-full (latest N OR best M by composite_score) or
pruned-to-summary (iter_* directories removed, summary artifacts retained:
batch_metrics.json, coalesce_report.md, promote_proposal.md, decision.md if any,
checkpoint.json, target_metrics.json files).

Policy lives at derivations/_evolutions/retention.json (auto-created with defaults
if missing). Run with --dry-run to preview.
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path

DEFAULT_RETENTION = {
    "keep_latest_n": 5,
    "keep_best_by_score": 3,
    "score_metric": "composite_score",
    "dry_run": False,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent
    evo_dir = root / "_evolutions" / "batches"
    policy_path = root / "_evolutions" / "retention.json"

    if not policy_path.exists():
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(json.dumps(DEFAULT_RETENTION, indent=2))
        print(f"[prune] wrote default retention policy to {policy_path}")

    policy = {**DEFAULT_RETENTION, **json.loads(policy_path.read_text())}
    if args.dry_run:
        policy["dry_run"] = True

    if not evo_dir.exists():
        print("[prune] no batches dir; nothing to do")
        return 0

    batches = []
    for d in sorted(evo_dir.glob("*")):
        if not d.is_dir():
            continue
        mp = d / "batch_metrics.json"
        score = 0.0
        if mp.exists():
            try:
                m = json.loads(mp.read_text())
                score = float(m.get(policy["score_metric"], 0.0))
            except Exception:
                pass
        batches.append({"path": d, "name": d.name, "score": score, "mtime": d.stat().st_mtime})

    if not batches:
        print("[prune] no batches to consider")
        return 0

    latest = sorted(batches, key=lambda b: -b["mtime"])[:policy["keep_latest_n"]]
    best = sorted(batches, key=lambda b: -b["score"])[:policy["keep_best_by_score"]]

    retain_paths = {b["path"] for b in latest} | {b["path"] for b in best}
    to_prune = [b for b in batches if b["path"] not in retain_paths]

    print(f"[prune] policy keep_latest_n={policy['keep_latest_n']}, "
          f"keep_best_by_score={policy['keep_best_by_score']} on '{policy['score_metric']}'")
    print(f"[prune] total batches: {len(batches)}; retain: {len(retain_paths)}; prune: {len(to_prune)}")
    print(f"[prune] dry_run: {policy['dry_run']}")

    n_removed = 0
    bytes_removed = 0
    for b in to_prune:
        targets_dir = b["path"] / "targets"
        if not targets_dir.exists():
            print(f"[prune]   {b['name']}: no targets/ dir, skipping")
            continue
        iter_dirs = list(targets_dir.glob("*/iter_*"))
        sz = 0
        for it in iter_dirs:
            try:
                for f in it.rglob("*"):
                    if f.is_file():
                        sz += f.stat().st_size
            except Exception:
                pass
        print(f"[prune]   {b['name']}: {len(iter_dirs)} iter dir(s), "
              f"{sz / 1024:.0f} KiB (score={b['score']:.2f})")
        if not policy["dry_run"]:
            for it in iter_dirs:
                shutil.rmtree(it, ignore_errors=True)
            n_removed += len(iter_dirs)
            bytes_removed += sz

    print(f"[prune] done. removed {n_removed} iter dirs, {bytes_removed / 1024:.0f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
