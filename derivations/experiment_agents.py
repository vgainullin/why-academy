#!/usr/bin/env python3
"""Render reusable headless-agent gate prompts for derivation experiments."""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import hashlib
import json
import subprocess
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
ROLE_DIR = ROOT / "experiment_agent_roles"
MANIFEST_PATH = ROLE_DIR / "manifest.json"
DEFAULT_OUT_ROOT = ROOT / "_evolutions" / "experiment_agents"
PLACEHOLDER_RE = re.compile(r"{{[A-Z0-9_]+}}")
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)

HEADLESS_CONTRACT = """\
## Headless Contract

- Do not request permissions or approvals.
- Do not run commands that require escalation or interactive confirmation.
- If a needed command would require approval, skip it and report the exact
  command, why it was needed, and what evidence is missing.
- Do not commit unless explicitly asked.

"""

AB_ANALYSIS_TOP_LEVEL_FILES = (
    "checkpoint.json",
    "batch_metrics.json",
    "coalesce_report.md",
    "promote_proposal.md",
)

AB_ANALYSIS_TARGET_FILES = (
    "target.json",
    "target_metrics.json",
    "ACCEPTED.txt",
    "FAILED.txt",
)

AB_ANALYSIS_ITER_FILES = (
    "status.txt",
    "failure_diagnosis.json",
    "rule_plan.raw.txt",
    "rule_plan.json",
    "rule_plan_parse_error.json",
    "problem.rule_executor.json",
    "problem.raw.json",
    "problem.raw.verifier.json",
    "problem.raw.substitution_check.json",
    "problem.verifier.json",
    "problem.judge.json",
    "problem.target_check.json",
    "problem.normalizer.json",
    "problem.normalization_bridge.json",
    "problem.normalization_bridge_candidate.json",
    "normalization_bridge_error.json",
    "problem.substitution_check.json",
    "rule_executor_error.json",
    "transition_score.json",
)

DEFAULT_AB_ANALYSIS_HYPOTHESIS = (
    "treatment materially improves derivation quality or safety relative to "
    "the control batch without invalidating production gates"
)

DEFAULT_NEXT_STEP_HYPOTHESIS = (
    "derive the next highest-leverage hypothesis and test plan from the supplied "
    "experiment analysis, without manually selecting an implementation task"
)


@dataclass(frozen=True)
class RenderContext:
    experiment_id: str
    hypothesis: str
    repo_root: Path
    worktree: str
    prototype_worktree: str
    evidence_paths: list[str]
    report_path: str = ""


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text())


def role_ids(manifest: dict[str, Any]) -> list[str]:
    return list(manifest.get("roles", {}))


def expand_roles(manifest: dict[str, Any], requested: list[str] | None) -> list[str]:
    groups = manifest.get("groups", {})
    roles = manifest.get("roles", {})
    if not requested:
        requested = ["prebuild"]

    expanded: list[str] = []
    for item in requested:
        names = groups.get(item, [item])
        for name in names:
            if name not in roles:
                raise ValueError(f"unknown experiment agent role or group: {name}")
            if name not in expanded:
                expanded.append(name)
    return expanded


def evidence_block(paths: list[str]) -> str:
    if not paths:
        return "- No evidence paths supplied."
    return "\n".join(f"- `{path}`" for path in paths)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(path)


