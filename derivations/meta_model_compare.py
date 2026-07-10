#!/usr/bin/env python3
"""Freeze and compare outer meta-analysis runs across expensive models."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
DEFAULT_OUT_ROOT = ROOT / "_evolutions" / "meta_model_comparisons"

PACKET_SCHEMA = "meta_model_comparison_packet.v1"
RUN_SCHEMA = "meta_model_comparison_run.v1"
SCORE_SCHEMA = "meta_model_comparison_score.v1"
COMPARISON_SCHEMA = "meta_model_comparison_report.v1"

REQUIRED_DECISION_KEYS = (
    "route",
    "rationale",
    "confidence",
    "candidate",
    "proposal_paths",
    "experiment_spec",
    "success_criteria",
    "failure_policy",
    "fallback_route",
)
ALLOWED_ROUTES = {"CONTINUE_EPOCH", "BUG_INVESTIGATE", "IMPLEMENT", "EXPERIMENT", "CLOSE"}
ALLOWED_FALLBACK_ROUTES = {"CONTINUE_EPOCH", "IMPLEMENT", "EXPERIMENT", "CLOSE"}
ALLOWED_FAILURE_POLICIES = {"NONE", "PARK_TREATMENT"}

CODEX_FS_SAFE_DISABLES = (
    "plugins",
    "memories",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "image_generation",
    "multi_agent",
    "workspace_dependencies",
    "apps",
    "in_app_browser",
)

SKIP_TRACKED_PREFIXES = (
    "derivations/_evolutions/",
    "derivations/logs/",
    "derivations/reports/",
)
SKIP_TRACKED_FILES = {"derivations/state.json"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def resolve_project_path(path: str | Path, project_root: Path = PROJECT_ROOT) -> Path:
    p = Path(path)
    return p if p.is_absolute() else project_root / p


def rel_path(path: Path, base: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    if not slug or slug in {".", ".."}:
        raise ValueError(f"invalid slug: {value!r}")
    return slug


def file_record(path: Path, *, project_root: Path, workspace_root: Path | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "source_path": rel_path(path, project_root) if path.resolve().is_relative_to(project_root.resolve()) else str(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }
    if workspace_root is not None:
        record["workspace_path"] = rel_path(path, workspace_root)
    return record


def input_file_record(source: Path, copied: Path, *, project_root: Path, workspace_root: Path) -> dict[str, Any]:
    return {
        "source_path": rel_path(source, project_root) if source.resolve().is_relative_to(project_root.resolve()) else str(source),
        "workspace_path": rel_path(copied, workspace_root),
        "sha256": sha256_file(copied),
        "bytes": copied.stat().st_size,
    }


def tree_manifest(root: Path) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    if not root.exists():
        return manifest
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        manifest.append({
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        })
    return manifest


def manifest_hash(manifest: list[dict[str, Any]]) -> str:
    return sha256_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")))


def git_capture(args: list[str], project_root: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def git_info(project_root: Path) -> dict[str, Any]:
    return {
        "head": git_capture(["rev-parse", "HEAD"], project_root),
        "branch": git_capture(["rev-parse", "--abbrev-ref", "HEAD"], project_root),
        "status_short": git_capture(["status", "--short"], project_root).splitlines(),
    }


def tracked_files(project_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(project_root),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    files = result.stdout.decode("utf-8").split("\0")
    out: list[Path] = []
    for raw in files:
        if not raw:
            continue
        if any(raw.startswith(prefix) for prefix in SKIP_TRACKED_PREFIXES):
            continue
        if raw in SKIP_TRACKED_FILES:
            continue
        out.append(Path(raw))
    return sorted(out, key=lambda p: p.as_posix())


def copy_tracked_workspace(project_root: Path, workspace_root: Path) -> int:
    count = 0
    for rel in tracked_files(project_root):
        src = project_root / rel
        if not src.is_file():
            continue
        dst = workspace_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        count += 1
    return count


def copy_into_workspace(src: Path, project_root: Path, workspace_root: Path) -> Path:
    dst = workspace_root / rel_path(src, project_root)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def infer_epoch_dir(prompt: Path, logs: list[Path], project_root: Path) -> str:
    names = {log.parent.name for log in logs if log.parent.name.startswith("epoch_")}
    report_parent = prompt.parent.name
    if report_parent.startswith("epoch_"):
        names.add(report_parent)
    if len(names) != 1:
        raise ValueError(f"expected exactly one epoch directory, got {sorted(names)}")
    return next(iter(names))


def epoch_number(epoch_dir: str) -> int | None:
    match = re.fullmatch(r"epoch_(\d+)", epoch_dir)
    return int(match.group(1)) if match else None


def normalize_checkpoint_state(project_root: Path, workspace_root: Path, epoch_dir: str) -> dict[str, Any] | None:
    source = project_root / "derivations" / "state.json"
    checkpoint_epoch = epoch_number(epoch_dir)
    if not source.is_file() or checkpoint_epoch is None:
        return None
    try:
        state = read_json(source)
    except Exception:
        return None
    if not isinstance(state, dict):
        return None
    original_epoch = state.get("epoch")
    state["epoch"] = checkpoint_epoch
    dest = workspace_root / "derivations" / "state.json"
    write_json(dest, state)
    return {
        "source_path": rel_path(source, project_root),
        "workspace_path": rel_path(dest, workspace_root),
        "source_epoch": original_epoch,
        "checkpoint_epoch": checkpoint_epoch,
        "sha256": sha256_file(dest),
        "bytes": dest.stat().st_size,
    }


def input_digest(prompt_record: dict[str, Any], log_records: list[dict[str, Any]]) -> str:
    payload = {
        "prompt": {
            "workspace_path": prompt_record["workspace_path"],
            "sha256": prompt_record["sha256"],
        },
        "logs": [
            {
                "workspace_path": record["workspace_path"],
                "sha256": record["sha256"],
            }
            for record in log_records
        ],
    }
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def baseline_record(path: Path | None, project_root: Path, out_dir: Path) -> dict[str, Any] | None:
    if path is None:
        return None
    baseline_dir = out_dir / "baseline"
    dst = baseline_dir / path.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dst)
    record = file_record(path, project_root=project_root)
    record["packet_path"] = rel_path(dst, out_dir)
    if path.suffix == ".json":
        try:
            record["parsed"] = read_json(path)
        except Exception:
            record["parsed"] = None
    return record


def freeze_packet(
    *,
    name: str,
    prompt: Path,
    logs: list[Path],
    baseline_console: Path | None,
    baseline_decision: Path | None,
    out_root: Path,
    out_dir: Path | None = None,
    project_root: Path = PROJECT_ROOT,
    overwrite: bool = False,
    copy_tracked: bool = True,
) -> dict[str, Any]:
    if not logs:
        raise ValueError("at least one --log is required")
    prompt = resolve_project_path(prompt, project_root)
    logs = [resolve_project_path(log, project_root) for log in logs]
    baseline_console = resolve_project_path(baseline_console, project_root) if baseline_console else None
    baseline_decision = resolve_project_path(baseline_decision, project_root) if baseline_decision else None
    for path in [prompt, *logs, *(p for p in (baseline_console, baseline_decision) if p is not None)]:
        if not path.is_file():
            raise FileNotFoundError(path)

    slug = safe_slug(name)
    packet_dir = out_dir or (out_root / slug)
    if packet_dir.exists():
        if not overwrite:
            raise FileExistsError(f"packet already exists: {packet_dir}")
        shutil.rmtree(packet_dir)
    workspace = packet_dir / "workspace"
    workspace.mkdir(parents=True)
    tracked_count = copy_tracked_workspace(project_root, workspace) if copy_tracked else 0

    epoch_dir = infer_epoch_dir(prompt, logs, project_root)
    prompt_workspace = copy_into_workspace(prompt, project_root, workspace)
    log_records = []
    for log in logs:
        copied = copy_into_workspace(log, project_root, workspace)
        log_records.append(input_file_record(log, copied, project_root=project_root, workspace_root=workspace))

    prompt_rec = input_file_record(prompt, prompt_workspace, project_root=project_root, workspace_root=workspace)
    source_epoch_dir = project_root / "derivations" / "logs" / epoch_dir
    source_epoch_entries = sorted(p.name for p in source_epoch_dir.iterdir()) if source_epoch_dir.is_dir() else []
    selected_log_names = sorted(log.name for log in logs)
    checkpoint_state = normalize_checkpoint_state(project_root, workspace, epoch_dir)
    workspace_manifest = tree_manifest(workspace)
    baseline_decision_record = baseline_record(baseline_decision, project_root, packet_dir)
    baseline_console_record = baseline_record(baseline_console, project_root, packet_dir)

    packet = {
        "schema_version": PACKET_SCHEMA,
        "name": slug,
        "generated_at": now_iso(),
        "project_root": str(project_root),
        "workspace_dir": "workspace",
        "runs_dir": "runs",
        "git": git_info(project_root),
        "epoch_dir": epoch_dir,
        "checkpoint_state": checkpoint_state,
        "input": {
            "prompt": prompt_rec,
            "logs": log_records,
            "input_digest": input_digest(prompt_rec, log_records),
            "selected_epoch_log_names": selected_log_names,
            "source_epoch_entries": source_epoch_entries,
            "excluded_source_epoch_entries": [
                entry for entry in source_epoch_entries if entry not in selected_log_names
            ],
        },
        "baselines": {
            "console": baseline_console_record,
            "decision": baseline_decision_record,
        },
        "expected_outputs": {
            "report_dir": str(Path(prompt_rec["workspace_path"]).parent.as_posix()),
            "decision_path": str((Path(prompt_rec["workspace_path"]).parent / "analysis_decision.json").as_posix()),
            "summary_path": str((Path(prompt_rec["workspace_path"]).parent / "summary.md").as_posix()),
        },
        "workspace": {
            "tracked_file_count": tracked_count,
            "manifest_sha256": manifest_hash(workspace_manifest),
            "manifest": workspace_manifest,
        },
    }
    write_json(packet_dir / "packet.json", packet)
    return packet


def load_packet(packet_path: Path) -> dict[str, Any]:
    return read_json(packet_path)


def verify_packet(packet_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    packet = load_packet(packet_path)
    packet_dir = packet_path.parent
    workspace = packet_dir / packet.get("workspace_dir", "workspace")
    issues: list[dict[str, Any]] = []
    if packet.get("schema_version") != PACKET_SCHEMA:
        issues.append({"issue": "schema_version_mismatch", "actual": packet.get("schema_version")})

    manifest = tree_manifest(workspace)
    actual_manifest_hash = manifest_hash(manifest)
    expected_manifest_hash = packet.get("workspace", {}).get("manifest_sha256")
    if actual_manifest_hash != expected_manifest_hash:
        issues.append({
            "issue": "workspace_manifest_sha256_mismatch",
            "expected": expected_manifest_hash,
            "actual": actual_manifest_hash,
        })

    for kind, record in [
        ("prompt", packet.get("input", {}).get("prompt", {})),
        *[(f"log_{index}", record) for index, record in enumerate(packet.get("input", {}).get("logs", []), start=1)],
    ]:
        rel = record.get("workspace_path")
        path = workspace / str(rel)
        if not path.is_file():
            issues.append({"issue": "missing_input_file", "kind": kind, "path": str(path)})
            continue
        actual = sha256_file(path)
        if actual != record.get("sha256"):
            issues.append({
                "issue": "input_sha256_mismatch",
                "kind": kind,
                "path": str(path),
                "expected": record.get("sha256"),
                "actual": actual,
            })

    epoch_dir = packet.get("epoch_dir", "")
    expected_logs = packet.get("input", {}).get("selected_epoch_log_names", [])
    actual_logs = []
    log_dir = workspace / "derivations" / "logs" / epoch_dir
    if log_dir.is_dir():
        actual_logs = sorted(p.name for p in log_dir.iterdir())
    if actual_logs != expected_logs:
        issues.append({
            "issue": "epoch_log_listing_mismatch",
            "expected": expected_logs,
            "actual": actual_logs,
        })
    return packet, issues


def build_codex_command(
    *,
    codex_bin: str,
    workspace: Path,
    sandbox: str,
    model: str,
    reasoning_effort: str,
    output: Path,
) -> list[str]:
    if not model:
        raise ValueError("--model is required for objective comparison")
    if not reasoning_effort:
        raise ValueError("--reasoning-effort is required for objective comparison")
    cmd = [
        codex_bin,
        "exec",
        "-C",
        str(workspace),
        "--sandbox",
        sandbox,
        "--ignore-user-config",
        "--ignore-rules",
    ]
    for feature in CODEX_FS_SAFE_DISABLES:
        cmd.extend(["--disable", feature])
    cmd.extend([
        "--model",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--ephemeral",
        "--output-last-message",
        str(output),
        "-",
    ])
    return cmd


def decision_schema_issues(decision: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    missing = [key for key in REQUIRED_DECISION_KEYS if key not in decision]
    if missing:
        issues.append({"issue": "decision_missing_keys", "missing": missing})
    route = decision.get("route")
    if route not in ALLOWED_ROUTES:
        issues.append({"issue": "decision_route_invalid", "route": route})
    fallback = decision.get("fallback_route")
    if fallback not in ALLOWED_FALLBACK_ROUTES:
        issues.append({"issue": "decision_fallback_route_invalid", "fallback_route": fallback})
    failure_policy = decision.get("failure_policy")
    if failure_policy not in ALLOWED_FAILURE_POLICIES:
        issues.append({"issue": "decision_failure_policy_invalid", "failure_policy": failure_policy})
    if not isinstance(decision.get("proposal_paths", []), list):
        issues.append({"issue": "decision_proposal_paths_not_list"})
    if decision.get("experiment_spec") is not None and not isinstance(decision.get("experiment_spec"), dict):
        issues.append({"issue": "decision_experiment_spec_invalid"})
    if decision.get("success_criteria") is not None and not isinstance(decision.get("success_criteria"), dict):
        issues.append({"issue": "decision_success_criteria_invalid"})
    if route == "BUG_INVESTIGATE":
        candidate = decision.get("candidate")
        if not isinstance(candidate, dict) or not candidate.get("hypothesis"):
            issues.append({"issue": "bug_investigate_candidate_invalid"})
    return issues


def proposal_path_issues(decision: dict[str, Any], workspace: Path) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    proposal_paths = decision.get("proposal_paths", [])
    if not isinstance(proposal_paths, list):
        return [{"issue": "proposal_paths_not_list"}]
    for raw in proposal_paths:
        if not isinstance(raw, str):
            issues.append({"issue": "proposal_path_not_string", "path": raw})
            continue
        p = Path(raw)
        if p.is_absolute():
            issues.append({"issue": "proposal_path_absolute", "path": raw})
            continue
        if not (workspace / p).is_file():
            issues.append({"issue": "proposal_path_missing", "path": raw})
    if decision.get("route") == "IMPLEMENT" and not proposal_paths:
        issues.append({"issue": "implement_route_without_proposals"})
    return issues


def epoch_log_listing(packet: dict[str, Any], workspace: Path) -> list[str]:
    log_dir = workspace / "derivations" / "logs" / str(packet.get("epoch_dir", ""))
    if not log_dir.is_dir():
        return []
    return sorted(p.name for p in log_dir.iterdir())


def score_run(packet_path: Path, run_dir: Path, run_record: dict[str, Any]) -> dict[str, Any]:
    packet = load_packet(packet_path)
    packet_dir = packet_path.parent
    run_workspace = run_dir / "workspace"
    packet_issues = verify_packet(packet_path)[1]
    prompt_path = run_workspace / packet["input"]["prompt"]["workspace_path"]
    decision_path = run_workspace / packet["expected_outputs"]["decision_path"]
    summary_path = run_workspace / packet["expected_outputs"]["summary_path"]

    issues: list[dict[str, Any]] = []
    decision: dict[str, Any] = {}
    decision_json_valid = False
    if decision_path.is_file():
        try:
            parsed = read_json(decision_path)
            if isinstance(parsed, dict):
                decision = parsed
                decision_json_valid = True
            else:
                issues.append({"issue": "decision_not_object", "path": str(decision_path)})
        except Exception as exc:
            issues.append({"issue": "decision_json_invalid", "path": str(decision_path), "error": str(exc)})
    else:
        issues.append({"issue": "decision_missing", "path": str(decision_path)})

    schema_issues = decision_schema_issues(decision) if decision_json_valid else []
    proposal_issues = proposal_path_issues(decision, run_workspace) if decision_json_valid else []
    issues.extend(schema_issues)
    issues.extend(proposal_issues)

    actual_logs = epoch_log_listing(packet, run_workspace)
    expected_logs = packet["input"]["selected_epoch_log_names"]
    epoch_logs_exact = actual_logs == expected_logs
    if not epoch_logs_exact:
        issues.append({"issue": "run_epoch_log_listing_mismatch", "expected": expected_logs, "actual": actual_logs})

    prompt_hash_match = prompt_path.is_file() and sha256_file(prompt_path) == packet["input"]["prompt"]["sha256"]
    if not prompt_hash_match:
        issues.append({"issue": "run_prompt_sha256_mismatch", "path": str(prompt_path)})

    baseline_decision = packet.get("baselines", {}).get("decision", {}) or {}
    baseline_parsed = baseline_decision.get("parsed") if isinstance(baseline_decision, dict) else None
    baseline_route = baseline_parsed.get("route") if isinstance(baseline_parsed, dict) else None
    route = decision.get("route") if decision_json_valid else None

    checks = {
        "packet_verified": not packet_issues,
        "command_succeeded": run_record.get("returncode") == 0,
        "model_explicit": bool(run_record.get("model")),
        "reasoning_effort_explicit": bool(run_record.get("reasoning_effort")),
        "input_digest_match": run_record.get("input_digest") == packet["input"]["input_digest"],
        "prompt_hash_match": prompt_hash_match,
        "epoch_logs_exact": epoch_logs_exact,
        "decision_exists": decision_path.is_file(),
        "decision_json_valid": decision_json_valid,
        "decision_schema_valid": decision_json_valid and not schema_issues,
        "proposal_paths_resolve": decision_json_valid and not proposal_issues,
        "summary_exists": summary_path.is_file(),
    }
    passed = sum(1 for value in checks.values() if value)
    score = {
        "schema_version": SCORE_SCHEMA,
        "generated_at": now_iso(),
        "packet": str(packet_path),
        "run_dir": str(run_dir),
        "arm": run_record.get("arm"),
        "engine": run_record.get("engine"),
        "model": run_record.get("model"),
        "reasoning_effort": run_record.get("reasoning_effort"),
        "input_digest": run_record.get("input_digest"),
        "objective_checks": checks,
        "objective_score": passed / len(checks),
        "issues": [*packet_issues, *issues],
        "decision_summary": {
            "route": route,
            "baseline_route": baseline_route,
            "baseline_route_match": bool(route and baseline_route and route == baseline_route),
            "confidence": decision.get("confidence") if decision_json_valid else None,
            "proposal_count": len(decision.get("proposal_paths", [])) if isinstance(decision.get("proposal_paths"), list) else 0,
            "experiment_spec_present": isinstance(decision.get("experiment_spec"), dict),
            "candidate_present": isinstance(decision.get("candidate"), dict),
        },
        "paths": {
            "decision": str(decision_path),
            "summary": str(summary_path),
            "last_message": str(run_dir / "last_message.txt"),
            "stdout": str(run_dir / "stdout.txt"),
            "stderr": str(run_dir / "stderr.txt"),
        },
    }
    write_json(run_dir / "score.json", score)
    return score


def run_arm(args: argparse.Namespace) -> int:
    packet_path = Path(args.packet)
    packet, packet_issues = verify_packet(packet_path)
    if packet_issues:
        print(json.dumps({"error": "packet_not_reproducible", "issues": packet_issues}, indent=2), file=sys.stderr)
        return 2
    if args.engine != "codex":
        print(json.dumps({
            "error": "unsupported_engine_for_agentic_comparison",
            "engine": args.engine,
            "reason": "outer-loop comparison requires identical writable workspace/tool access; use codex arms only",
        }, indent=2), file=sys.stderr)
        return 2

    arm = safe_slug(args.arm)
    packet_dir = packet_path.parent
    run_dir = packet_dir / packet.get("runs_dir", "runs") / arm
    run_workspace = run_dir / "workspace"
    last_message = run_dir / "last_message.txt"
    command = build_codex_command(
        codex_bin=args.codex_bin,
        workspace=run_workspace,
        sandbox=args.sandbox,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        output=last_message,
    )
    run_record = {
        "schema_version": RUN_SCHEMA,
        "arm": arm,
        "engine": args.engine,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "packet": str(packet_path),
        "input_digest": packet["input"]["input_digest"],
        "command": command,
        "started_at": now_iso(),
    }
    if args.dry_run:
        run_record["dry_run"] = True
        print(json.dumps(run_record, indent=2))
        return 0

    if run_dir.exists():
        if not args.overwrite:
            print(json.dumps({"error": "run_already_exists", "run_dir": str(run_dir)}, indent=2), file=sys.stderr)
            return 2
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    shutil.copytree(packet_dir / packet.get("workspace_dir", "workspace"), run_workspace)

    prompt_path = run_workspace / packet["input"]["prompt"]["workspace_path"]
    prompt = prompt_path.read_text()

    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=args.timeout,
            check=False,
        )
        run_record["returncode"] = result.returncode
        (run_dir / "stdout.txt").write_text(result.stdout)
        (run_dir / "stderr.txt").write_text(result.stderr)
    except subprocess.TimeoutExpired as exc:
        run_record["returncode"] = 124
        run_record["timeout_s"] = args.timeout
        run_record["timeout_error"] = str(exc)
        (run_dir / "stdout.txt").write_text(exc.stdout or "")
        (run_dir / "stderr.txt").write_text(exc.stderr or "")
    run_record["ended_at"] = now_iso()
    run_record["wall_time_s"] = round(time.monotonic() - started, 3)
    write_json(run_dir / "run_record.json", run_record)
    score = score_run(packet_path, run_dir, run_record)
    print(json.dumps(score, indent=2))
    return 0 if score["objective_checks"]["command_succeeded"] else 1


def score_existing(args: argparse.Namespace) -> int:
    packet_path = Path(args.packet)
    run_dir = Path(args.run_dir)
    record_path = run_dir / "run_record.json"
    if not record_path.is_file():
        print(json.dumps({"error": "missing_run_record", "path": str(record_path)}, indent=2), file=sys.stderr)
        return 2
    score = score_run(packet_path, run_dir, read_json(record_path))
    print(json.dumps(score, indent=2))
    return 0


def compare_runs(args: argparse.Namespace) -> int:
    packet_path = Path(args.packet)
    packet, packet_issues = verify_packet(packet_path)
    packet_dir = packet_path.parent
    runs_dir = packet_dir / packet.get("runs_dir", "runs")
    score_paths = sorted(runs_dir.glob("*/score.json")) if runs_dir.is_dir() else []
    scores = [read_json(path) for path in score_paths]
    issues: list[dict[str, Any]] = list(packet_issues)
    if len(scores) < 2 and not args.allow_single:
        issues.append({"issue": "not_enough_model_arms", "n_arms": len(scores)})

    input_digests = {score.get("input_digest") for score in scores}
    same_input = input_digests == {packet["input"]["input_digest"]} if scores else False
    if not same_input:
        issues.append({
            "issue": "run_input_digest_mismatch",
            "expected": packet["input"]["input_digest"],
            "actual": sorted(str(value) for value in input_digests),
        })

    arm_summaries = []
    route_distribution: dict[str, int] = {}
    for score in scores:
        checks = score.get("objective_checks", {})
        decision_summary = score.get("decision_summary", {})
        route = decision_summary.get("route") or "UNPARSED"
        route_distribution[route] = route_distribution.get(route, 0) + 1
        invalid_checks = sorted(key for key, value in checks.items() if not value)
        if invalid_checks:
            issues.append({
                "issue": "arm_failed_objective_checks",
                "arm": score.get("arm"),
                "failed_checks": invalid_checks,
            })
        arm_summaries.append({
            "arm": score.get("arm"),
            "engine": score.get("engine"),
            "model": score.get("model"),
            "reasoning_effort": score.get("reasoning_effort"),
            "objective_score": score.get("objective_score"),
            "failed_checks": invalid_checks,
            "route": route,
            "confidence": decision_summary.get("confidence"),
            "proposal_count": decision_summary.get("proposal_count"),
            "experiment_spec_present": decision_summary.get("experiment_spec_present"),
            "baseline_route_match": decision_summary.get("baseline_route_match"),
            "score_path": str(score_paths[len(arm_summaries)]),
        })

    report = {
        "schema_version": COMPARISON_SCHEMA,
        "generated_at": now_iso(),
        "packet": str(packet_path),
        "input_digest": packet["input"]["input_digest"],
        "comparison_valid": not issues,
        "issues": issues,
        "route_distribution": route_distribution,
        "arms": arm_summaries,
        "note": "No subjective winner is selected; this report only validates identical inputs and machine-checkable outputs.",
    }
    out = Path(args.report) if args.report else packet_dir / "comparison.json"
    write_json(out, report)
    print(json.dumps(report, indent=2))
    return 0 if report["comparison_valid"] else 1


def cmd_freeze(args: argparse.Namespace) -> int:
    try:
        packet = freeze_packet(
            name=args.name,
            prompt=Path(args.prompt),
            logs=[Path(log) for log in args.log],
            baseline_console=Path(args.baseline_console) if args.baseline_console else None,
            baseline_decision=Path(args.baseline_decision) if args.baseline_decision else None,
            out_root=Path(args.out_root),
            out_dir=Path(args.out_dir) if args.out_dir else None,
            overwrite=args.overwrite,
            copy_tracked=not args.no_tracked_workspace,
        )
    except Exception as exc:
        print(json.dumps({"error": "freeze_failed", "detail": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({
        "packet": str((Path(args.out_dir) if args.out_dir else Path(args.out_root) / safe_slug(args.name)) / "packet.json"),
        "input_digest": packet["input"]["input_digest"],
        "workspace_manifest_sha256": packet["workspace"]["manifest_sha256"],
        "excluded_source_epoch_entries": packet["input"]["excluded_source_epoch_entries"],
    }, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    packet, issues = verify_packet(Path(args.packet))
    payload = {
        "packet": args.packet,
        "schema_version": packet.get("schema_version"),
        "input_digest": packet.get("input", {}).get("input_digest"),
        "issues": issues,
        "reproducible": not issues,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not issues else 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    freeze = sub.add_parser("freeze")
    freeze.add_argument("--name", required=True)
    freeze.add_argument("--prompt", required=True)
    freeze.add_argument("--log", action="append", required=True)
    freeze.add_argument("--baseline-console")
    freeze.add_argument("--baseline-decision")
    freeze.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    freeze.add_argument("--out-dir")
    freeze.add_argument("--overwrite", action="store_true")
    freeze.add_argument("--no-tracked-workspace", action="store_true")
    freeze.set_defaults(func=cmd_freeze)

    verify = sub.add_parser("verify")
    verify.add_argument("--packet", required=True)
    verify.set_defaults(func=cmd_verify)

    run = sub.add_parser("run")
    run.add_argument("--packet", required=True)
    run.add_argument("--arm", required=True)
    run.add_argument("--engine", default="codex", choices=["codex"])
    run.add_argument("--model", required=True)
    run.add_argument("--reasoning-effort", required=True)
    run.add_argument("--sandbox", default="workspace-write")
    run.add_argument("--timeout", type=int, default=7200)
    run.add_argument("--codex-bin", default="codex")
    run.add_argument("--overwrite", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=run_arm)

    score = sub.add_parser("score")
    score.add_argument("--packet", required=True)
    score.add_argument("--run-dir", required=True)
    score.set_defaults(func=score_existing)

    compare = sub.add_parser("compare")
    compare.add_argument("--packet", required=True)
    compare.add_argument("--report")
    compare.add_argument("--allow-single", action="store_true")
    compare.set_defaults(func=compare_runs)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
