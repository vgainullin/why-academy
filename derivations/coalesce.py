#!/usr/bin/env python3
"""Batch-level coalescing: read accepted variants across a batch, identify
addenda patterns, and produce a conservative promote_proposal.

Output (all written into the batch directory):
  batch_metrics.json      aggregate stats: rates, consistency, composite_score
  coalesce_report.md      every addendum cluster, with representative + frequency
  promote_proposal.md     the conservative-threshold subset, ready for human review

No LLM call. Clustering is deterministic on the normalized addendum header. A
human reviewer can hand-edit the promote_proposal before invoking promote_prompt.sh.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CANONICAL = ROOT / "prompts" / "generate_derivation.md"

ADDENDUM_BLOCK_RE = re.compile(r"(?ms)^## Addendum[^\n]*$.*?(?=^## Addendum|\Z)")
ADDENDUM_HEADER_RE = re.compile(r"^## Addendum.*?:\s*(.+?)$", re.MULTILINE)


def extract_addenda(variant_text: str, canonical_text: str) -> list[dict]:
    """Return list of {header, body, full_text} for each addendum block beyond canonical."""
    # Strip canonical prefix (variant should be canonical + addenda)
    if variant_text.startswith(canonical_text):
        tail = variant_text[len(canonical_text):]
    else:
        tail = variant_text
    out = []
    for m in ADDENDUM_BLOCK_RE.finditer(tail):
        block = m.group(0).strip()
        header_m = ADDENDUM_HEADER_RE.match(block)
        header = header_m.group(1).strip() if header_m else "(unnamed)"
        # Body = everything after the header line
        first_newline = block.find("\n")
        body = block[first_newline + 1:].strip() if first_newline > -1 else ""
        out.append({"header": header, "body": body, "full_text": block})
    return out


def normalize_header(s: str) -> str:
    s = re.sub(r"\(iteration\s+\d+\)", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s


def read_transition(iter_dir: Path) -> dict:
    path = iter_dir / "transition_score.json"
    if not path.exists():
        return {"verdict": "unknown", "score": 0.0}
    try:
        rec = json.loads(path.read_text())
        return {
            "verdict": rec.get("verdict", "unknown"),
            "score": rec.get("score", 0.0),
            "previous_key": rec.get("previous_key"),
            "next_key": rec.get("next_key"),
        }
    except Exception:
        return {"verdict": "unreadable", "score": 0.0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_dir", help="derivations/_evolutions/batches/<batch_id>/")
    ap.add_argument("--threshold-frac", type=float, default=0.3,
                    help="addendum cluster must affect >= this fraction of ACCEPTED targets to be eligible to promote")
    args = ap.parse_args()

    batch_dir = Path(args.batch_dir).resolve()
    if not batch_dir.is_dir():
        print(f"[coalesce] no such batch dir: {batch_dir}", file=sys.stderr)
        return 1

    canonical_text = CANONICAL.read_text()
    targets = sorted((batch_dir / "targets").glob("target_*"))

    n_total = len(targets)
    n_accepted = 0
    n_first_try = 0
    iters_to_accept: list[int] = []
    addenda_by_accepted_target: dict[int, list[dict]] = {}
    addenda_by_any_target: dict[int, list[dict]] = {}
    target_outcomes: dict[int, dict] = {}
    failure_reasons: dict[str, int] = {}

    for tdir in targets:
        mp = tdir / "target_metrics.json"
        if not mp.exists():
            continue
        m = json.loads(mp.read_text())
        ti = m["target_index"]
        target_outcomes[ti] = {
            "accepted": bool(m.get("accepted")),
            "failure_reason": m.get("failure_reason"),
            "n_iterations": m.get("n_iterations"),
        }
        for iter_dir in sorted(tdir.glob("iter_*")):
            variant_path = iter_dir / "variant.md"
            if variant_path.exists():
                transition = read_transition(iter_dir)
                for addendum in extract_addenda(variant_path.read_text(), canonical_text):
                    addendum = {**addendum, "iter": iter_dir.name, "transition": transition}
                    addenda_by_any_target.setdefault(ti, []).append(addendum)
        if m["accepted"]:
            n_accepted += 1
            iters_to_accept.append(m["accepted_at_iter"])
            if m["first_try_pass"]:
                n_first_try += 1
            iter_dir = tdir / f"iter_{m['accepted_at_iter']:02d}"
            variant_path = iter_dir / "variant.md"
            if variant_path.exists():
                addenda_by_accepted_target[ti] = extract_addenda(variant_path.read_text(), canonical_text)
            else:
                addenda_by_accepted_target[ti] = []
        else:
            reason = m.get("failure_reason") or "unknown"
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1

    first_try_pass_rate = n_first_try / n_total if n_total else 0.0
    convergence_rate = n_accepted / n_total if n_total else 0.0
    avg_iters_to_accept = sum(iters_to_accept) / len(iters_to_accept) if iters_to_accept else 0.0

    accepted_cluster: dict[str, list[tuple[int, dict]]] = {}
    for ti, alist in addenda_by_accepted_target.items():
        for a in alist:
            key = normalize_header(a["header"])
            accepted_cluster.setdefault(key, []).append((ti, a))

    all_cluster: dict[str, list[tuple[int, dict]]] = {}
    for ti, alist in addenda_by_any_target.items():
        seen_in_iter: set[tuple[str, str]] = set()
        for a in alist:
            key = normalize_header(a["header"])
            dedupe_key = (key, a.get("iter", ""))
            if dedupe_key in seen_in_iter:
                continue
            seen_in_iter.add(dedupe_key)
            all_cluster.setdefault(key, []).append((ti, a))

    transition_cluster: dict[str, list[tuple[int, dict]]] = {}
    for key, entries in all_cluster.items():
        for ti, a in entries:
            verdict = (a.get("transition") or {}).get("verdict", "unknown")
            transition_cluster.setdefault(f"{key}::{verdict}", []).append((ti, a))

    if n_accepted:
        total_addenda = sum(len(v) for v in accepted_cluster.values())
        consistency = 1.0 - (len(accepted_cluster) / max(total_addenda, 1)) if total_addenda else 1.0
        consistency = max(0.0, min(1.0, consistency))
    else:
        consistency = 0.0

    composite = (first_try_pass_rate * 0.4) + (convergence_rate * 0.4) + (consistency * 0.2)

    metrics = {
        "batch_id": batch_dir.name,
        "n_targets": n_total,
        "n_accepted": n_accepted,
        "first_try_pass_rate": first_try_pass_rate,
        "convergence_rate": convergence_rate,
        "avg_iters_to_accept": avg_iters_to_accept,
        "n_unique_addenda_clusters": len(accepted_cluster),
        "n_all_addenda_clusters": len(all_cluster),
        "n_transition_addenda_clusters": len(transition_cluster),
        "consistency_score": consistency,
        "composite_score": composite,
        "failure_reasons": failure_reasons,
    }
    (batch_dir / "batch_metrics.json").write_text(json.dumps(metrics, indent=2))

    threshold = max(1, int(args.threshold_frac * n_accepted)) if n_accepted else 1
    accepted_cluster_sorted = sorted(
        accepted_cluster.items(),
        key=lambda kv: -len({t for t, _ in kv[1]}),
    )
    all_cluster_sorted = sorted(
        all_cluster.items(),
        key=lambda kv: -len({t for t, _ in kv[1]}),
    )
    promote: list = []
    watch: list = []
    for key, entries in accepted_cluster_sorted:
        n_t = len({t for t, _ in entries})
        (promote if n_t >= threshold else watch).append((key, entries, n_t))

    # coalesce_report.md
    report = [
        f"# Batch coalesce report: {batch_dir.name}",
        "",
        f"- Targets: {n_total}",
        f"- Accepted: {n_accepted}/{n_total} ({convergence_rate * 100:.0f}%)",
        f"- First-try pass: {n_first_try}/{n_total} ({first_try_pass_rate * 100:.0f}%)",
        f"- Avg iterations to accept (accepted only): {avg_iters_to_accept:.1f}",
        f"- Accepted addendum clusters: {len(accepted_cluster)}",
        f"- All addendum clusters: {len(all_cluster)}",
        f"- Transition addendum clusters: {len(transition_cluster)}",
        f"- Consistency score: {consistency:.2f}",
        f"- Composite score: {composite:.2f}",
        "",
    ]
    if failure_reasons:
        report.append("Failure reasons (non-accepted targets):")
        for r, c in sorted(failure_reasons.items(), key=lambda kv: -kv[1]):
            report.append(f"- {r}: {c}")
        report.append("")
    report.append("## All addendum clusters")
    report.append("")
    for key, entries in all_cluster_sorted:
        n_t = len({t for t, _ in entries})
        rep = entries[0][1]
        accepted_targets = sorted({t for t, _ in entries if target_outcomes.get(t, {}).get("accepted")})
        failed_targets = sorted({t for t, _ in entries if not target_outcomes.get(t, {}).get("accepted")})
        fail_counts: dict[str, int] = {}
        for t, _ in entries:
            reason = target_outcomes.get(t, {}).get("failure_reason")
            if reason:
                fail_counts[reason] = fail_counts.get(reason, 0) + 1
        report.append(f"### `{key}` ({n_t} target{'s' if n_t != 1 else ''}; {len(entries)} total occurrences)")
        report.append(f"Representative header: {rep['header']}")
        report.append(f"Accepted targets: {len(accepted_targets)}")
        report.append(f"Failed targets: {len(failed_targets)}")
        transition_counts: dict[str, int] = {}
        transition_scores = []
        for _, a in entries:
            tr = a.get("transition") or {}
            verdict = tr.get("verdict", "unknown")
            transition_counts[verdict] = transition_counts.get(verdict, 0) + 1
            transition_scores.append(float(tr.get("score", 0.0) or 0.0))
        if transition_counts:
            report.append("Transition verdicts:")
            for verdict, count in sorted(transition_counts.items(), key=lambda kv: (-kv[1], kv[0])):
                report.append(f"- {verdict}: {count}")
            avg_score = sum(transition_scores) / len(transition_scores)
            report.append(f"Average transition score: {avg_score:.2f}")
        if fail_counts:
            report.append("Failure reasons seen:")
            for reason, count in sorted(fail_counts.items(), key=lambda kv: (-kv[1], kv[0])):
                report.append(f"- {reason}: {count}")
        report.append("")
        report.append("```")
        body = rep["body"]
        report.append(body[:400] + ("..." if len(body) > 400 else ""))
        report.append("```")
        report.append("")
    (batch_dir / "coalesce_report.md").write_text("\n".join(report))

    # promote_proposal.md
    proposal = [
        f"# Promote Proposal: {batch_dir.name}",
        "",
        f"Threshold: cluster must affect >= {threshold} of {n_accepted} accepted targets.",
        f"Composite score: {composite:.2f}",
        "",
    ]
    if not promote:
        proposal.append("**No conservative-eligible promotions in this batch.**")
        proposal.append("")
        if watch:
            proposal.append("Below threshold (watch list, not promoted):")
            for key, entries, n_t in watch:
                proposal.append(f"- `{key}` — {n_t} target{'s' if n_t != 1 else ''}")
    else:
        proposal.append("## Promote (conservative)")
        proposal.append("")
        proposal.append("The following addendum block(s) will be appended to `derivations/prompts/generate_derivation.md` when this proposal is approved via `scripts/promote_prompt.sh`. Edit this file by hand to refine or remove entries before approving.")
        proposal.append("")
        for key, entries, n_t in promote:
            rep = entries[0][1]
            proposal.append(f"### Cluster `{key}` ({n_t} of {n_accepted} accepted targets)")
            proposal.append("")
            proposal.append("```markdown")
            proposal.append(rep["full_text"])
            proposal.append("```")
            proposal.append("")
        if watch:
            proposal.append("## Watch (below threshold; not promoted this round)")
            proposal.append("")
            for key, entries, n_t in watch:
                proposal.append(f"- `{key}` — {n_t} target{'s' if n_t != 1 else ''}")
    (batch_dir / "promote_proposal.md").write_text("\n".join(proposal))

    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