def resolve_project_path(path: str | Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p


def render_template(text: str, ctx: RenderContext) -> str:
    report_path = ctx.report_path or f"derivations/experiments/{ctx.experiment_id}.md"
    values = {
        "EXPERIMENT_ID": ctx.experiment_id,
        "HYPOTHESIS": ctx.hypothesis,
        "REPO_ROOT": str(ctx.repo_root),
        "WORKTREE": ctx.worktree,
        "PROTOTYPE_WORKTREE": ctx.prototype_worktree,
        "EVIDENCE_PATHS": evidence_block(ctx.evidence_paths),
        "REPORT_PATH": report_path,
    }
    out = text
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", value)
    unresolved = sorted(set(PLACEHOLDER_RE.findall(out)))
    if unresolved:
        raise ValueError(f"unresolved placeholders: {unresolved}")
    return HEADLESS_CONTRACT + out


def render_role(manifest: dict[str, Any], role_id: str, ctx: RenderContext) -> tuple[str, dict[str, Any]]:
    role = manifest["roles"][role_id]
    template_path = ROLE_DIR / role["template"]
    prompt = render_template(template_path.read_text(), ctx)
    metadata = {
        "role_id": role_id,
        "agent_type": role.get("agent_type"),
        "phase": role.get("phase"),
        "expected_output": role.get("output"),
        "template": str(template_path.relative_to(PROJECT_ROOT)),
    }
    return prompt, metadata


def write_packet(ctx: RenderContext, roles: list[str], out_dir: Path) -> dict[str, Any]:
    manifest = load_manifest()
    prompts_dir = out_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    rendered_roles = []
    for role_id in roles:
        prompt, metadata = render_role(manifest, role_id, ctx)
        prompt_path = prompts_dir / f"{role_id}.md"
        prompt_path.write_text(prompt)
        rendered_roles.append({
            **metadata,
            "prompt_path": str(prompt_path),
            "prompt_sha256": sha256_text(prompt),
            "prompt_bytes": len(prompt.encode("utf-8")),
        })

    packet = {
        "schema_version": "experiment_agent_packet.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment_id": ctx.experiment_id,
        "hypothesis": ctx.hypothesis,
        "repo_root": str(ctx.repo_root),
        "worktree": ctx.worktree,
        "prototype_worktree": ctx.prototype_worktree,
        "report_path": ctx.report_path or f"derivations/experiments/{ctx.experiment_id}.md",
        "evidence_paths": ctx.evidence_paths,
        "evidence_sha256": sha256_text("\n".join(ctx.evidence_paths)),
        "roles": rendered_roles,
    }
    (out_dir / "packet.json").write_text(json.dumps(packet, indent=2) + "\n")
    return packet


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def add_existing_file(paths: list[str], path: Path) -> None:
    if path.exists() and path.is_file():
        paths.append(display_path(path))


def collect_batch_evidence(batch_dir: Path) -> tuple[list[str], list[str]]:
    paths: list[str] = []
    issues: list[str] = []
    if not batch_dir.is_dir():
        return [], [f"missing batch dir: {batch_dir}"]

    paths.append(display_path(batch_dir))
    for name in AB_ANALYSIS_TOP_LEVEL_FILES:
        path = batch_dir / name
        if name in ("checkpoint.json", "batch_metrics.json") and not path.is_file():
            issues.append(f"missing required batch artifact: {path}")
        add_existing_file(paths, path)

    targets_dir = batch_dir / "targets"
    target_dirs = sorted(targets_dir.glob("target_*")) if targets_dir.is_dir() else []
    if not target_dirs:
        issues.append(f"missing target dirs under: {targets_dir}")
    for target_dir in target_dirs:
        paths.append(display_path(target_dir))
        for name in AB_ANALYSIS_TARGET_FILES:
            add_existing_file(paths, target_dir / name)
        for iter_dir in sorted(target_dir.glob("iter_*")):
            if not iter_dir.is_dir():
                continue
            paths.append(display_path(iter_dir))
            for name in AB_ANALYSIS_ITER_FILES:
                add_existing_file(paths, iter_dir / name)
    return paths, issues


def infer_experiment_id(control_dir: Path, treatment_dir: Path, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    for path in (
        treatment_dir / "ab_comparison.json",
        treatment_dir / "batch_metrics.json",
        control_dir / "batch_metrics.json",
        treatment_dir / "checkpoint.json",
        control_dir / "checkpoint.json",
    ):
        value = read_json_object(path).get("experiment_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"{control_dir.name}_vs_{treatment_dir.name}"


def collect_ab_analysis_evidence(
    control_dir: Path,
    treatment_dir: Path,
    *,
    require_comparison: bool = True,
) -> tuple[list[str], list[str]]:
    evidence: list[str] = []
    issues: list[str] = []
    control_paths, control_issues = collect_batch_evidence(control_dir)
    treatment_paths, treatment_issues = collect_batch_evidence(treatment_dir)
    evidence.extend(control_paths)
    evidence.extend(treatment_paths)
    issues.extend(control_issues)
    issues.extend(treatment_issues)

    comparison = treatment_dir / "ab_comparison.json"
    if comparison.is_file():
        evidence.insert(0, display_path(comparison))
        add_existing_file(evidence, treatment_dir / "ab_comparison.md")
    elif require_comparison:
        issues.append(f"missing required A/B comparison artifact: {comparison}")
    return list(dict.fromkeys(evidence)), issues


def write_ab_analysis_packet(
    *,
    control_dir: Path,
    treatment_dir: Path,
    experiment_id: str | None,
    hypothesis: str,
    worktree: str,
    prototype_worktree: str,
    report_path: str,
    out_dir: Path,
    require_comparison: bool = True,
) -> tuple[dict[str, Any] | None, list[str]]:
    evidence, issues = collect_ab_analysis_evidence(
        control_dir,
        treatment_dir,
        require_comparison=require_comparison,
    )
    if issues:
        return None, issues
    resolved_experiment_id = infer_experiment_id(control_dir, treatment_dir, experiment_id)
    ctx = RenderContext(
        experiment_id=resolved_experiment_id,
        hypothesis=hypothesis,
        repo_root=PROJECT_ROOT,
        worktree=worktree,
        prototype_worktree=prototype_worktree,
        evidence_paths=evidence,
        report_path=report_path,
    )
    return write_packet(ctx, ["ab_analysis"], out_dir), []


def collect_existing_evidence(paths: list[str]) -> tuple[list[str], list[str]]:
    evidence: list[str] = []
    issues: list[str] = []
    for raw in paths:
        path = resolve_project_path(raw)
        if not path.exists():
            issues.append(f"missing evidence artifact: {path}")
            continue
        evidence.append(display_path(path))
    return list(dict.fromkeys(evidence)), issues


def infer_next_step_experiment_id(analysis_paths: list[str], explicit: str | None = None) -> str:
    if explicit:
        return explicit
    for raw in analysis_paths:
        path = Path(raw)
        stem = path.stem
        if stem and stem not in {"ab_analysis_result", "analysis_result", "result"}:
            return f"{stem}_next_step"
    return "next_step_derivation"


def write_next_step_packet(
    *,
    analysis_paths: list[str],
    extra_evidence: list[str],
    experiment_id: str | None,
    hypothesis: str,
    worktree: str,
    prototype_worktree: str,
    report_path: str,
    out_dir: Path,
) -> tuple[dict[str, Any] | None, list[str]]:
    evidence, issues = collect_existing_evidence([*analysis_paths, *extra_evidence])
    if issues:
        return None, issues
    resolved_experiment_id = infer_next_step_experiment_id(analysis_paths, experiment_id)
    ctx = RenderContext(
        experiment_id=resolved_experiment_id,
        hypothesis=hypothesis,
        repo_root=PROJECT_ROOT,
        worktree=worktree,
        prototype_worktree=prototype_worktree,
        evidence_paths=evidence,
        report_path=report_path,
    )
    return write_packet(ctx, ["next_step_derivation"], out_dir), []


def verify_packet(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    packet = load_packet(path)
    issues: list[dict[str, Any]] = []
    for role in packet.get("roles", []):
        prompt_path = Path(str(role.get("prompt_path", "")))
        if not prompt_path.is_absolute():
            prompt_path = path.parent / prompt_path
        if not prompt_path.is_file():
            issues.append({
                "role_id": role.get("role_id"),
                "prompt_path": str(prompt_path),
                "issue": "missing_prompt",
            })
            continue
        prompt = prompt_path.read_text()
        actual = sha256_text(prompt)
        expected = role.get("prompt_sha256")
        if expected != actual:
            issues.append({
                "role_id": role.get("role_id"),
                "prompt_path": str(prompt_path),
                "issue": "prompt_sha256_mismatch",
                "expected": expected,
                "actual": actual,
            })
    expected_evidence_hash = packet.get("evidence_sha256")
    actual_evidence_hash = sha256_text("\n".join(packet.get("evidence_paths", [])))
    if expected_evidence_hash != actual_evidence_hash:
        issues.append({
            "issue": "evidence_sha256_mismatch",
            "expected": expected_evidence_hash,
            "actual": actual_evidence_hash,
        })
    return packet, issues


def decision_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "; ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value).strip()


def normalized_decision_text(value: Any) -> str:
    text = decision_string(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tag_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", decision_string(value).lower()).strip("_")


def canonical_decision_tags(value: Any) -> set[str]:
    raw = tag_key(value)
    if not raw:
        return set()
    tags: set[str] = set()
    if "rule_executor" in raw or raw == "executor" or raw.endswith("_executor"):
        tags.add("rule_executor_pipeline")
    if "normaliz" in raw:
        tags.add("graph_normalization")
    if "boundary" in raw or "edge" in raw or "one_rule" in raw:
        tags.add("edge_preservation")
    if "substitution_structural" in raw or ("substitution" in raw and "structural" in raw):
        tags.add("substitution_structural_check")
    if "production" in raw or "gate" in raw or "judge" in raw:
        tags.add("production_gate_equivalence")
    if "target" in raw or "single" in raw or "frozen" in raw or "hard" in raw:
        tags.add("focused_target_replay")
    if "paired" in raw or raw.endswith("_ab") or "_ab_" in raw or "replay" in raw:
        tags.add("paired_replay")
    if "arg" in raw or "schema" in raw or "multiplier" in raw:
        tags.add("arg_schema")
    if "scale" in raw or "quality_claim" in raw or "merge_claim" in raw or "inconclusive" in raw:
        tags.add("no_premature_claim")
    return tags or {raw}


def text_similarity(left: str, right: str) -> float:
    norm_left = normalized_decision_text(left)
    norm_right = normalized_decision_text(right)
    if not norm_left and not norm_right:
        return 1.0
    if not norm_left or not norm_right:
        return 0.0
    return SequenceMatcher(None, norm_left, norm_right).ratio()


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def infer_decision_tags(text: str) -> set[str]:
    normalized = normalized_decision_text(text)
    tags: set[str] = set()
    if re.search(r"\brule executor\b|\brule[-_]executor\b|\bexecutor\b", normalized):
        tags.add("rule_executor_pipeline")
    if re.search(r"\bnormaliz|\bnormalized graph\b|\bgraph handoff\b", normalized):
        tags.add("graph_normalization")
    if (
        re.search(r"\bedges?\b|\bstep results?\b|\bstep_result\b", normalized)
        and re.search(r"\bpreserv|\bseparat|\bsplit|\bdistinct|\bone to one\b", normalized)
    ):
        tags.add("edge_preservation")
    if re.search(r"\bsubstitution structural\b|\bstructural substitution\b|\bsubstitution_structural\b", normalized):
        tags.add("substitution_structural_check")
    if re.search(r"\bproduction gate\b|\bgate equivalence\b|\btarget check\b|\bjudge\b|\bskipped gate\b", normalized):
        tags.add("production_gate_equivalence")
    if re.search(r"\btarget 001\b|\btarget_001\b|\bhard target\b|\bsingle target\b|\bone target\b", normalized):
        tags.add("focused_target_replay")
    if re.search(r"\breplay\b|\bpaired\b|\bcontrol treatment\b|\bcontrol\b.*\btreatment\b", normalized):
        tags.add("paired_replay")
    if re.search(r"\barg\b|\bschema\b|\bmultiplier\b", normalized):
        tags.add("arg_schema")
    if re.search(r"\bscale\b|\blarger workload\b|\bmore targets\b|\bbatch\b", normalized):
        tags.add("larger_workload")
    if re.search(r"\bprompt only\b|\bprompt-only\b", normalized):
        tags.add("prompt_only")
    return tags


def parse_json_decision_block(text: str) -> dict[str, Any]:
    for match in reversed(list(JSON_BLOCK_RE.finditer(text))):
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def label_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def extract_labeled_line(text: str, labels: set[str]) -> str:
    normalized_labels = {label_key(label) for label in labels}
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*#").strip()
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        if label_key(label) in normalized_labels:
            return value.strip().strip("`")
    return ""


def first_decision_value(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if decision_string(value):
            return decision_string(value)
    return ""


def decision_tags(data: dict[str, Any], selected: str, design: str) -> list[str]:
    explicit = data.get("decision_tags", [])
    tags: set[str] = set()
    if isinstance(explicit, list):
        for item in explicit:
            tags.update(canonical_decision_tags(item))
    elif decision_string(explicit):
        tags.update(canonical_decision_tags(explicit))
    tags.update(infer_decision_tags("\n".join([selected, design])))
    return sorted(tags)


def parse_next_step_decision(text: str) -> dict[str, Any]:
    data = parse_json_decision_block(text)
    selected = first_decision_value(
        data,
        ("selected_next_hypothesis", "selected_hypothesis", "next_hypothesis"),
    )
    design = first_decision_value(
        data,
        ("minimum_experiment_design", "experiment_design", "minimum_test"),
    )
    ready = first_decision_value(
        data,
        ("next_step_ready", "ready", "verdict"),
    ).lower()

    if not selected:
        selected = extract_labeled_line(text, {
            "selected next hypothesis",
            "selected_next_hypothesis",
            "next hypothesis",
        })
    if not design:
        design = extract_labeled_line(text, {
            "minimum experiment design",
            "minimum_experiment_design",
            "experiment design",
        })
    if not ready:
        ready = extract_labeled_line(text, {
            "next_step_ready",
            "next step ready",
            "verdict",
        }).lower()
    ready_match = re.search(r"\b(yes|no)\b", ready)
    ready = ready_match.group(1) if ready_match else ready

    missing = []
    if not selected:
        missing.append("selected_next_hypothesis")
    if not design:
        missing.append("minimum_experiment_design")
    if ready not in {"yes", "no"}:
        missing.append("next_step_ready")
    return {
        "decision_tags": decision_tags(data, selected, design),
        "selected_next_hypothesis": selected,
        "minimum_experiment_design": design,
        "next_step_ready": ready,
        "parse_status": "ok" if not missing else "missing_fields",
        "missing_fields": missing,
    }


def compare_next_step_outputs(paths: list[Path], similarity_threshold: float = 0.70) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for index, path in enumerate(paths, start=1):
        text = path.read_text()
        decision = parse_next_step_decision(text)
        runs.append({
            "run": index,
            "output_path": str(path),
            "output_sha256": sha256_text(text),
            "decision": decision,
        })
        if decision["parse_status"] != "ok":
            issues.append({
                "run": index,
                "issue": "decision_parse_incomplete",
                "missing_fields": decision["missing_fields"],
            })

    if len(runs) < 2:
        issues.append({"issue": "not_enough_outputs", "n_outputs": len(runs)})

    reference = runs[0]["decision"] if runs else {}
    reference_tags = set(reference.get("decision_tags", []))
    for run in runs[1:]:
        decision = run["decision"]
        current_tags = set(decision.get("decision_tags", []))
        hypothesis_similarity = text_similarity(
            reference.get("selected_next_hypothesis", ""),
            decision.get("selected_next_hypothesis", ""),
        )
        design_similarity = text_similarity(
            reference.get("minimum_experiment_design", ""),
            decision.get("minimum_experiment_design", ""),
        )
        ready_match = (
            reference.get("next_step_ready") in {"yes", "no"}
            and reference.get("next_step_ready") == decision.get("next_step_ready")
        )
        tag_similarity = jaccard(reference_tags, current_tags)
        run["similarity_to_reference"] = {
            "selected_next_hypothesis": hypothesis_similarity,
            "minimum_experiment_design": design_similarity,
            "decision_tags": tag_similarity,
            "reference_tags": sorted(reference_tags),
            "actual_tags": sorted(current_tags),
            "next_step_ready_match": ready_match,
        }
        if not reference_tags or not current_tags:
            issues.append({
                "run": run["run"],
                "issue": "decision_tags_missing",
                "reference_tags": sorted(reference_tags),
                "actual_tags": sorted(current_tags),
            })
        elif tag_similarity < similarity_threshold:
            issues.append({
                "run": run["run"],
                "issue": "decision_tags_diverged",
                "similarity": tag_similarity,
                "threshold": similarity_threshold,
                "reference_tags": sorted(reference_tags),
                "actual_tags": sorted(current_tags),
            })
        if not ready_match:
            issues.append({
                "run": run["run"],
                "issue": "next_step_ready_diverged",
                "reference": reference.get("next_step_ready"),
                "actual": decision.get("next_step_ready"),
            })

    return {
        "schema_version": "next_step_reproducibility.v1",
        "n_outputs": len(paths),
        "similarity_threshold": similarity_threshold,
        "reference_output": str(paths[0]) if paths else "",
        "decision_reproducible": not issues,
        "issues": issues,
        "runs": runs,
    }


def slug_part(value: str | None) -> str:
    text = value or "default"
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")
    return text or "default"


def cmd_list_roles() -> int:
    manifest = load_manifest()
    for role_id, role in manifest["roles"].items():
        print(f"{role_id}\t{role.get('phase')}\t{role.get('agent_type')}\t{role.get('output')}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    try:
        roles = expand_roles(manifest, args.role)
    except ValueError as e:
        print(f"[experiment-agents] {e}", file=sys.stderr)
        return 2

    out_root = Path(args.out_root) if args.out_root else DEFAULT_OUT_ROOT
    out_dir = Path(args.out_dir) if args.out_dir else (out_root / args.experiment_id)
    ctx = RenderContext(
        experiment_id=args.experiment_id,
        hypothesis=args.hypothesis,
        repo_root=PROJECT_ROOT,
        worktree=args.worktree,
        prototype_worktree=args.prototype_worktree or "",
        evidence_paths=args.evidence or [],
        report_path=args.report_path or "",
    )
    packet = write_packet(ctx, roles, out_dir)
    print(json.dumps({
        "packet": str(out_dir / "packet.json"),
        "roles": [
            {
                "role_id": role["role_id"],
                "prompt_path": role["prompt_path"],
                "prompt_sha256": role["prompt_sha256"],
            }
            for role in packet["roles"]
        ],
        "evidence_sha256": packet["evidence_sha256"],
    }, indent=2))
    return 0


def cmd_render_ab_analysis(args: argparse.Namespace) -> int:
    control_dir = resolve_project_path(args.control)
    treatment_dir = resolve_project_path(args.treatment)
    experiment_id = infer_experiment_id(control_dir, treatment_dir, args.experiment_id)
    out_root = Path(args.out_root) if args.out_root else DEFAULT_OUT_ROOT
    out_dir = Path(args.out_dir) if args.out_dir else (out_root / f"{experiment_id}_ab_analysis")
    packet, issues = write_ab_analysis_packet(
        control_dir=control_dir,
        treatment_dir=treatment_dir,
        experiment_id=experiment_id,
        hypothesis=args.hypothesis or DEFAULT_AB_ANALYSIS_HYPOTHESIS,
        worktree=args.worktree or str(PROJECT_ROOT),
        prototype_worktree=args.prototype_worktree or "",
        report_path=args.report_path or "",
        out_dir=out_dir,
        require_comparison=not args.allow_missing_comparison,
    )
    if issues:
        print(json.dumps({
            "error": "ab_analysis_evidence_incomplete",
            "issues": issues,
        }, indent=2), file=sys.stderr)
        return 2
    assert packet is not None
    role = packet["roles"][0]
    print(json.dumps({
        "packet": str(out_dir / "packet.json"),
        "roles": [{
            "role_id": role["role_id"],
            "prompt_path": role["prompt_path"],
            "prompt_sha256": role["prompt_sha256"],
        }],
        "evidence_count": len(packet["evidence_paths"]),
        "evidence_sha256": packet["evidence_sha256"],
    }, indent=2))
    return 0


def cmd_render_next_step(args: argparse.Namespace) -> int:
    experiment_id = infer_next_step_experiment_id(args.analysis, args.experiment_id)
    out_root = Path(args.out_root) if args.out_root else DEFAULT_OUT_ROOT
    out_dir = Path(args.out_dir) if args.out_dir else (out_root / experiment_id)
    packet, issues = write_next_step_packet(
        analysis_paths=args.analysis,
        extra_evidence=args.evidence or [],
        experiment_id=experiment_id,
        hypothesis=args.hypothesis or DEFAULT_NEXT_STEP_HYPOTHESIS,
        worktree=args.worktree or str(PROJECT_ROOT),
        prototype_worktree=args.prototype_worktree or "",
        report_path=args.report_path or "",
        out_dir=out_dir,
    )
    if issues:
        print(json.dumps({
            "error": "next_step_evidence_incomplete",
            "issues": issues,
        }, indent=2), file=sys.stderr)
        return 2
    assert packet is not None
    role = packet["roles"][0]
    print(json.dumps({
        "packet": str(out_dir / "packet.json"),
        "roles": [{
            "role_id": role["role_id"],
            "prompt_path": role["prompt_path"],
            "prompt_sha256": role["prompt_sha256"],
        }],
        "evidence_count": len(packet["evidence_paths"]),
        "evidence_sha256": packet["evidence_sha256"],
    }, indent=2))
    return 0


def cmd_verify_packet(args: argparse.Namespace) -> int:
    packet, issues = verify_packet(Path(args.packet))
    payload = {
        "packet": args.packet,
        "experiment_id": packet.get("experiment_id"),
        "roles": [
            {
                "role_id": role.get("role_id"),
                "prompt_path": role.get("prompt_path"),
                "prompt_sha256": role.get("prompt_sha256"),
            }
            for role in packet.get("roles", [])
        ],
        "evidence_sha256": packet.get("evidence_sha256"),
        "issues": issues,
        "reproducible": not issues,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not issues else 2


def cmd_compare_next_step(args: argparse.Namespace) -> int:
    paths = [Path(output) for output in args.output]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        print(json.dumps({
            "error": "missing_outputs",
            "missing": missing,
        }, indent=2), file=sys.stderr)
        return 2
    report = compare_next_step_outputs(paths, args.similarity_threshold)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if report["decision_reproducible"] else 1


def load_packet(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def role_from_packet(packet: dict[str, Any], role_id: str) -> dict[str, Any] | None:
    for role in packet.get("roles", []):
        if role.get("role_id") == role_id:
            return role
    return None


def codex_run_command(args: argparse.Namespace, packet: dict[str, Any], role: dict[str, Any], output: Path) -> list[str]:
    worktree = args.worktree or packet.get("worktree") or packet.get("repo_root") or str(PROJECT_ROOT)
    cmd = [
        args.codex_bin,
        "exec",
        "-C",
        str(worktree),
        "--sandbox",
        args.sandbox,
    ]
    if args.model:
        cmd.extend(["--model", args.model])
    if args.reasoning_effort:
        cmd.extend(["-c", f'model_reasoning_effort="{args.reasoning_effort}"'])
    if args.ephemeral:
        cmd.append("--ephemeral")
    cmd.extend(["--output-last-message", str(output), "-"])
    return cmd


def cmd_run_role(args: argparse.Namespace) -> int:
    packet_path = Path(args.packet)
    packet = load_packet(packet_path)
    role = role_from_packet(packet, args.role)
    if not role:
        print(f"[experiment-agents] packet has no role {args.role!r}", file=sys.stderr)
        return 2
    prompt_path = Path(role["prompt_path"])
    if not prompt_path.is_absolute():
        prompt_path = packet_path.parent / prompt_path
    prompt = prompt_path.read_text()
    output = Path(args.output) if args.output else packet_path.parent / f"{args.role}_result.txt"
    cmd = codex_run_command(args, packet, role, output)
    if args.dry_run:
        print(json.dumps({
            "command": cmd,
            "prompt_path": str(prompt_path),
            "output": str(output),
        }, indent=2))
        return 0
    result = subprocess.run(cmd, input=prompt, text=True)
    return result.returncode


def cmd_run_reproducibility(args: argparse.Namespace) -> int:
    packet_path = Path(args.packet)
    packet, packet_issues = verify_packet(packet_path)
    if packet_issues:
        print(json.dumps({
            "error": "packet_not_reproducible",
            "issues": packet_issues,
        }, indent=2), file=sys.stderr)
        return 2
    role = role_from_packet(packet, args.role)
    if not role:
        print(f"[experiment-agents] packet has no role {args.role!r}", file=sys.stderr)
        return 2
    prompt_path = Path(role["prompt_path"])
    if not prompt_path.is_absolute():
        prompt_path = packet_path.parent / prompt_path
    prompt = prompt_path.read_text()

    out_dir = Path(args.out_dir) if args.out_dir else (
        packet_path.parent
        / "reproducibility"
        / f"{args.role}_{slug_part(args.model)}_{slug_part(args.reasoning_effort)}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    run_records = []
    output_paths = []
    command_failures = []
    for index in range(1, args.runs + 1):
        output = out_dir / f"run_{index:02d}.txt"
        cmd = codex_run_command(args, packet, role, output)
        run_record = {
            "run": index,
            "command": cmd,
            "output": str(output),
        }
        if args.dry_run:
            run_records.append(run_record)
            continue
        result = subprocess.run(cmd, input=prompt, text=True)
        run_record["returncode"] = result.returncode
        run_records.append(run_record)
        if result.returncode == 0 and output.is_file():
            output_paths.append(output)
        else:
            command_failures.append({
                "run": index,
                "returncode": result.returncode,
                "output": str(output),
            })

    if args.dry_run:
        payload = {
            "packet": str(packet_path),
            "role": args.role,
            "runs": run_records,
        }
        print(json.dumps(payload, indent=2))
        return 0

    report = compare_next_step_outputs(output_paths, args.similarity_threshold)
    report["packet"] = str(packet_path)
    report["role"] = args.role
    report["model"] = args.model
    report["reasoning_effort"] = args.reasoning_effort
    report["run_records"] = run_records
    if command_failures:
        report["issues"].extend({
            "issue": "run_command_failed",
            **failure,
        } for failure in command_failures)
        report["decision_reproducible"] = False
    report_path = out_dir / "reproducibility_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "report": str(report_path),
        "decision_reproducible": report["decision_reproducible"],
        "issues": report["issues"],
    }, indent=2))
    return 0 if report["decision_reproducible"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-roles")

    render = sub.add_parser("render")
    render.add_argument("--experiment-id", required=True)
    render.add_argument("--hypothesis", required=True)
    render.add_argument("--worktree", required=True)
    render.add_argument("--prototype-worktree", default="")
    render.add_argument("--report-path", default="",
                        help="markdown report path for report-writer/review roles")
    render.add_argument("--evidence", action="append", default=[])
    render.add_argument("--role", action="append", default=None,
                        help="role or group to render; default: prebuild")
    render.add_argument("--out-root", default=None)
    render.add_argument("--out-dir", default=None)

    ab = sub.add_parser("render-ab-analysis")
    ab.add_argument("--control", required=True, help="control batch dir")
    ab.add_argument("--treatment", required=True, help="treatment batch dir")
    ab.add_argument("--experiment-id", default=None,
                    help="defaults to experiment_id from comparison/batch artifacts")
    ab.add_argument("--hypothesis", default=None,
                    help=f"default: {DEFAULT_AB_ANALYSIS_HYPOTHESIS}")
    ab.add_argument("--worktree", default=None,
                    help="defaults to this repository root")
    ab.add_argument("--prototype-worktree", default="")
    ab.add_argument("--report-path", default="")
    ab.add_argument("--out-root", default=None)
    ab.add_argument("--out-dir", default=None)
    ab.add_argument("--allow-missing-comparison", action="store_true",
                    help="render even when treatment/ab_comparison.json is absent")

    next_step = sub.add_parser("render-next-step")
    next_step.add_argument("--analysis", required=True, action="append",
                           help="analysis or introspection result artifact")
    next_step.add_argument("--evidence", action="append", default=[],
                           help="additional grounding artifact")
    next_step.add_argument("--experiment-id", default=None,
                           help="defaults from the analysis filename")
    next_step.add_argument("--hypothesis", default=None,
                           help=f"default: {DEFAULT_NEXT_STEP_HYPOTHESIS}")
    next_step.add_argument("--worktree", default=None,
                           help="defaults to this repository root")
    next_step.add_argument("--prototype-worktree", default="")
    next_step.add_argument("--report-path", default="")
    next_step.add_argument("--out-root", default=None)
    next_step.add_argument("--out-dir", default=None)

    verify = sub.add_parser("verify-packet")
    verify.add_argument("--packet", required=True, help="packet.json path")

    compare_next = sub.add_parser("compare-next-step")
    compare_next.add_argument("--output", required=True, action="append",
                              help="next_step_derivation output to compare")
    compare_next.add_argument("--similarity-threshold", type=float, default=0.70)
    compare_next.add_argument("--report", default=None,
                              help="optional JSON report path")

    run = sub.add_parser("run-role")
    run.add_argument("--packet", required=True, help="packet.json path")
    run.add_argument("--role", required=True)
    run.add_argument("--worktree", default=None,
                     help="override packet worktree")
    run.add_argument("--output", default=None,
                     help="default: <packet-dir>/<role>_result.txt")
    run.add_argument("--sandbox", default="read-only",
                     choices=["read-only", "workspace-write", "danger-full-access"])
    run.add_argument("--model", default=None)
    run.add_argument("--reasoning-effort", default=None)
    run.add_argument("--codex-bin", default="codex")
    run.add_argument("--ephemeral", action="store_true")
    run.add_argument("--dry-run", action="store_true")

    repro = sub.add_parser("run-reproducibility")
    repro.add_argument("--packet", required=True, help="packet.json path")
    repro.add_argument("--role", default="next_step_derivation")
    repro.add_argument("--runs", type=int, default=3)
    repro.add_argument("--out-dir", default=None)
    repro.add_argument("--worktree", default=None,
                       help="override packet worktree")
    repro.add_argument("--sandbox", default="read-only",
                       choices=["read-only", "workspace-write", "danger-full-access"])
    repro.add_argument("--model", default=None)
    repro.add_argument("--reasoning-effort", default=None)
    repro.add_argument("--codex-bin", default="codex")
    repro.add_argument("--ephemeral", action="store_true")
    repro.add_argument("--dry-run", action="store_true")
    repro.add_argument("--similarity-threshold", type=float, default=0.70)

    args = parser.parse_args()
    if args.cmd == "list-roles":
        return cmd_list_roles()
    if args.cmd == "render":
        return cmd_render(args)
    if args.cmd == "render-ab-analysis":
        return cmd_render_ab_analysis(args)
    if args.cmd == "render-next-step":
        return cmd_render_next_step(args)
    if args.cmd == "verify-packet":
        return cmd_verify_packet(args)
    if args.cmd == "compare-next-step":
        return cmd_compare_next_step(args)
    if args.cmd == "run-role":
        return cmd_run_role(args)
    if args.cmd == "run-reproducibility":
        return cmd_run_reproducibility(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
