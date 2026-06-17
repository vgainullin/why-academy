#!/usr/bin/env python3
"""Build machine-checkable capability proposals from verifier failures.

This is the bridge between "the prompt keeps failing on rule X" and "try a
formal rule/validator extension". It never edits live validators. It writes
proposal packages under derivations/_evolutions/capabilities/ that can later be
fed to capability_synthesize.py and capability_eval.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
BATCHES = ROOT / "_evolutions" / "batches"
CAPABILITIES = ROOT / "_evolutions" / "capabilities"
TEMPLATE = ROOT / "prompts" / "capability_synthesis.md"


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}


def slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower() or "unknown"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def select_batches(batch_ids: list[str], batch_prefix: str | None) -> list[Path]:
    if batch_ids:
        return [BATCHES / bid for bid in batch_ids]
    if batch_prefix:
        return sorted(p for p in BATCHES.glob(f"{batch_prefix}*") if p.is_dir())
    return sorted(p for p in BATCHES.iterdir() if p.is_dir())


def edge_nodes(problem: dict[str, Any], edge: dict[str, Any]) -> tuple[str | None, str | None]:
    nodes = {n.get("id"): n.get("sympy_srepr") for n in problem.get("nodes", [])}
    return nodes.get(edge.get("from")), nodes.get(edge.get("to"))


def problem_edge_args(problem: dict[str, Any], edge: dict[str, Any]) -> dict[str, Any]:
    for candidate in problem.get("edges", []):
        if (
            candidate.get("from") == edge.get("from")
            and candidate.get("to") == edge.get("to")
            and candidate.get("rule") == edge.get("rule")
        ):
            return candidate.get("rule_args") or {}
    return {}


def collect_evidence(batch_dirs: list[Path]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for batch_dir in batch_dirs:
        checkpoint = read_json(batch_dir / "checkpoint.json") or {}
        batch_id = checkpoint.get("batch_id", batch_dir.name)
        for target_dir in sorted((batch_dir / "targets").glob("target_*")):
            target = (read_json(target_dir / "target.json") or {}).get("target", "")
            for iter_dir in sorted(target_dir.glob("iter_*")):
                diagnosis = read_json(iter_dir / "failure_diagnosis.json") or {}
                if diagnosis.get("gate") != "verify":
                    continue
                problem = read_json(iter_dir / "problem.json") or {}
                verifier = read_json(iter_dir / "problem.verifier.json") or {}
                for edge in verifier.get("edge_results", []):
                    if edge.get("status") not in ("FAIL", "ERROR"):
                        continue
                    rule = edge.get("rule")
                    if not rule:
                        continue
                    from_srepr, to_srepr = edge_nodes(problem, edge)
                    grouped[rule].append({
                        "batch_id": batch_id,
                        "target": target,
                        "target_dir": rel(target_dir),
                        "iter": iter_dir.name,
                        "problem_id": problem.get("id") or verifier.get("problem_id"),
                        "problem_path": rel(iter_dir / "problem.json"),
                        "verifier_path": rel(iter_dir / "problem.verifier.json"),
                        "diagnosis_path": rel(iter_dir / "failure_diagnosis.json"),
                        "diagnosis": {
                            "failure_class": diagnosis.get("failure_class"),
                            "primary_rule": diagnosis.get("rule"),
                            "details": diagnosis.get("details"),
                        },
                        "edge": {
                            "from": edge.get("from"),
                            "to": edge.get("to"),
                            "rule": edge.get("rule"),
                            "status": edge.get("status"),
                            "reason": edge.get("reason"),
                            "rule_args": problem_edge_args(problem, edge),
                            "from_srepr": from_srepr,
                            "to_srepr": to_srepr,
                        },
                    })
    return grouped


def summarize(rule: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    batches = sorted({e["batch_id"] for e in evidence})
    problems = sorted({e.get("problem_id") for e in evidence if e.get("problem_id")})
    targets = sorted({e.get("target") for e in evidence if e.get("target")})
    reasons = Counter((e.get("edge") or {}).get("reason", "") for e in evidence)
    validator_path = ROOT / "validators" / f"{rule}.py"
    return {
        "rule_name": rule,
        "frequency": len(evidence),
        "breadth_problems": len(problems),
        "breadth_targets": len(targets),
        "batches": batches,
        "n_batches": len(batches),
        "validator_exists": validator_path.exists(),
        "validator_path": rel(validator_path),
        "top_reasons": [{"reason": reason, "count": count} for reason, count in reasons.most_common(5)],
    }


def proposal_payload(rule: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize(rule, evidence)
    kind = "STRENGTHEN_VALIDATOR" if summary["validator_exists"] else "NEW_VALIDATOR"
    return {
        "schema_version": "capability_proposal.v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "kind": kind,
        **summary,
        "status": "proposal_ready_for_synthesis",
        "safety_invariants": [
            "candidate validator must validate exactly one local edge",
            "candidate validator must not inspect target text or whole-graph acceptance",
            "candidate validator must not weaken target_check or judge gates",
            "candidate validator must include positive and negative tests",
            "promotion requires isolated candidate tests plus closure and holdout checks",
        ],
        "contract": {
            "candidate_validator": "candidate/validator.py",
            "candidate_tests": "candidate/tests.json",
            "required_exports": ["RULE_NAME", "validate(from_expr, to_expr, args)"],
            "allowed_test_expected_values": ["PASS", "FAIL"],
            "live_validator_destination": f"derivations/validators/{rule}.py",
            "promotion_mode": "explicit_only_after_closure",
        },
        "evidence": evidence,
    }


def markdown(payload: dict[str, Any]) -> str:
    rule = payload["rule_name"]
    lines = [
        f"# Capability Proposal: `{rule}`",
        "",
        f"- Kind: `{payload['kind']}`",
        f"- Frequency: {payload['frequency']}",
        f"- Problems: {payload['breadth_problems']}",
        f"- Batches: {payload['n_batches']} ({', '.join(payload['batches'])})",
        f"- Existing validator: {payload['validator_exists']}",
        f"- Destination: `{payload['contract']['live_validator_destination']}`",
        "",
        "## Why This Exists",
        "",
        "The verifier repeatedly rejected this rule. This package is evidence for a possible formal capability gap; it is not approval to change the live validator library.",
        "",
        "## Top Reasons",
        "",
    ]
    for row in payload["top_reasons"]:
        lines.append(f"- {row['count']}x: {row['reason']}")
    lines += [
        "",
        "## Evidence",
        "",
    ]
    for ev in payload["evidence"][:12]:
        edge = ev["edge"]
        lines += [
            f"- `{ev['batch_id']}` `{ev['problem_id']}` `{ev['iter']}` `{edge['from']}->{edge['to']}`",
            f"  - from: `{edge.get('from_srepr')}`",
            f"  - to: `{edge.get('to_srepr')}`",
            f"  - rule_args: `{json.dumps(edge.get('rule_args') or {}, sort_keys=True)}`",
            f"  - reason: {edge.get('reason')}",
        ]
    if len(payload["evidence"]) > 12:
        lines.append(f"- ... {len(payload['evidence']) - 12} more evidence rows in `proposal.json`")
    lines += [
        "",
        "## Promotion Gates",
        "",
        "- `candidate/validator.py` passes static safety checks.",
        "- `candidate/tests.json` has positive and negative tests and all pass under `scripts/capability_eval.sh`.",
        "- Closure test improves this rule's historical failure cluster.",
        "- Holdout does not regress.",
        "- Target-completion gate remains independent and cannot be changed by this proposal.",
        "",
        "## Next Command",
        "",
        "```bash",
        "scripts/capability_synthesize.sh " + rel(Path(payload["_proposal_dir"])),
        "scripts/capability_eval.sh " + rel(Path(payload["_proposal_dir"])),
        "```",
    ]
    return "\n".join(lines) + "\n"


def render_synthesis_prompt(payload: dict[str, Any]) -> str:
    template = TEMPLATE.read_text()
    public_payload = {k: v for k, v in payload.items() if not k.startswith("_")}
    return template.replace("<<CAPABILITY_PROPOSAL_JSON>>", json.dumps(public_payload, indent=2))


def write_package(payload: dict[str, Any], out_root: Path, overwrite: bool = False) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    proposal_dir = out_root / f"{stamp}_{slug(payload['rule_name'])}"
    if proposal_dir.exists() and not overwrite:
        raise FileExistsError(proposal_dir)
    proposal_dir.mkdir(parents=True, exist_ok=True)
    (proposal_dir / "candidate").mkdir(exist_ok=True)
    payload["_proposal_dir"] = str(proposal_dir)
    (proposal_dir / "proposal.json").write_text(
        json.dumps({k: v for k, v in payload.items() if not k.startswith("_")}, indent=2) + "\n"
    )
    (proposal_dir / "proposal.md").write_text(markdown(payload))
    (proposal_dir / "synthesis_prompt.md").write_text(render_synthesis_prompt(payload))
    (proposal_dir / "candidate" / "README.md").write_text(
        "Generated candidates go here. Do not copy this directory into derivations/validators/ without closure and holdout gates.\n"
    )
    return proposal_dir


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-id", action="append", default=[], help="specific batch id; repeatable")
    ap.add_argument("--batch-prefix", default=None, help="scan batches whose id starts with this prefix")
    ap.add_argument("--out-root", default=str(CAPABILITIES))
    ap.add_argument("--min-frequency", type=int, default=3)
    ap.add_argument("--min-batches", type=int, default=1)
    ap.add_argument("--max-proposals", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    batch_dirs = [p for p in select_batches(args.batch_id, args.batch_prefix) if p.exists()]
    if not batch_dirs:
        print("[capability] no matching batches", file=sys.stderr)
        return 1
    grouped = collect_evidence(batch_dirs)
    candidates = []
    for rule, evidence in grouped.items():
        payload = proposal_payload(rule, evidence)
        if payload["frequency"] < args.min_frequency:
            continue
        if payload["n_batches"] < args.min_batches:
            continue
        candidates.append(payload)
    candidates.sort(key=lambda p: (p["frequency"], p["breadth_problems"], p["n_batches"]), reverse=True)
    candidates = candidates[: args.max_proposals]

    out_root = Path(args.out_root)
    written = []
    for payload in candidates:
        if args.dry_run:
            print(json.dumps({k: payload[k] for k in ("rule_name", "kind", "frequency", "breadth_problems", "n_batches")}))
        else:
            proposal_dir = write_package(payload, out_root)
            written.append(str(proposal_dir))
            print(f"[capability] wrote {proposal_dir}")

    index = {
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "batch_dirs": [rel(p) for p in batch_dirs],
        "min_frequency": args.min_frequency,
        "min_batches": args.min_batches,
        "n_candidates": len(candidates),
        "written": written,
    }
    if not args.dry_run:
        out_root.mkdir(parents=True, exist_ok=True)
        (out_root / "latest_index.json").write_text(json.dumps(index, indent=2) + "\n")
    if not candidates:
        print("[capability] no rule clusters met thresholds", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
