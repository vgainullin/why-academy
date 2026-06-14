#!/usr/bin/env python3
"""Generate and optionally run an introspective review of derivation batch logs."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent

DEFAULT_MODEL = "gpt-5.5"
DEFAULT_REASONING_EFFORT = "xhigh"
ARTIFACT_PREFIX = "introspective_log_review"

TARGET_ROOT_FILES = [
    "target.json",
    "target_metrics.json",
    "FAILED.txt",
    "ACCEPTED.txt",
    "seed_variant.md",
    "seed_variant.json",
]

ITER_FILES = [
    "status.txt",
    "result_event.json",
    "failure_diagnosis.json",
    "problem.json",
    "problem.verifier.json",
    "problem.judge.json",
    "problem.target_check.json",
    "addendum.md",
    "transition_score.json",
    "variant.md",
    "verify.log",
    "judge.log",
    "evolve.log",
]


def read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except FileNotFoundError:
        return None


def read_json(path: Path) -> Any:
    text = read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception as e:
        return {"_error": str(e), "_path": str(path)}


def rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def iter_number(iter_dir: Path) -> int:
    name = iter_dir.name
    if not name.startswith("iter_"):
        return 10**9
    try:
        return int(name.removeprefix("iter_"))
    except ValueError:
        return 10**9


def find_target_dir(batch_dir: Path, target_id: str) -> Path:
    target = Path(target_id)
    if target.parts and target.parts[0] == "targets":
        candidate = batch_dir / target
    else:
        candidate = batch_dir / "targets" / target_id
    if not candidate.is_dir():
        raise FileNotFoundError(f"target directory not found: {candidate}")
    return candidate


def iter_dirs(target_dir: Path) -> list[Path]:
    return sorted(
        [p for p in target_dir.glob("iter_*") if p.is_dir()],
        key=lambda p: (iter_number(p), p.name),
    )


def review_files(target_dir: Path) -> list[Path]:
    files: list[Path] = []
    for name in TARGET_ROOT_FILES:
        path = target_dir / name
        if path.exists():
            files.append(path)
    for iter_dir in iter_dirs(target_dir):
        for name in ITER_FILES:
            path = iter_dir / name
            if path.exists():
                files.append(path)
    return files


def _failed_edges(verifier: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for edge in verifier.get("edge_results") or []:
        if edge.get("status") not in ("PASS", None):
            out.append({
                "from": edge.get("from"),
                "to": edge.get("to"),
                "rule": edge.get("rule"),
                "status": edge.get("status"),
                "reason": edge.get("reason"),
            })
    return out


def iteration_summary(iter_dir: Path) -> dict[str, Any]:
    verifier = read_json(iter_dir / "problem.verifier.json") or {}
    judge = read_json(iter_dir / "problem.judge.json") or {}
    target_check = read_json(iter_dir / "problem.target_check.json") or {}
    diagnosis = read_json(iter_dir / "failure_diagnosis.json") or {}
    result = read_json(iter_dir / "result_event.json") or {}
    adversarial = judge.get("adversarial") or {}

    summary: dict[str, Any] = {
        "iter": iter_dir.name,
        "status": (read_text(iter_dir / "status.txt") or "").strip() or result.get("status"),
        "result_status": result.get("status"),
        "diagnosis": diagnosis,
        "verifier_edge_summary": verifier.get("edge_summary"),
        "verifier_failed_edges": _failed_edges(verifier),
        "judge_overall": judge.get("overall"),
        "judge_primary_overall": judge.get("primary_overall"),
        "judge_adversarial": {
            "status": adversarial.get("status"),
            "criterion": adversarial.get("criterion"),
            "reason": adversarial.get("reason") or adversarial.get("error"),
        },
        "target_check_status": target_check.get("status"),
        "addendum_present": (iter_dir / "addendum.md").exists(),
    }
    return {k: v for k, v in summary.items() if v not in (None, {}, [], "")}


def compact_summary(batch_dir: Path, target_dir: Path) -> dict[str, Any]:
    target = read_json(target_dir / "target.json") or {}
    metrics = read_json(target_dir / "target_metrics.json") or {}
    return {
        "batch_dir": rel(batch_dir, PROJECT_ROOT),
        "target_id": target_dir.name,
        "target": target.get("target"),
        "target_metrics": metrics,
        "iterations": [iteration_summary(p) for p in iter_dirs(target_dir)],
    }


def output_schema() -> dict[str, Any]:
    return {
        "detected": "boolean",
        "target_id": "string",
        "original_issue": "short string",
        "repair_fixed_original_issue": "boolean or null if no repair occurred",
        "new_failure_gate": "string or null",
        "new_failure_rule": "string or null",
        "new_failure_description": "short string or null",
        "required_edge_sequence": ["ordered edge/rule descriptions"],
        "root_cause": "short string",
        "recommended_system_change": "short string",
        "hypothesis_for_next_change": "testable hypothesis string",
        "experiment_to_validate": "side-by-side experiment plan string",
    }


def build_prompt(batch_dir: Path, target_dir: Path) -> str:
    files = review_files(target_dir)
    summary = compact_summary(batch_dir, target_dir)
    file_lines = "\n".join(f"- `{rel(p, batch_dir)}`" for p in files)
    summary_json = json.dumps(summary, indent=2, sort_keys=True)
    schema_json = json.dumps(output_schema(), indent=2)
    return f"""You are performing an introspective log review for a derivation pipeline run.

Goal:
- Reproduce an expert review of the saved logs.
- Determine whether a repair fixed the previous failure, whether a new failure appeared, and what exact edge sequence was required.
- Extract the reusable LLM pitfall and express the next system change as a testable hypothesis with a planned side-by-side experiment.

Workspace:
- Project root: `{PROJECT_ROOT}`
- Batch directory: `{rel(batch_dir, PROJECT_ROOT)}`
- Target: `{target_dir.name}`

Inspect the target artifacts on disk. Use this compact summary as an index, not as a substitute for checking the listed files.

Files to inspect:
{file_lines}

Compact summary:
```json
{summary_json}
```

Review protocol:
1. Identify the first meaningful failure that blocked acceptance.
2. Inspect the next repair attempt, including addenda and generated graph changes.
3. Decide whether that repair fixed the original issue.
4. If the target still failed, identify the new failing gate, rule, edge, and reason.
5. Write the exact graph edge sequence that would satisfy one operation per edge.
6. Generalize the observed pitfall into a system-level change.
7. Frame that change as a falsifiable hypothesis and a concrete A/B experiment against the current pipeline.

Return JSON only. No markdown, no prose outside JSON. Match this schema:
```json
{schema_json}
```
"""


def artifact_base(out_dir: Path, target_id: str) -> Path:
    safe_target = target_id.replace("/", "_")
    return out_dir / f"{ARTIFACT_PREFIX}_{safe_target}"


def artifact_path(out_dir: Path, target_id: str, suffix: str) -> Path:
    base = artifact_base(out_dir, target_id)
    return base.parent / f"{base.name}_{suffix}"


def write_prompt(batch_dir: Path, target_id: str, out_dir: Path) -> Path:
    target_dir = find_target_dir(batch_dir, target_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = artifact_path(out_dir, target_dir.name, "prompt.md")
    prompt_path.write_text(build_prompt(batch_dir, target_dir))
    return prompt_path


def codex_command(
    *,
    codex_bin: str,
    model: str,
    reasoning_effort: str,
    sandbox: str,
    output_path: Path,
) -> list[str]:
    cmd = [
        codex_bin,
        "exec",
        "-C",
        str(PROJECT_ROOT),
    ]
    if model:
        cmd += ["--model", model]
    if reasoning_effort:
        cmd += ["-c", f'model_reasoning_effort="{reasoning_effort}"']
    cmd += [
        "--sandbox",
        sandbox,
        "--output-last-message",
        str(output_path),
        "-",
    ]
    return cmd


def parse_json_output(path: Path) -> tuple[bool, str | None]:
    text = read_text(path)
    if text is None:
        return False, "output file missing"
    try:
        json.loads(text)
        return True, None
    except Exception as e:
        return False, str(e)


def tail_text(value: object, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    return text[-limit:]


def run_reviewer(
    prompt_path: Path,
    output_path: Path,
    run_path: Path,
    *,
    codex_bin: str,
    model: str,
    reasoning_effort: str,
    sandbox: str,
    timeout: int,
) -> int:
    output_path.unlink(missing_ok=True)
    cmd = codex_command(
        codex_bin=codex_bin,
        model=model,
        reasoning_effort=reasoning_effort,
        sandbox=sandbox,
        output_path=output_path,
    )
    started = datetime.now(timezone.utc).isoformat()
    prompt = prompt_path.read_text()
    timed_out = False
    timeout_error = None
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        timed_out = True
        timeout_error = str(e)
        proc = subprocess.CompletedProcess(cmd, 124, stdout=e.stdout or "", stderr=e.stderr or "")
    ended = datetime.now(timezone.utc).isoformat()
    output_valid, output_error = parse_json_output(output_path)
    metadata = {
        "started_at": started,
        "ended_at": ended,
        "prompt_path": str(prompt_path),
        "output_path": str(output_path),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "sandbox": sandbox,
        "timeout_s": timeout,
        "timed_out": timed_out,
        "timeout_error": timeout_error,
        "returncode": proc.returncode,
        "output_json_valid": output_valid,
        "output_json_error": output_error,
        "command": cmd,
        "stdout_tail": tail_text(proc.stdout, 2000),
        "stderr_tail": tail_text(proc.stderr, 4000),
    }
    run_path.write_text(json.dumps(metadata, indent=2) + "\n")
    if proc.returncode != 0:
        return proc.returncode
    return 0 if output_valid else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_dir", help="derivations/_evolutions/batches/<batch_id>")
    ap.add_argument("--target-id", "--target", required=True, help="target id, e.g. target_008")
    ap.add_argument("--out-dir", default=None, help="artifact directory; default is batch_dir")
    ap.add_argument("--run", action="store_true", help="run the reviewer model after writing the prompt")
    ap.add_argument("--model", default=os.environ.get("LOG_REVIEW_MODEL", DEFAULT_MODEL))
    ap.add_argument(
        "--reasoning-effort",
        default=os.environ.get("LOG_REVIEW_REASONING_EFFORT", DEFAULT_REASONING_EFFORT),
    )
    ap.add_argument("--sandbox", default=os.environ.get("LOG_REVIEW_SANDBOX", "read-only"))
    ap.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    ap.add_argument("--timeout", type=int, default=int(os.environ.get("LOG_REVIEW_TIMEOUT", "1800")))
    args = ap.parse_args()

    batch_dir = Path(args.batch_dir)
    out_dir = Path(args.out_dir) if args.out_dir else batch_dir
    try:
        target_dir = find_target_dir(batch_dir, args.target_id)
        prompt_path = write_prompt(batch_dir, args.target_id, out_dir)
    except Exception as e:
        print(f"[introspective-log-review] {e}", file=sys.stderr)
        return 2

    output_path = artifact_path(out_dir, target_dir.name, "output.json")
    run_path = artifact_path(out_dir, target_dir.name, "run.json")

    print(f"[introspective-log-review] prompt: {prompt_path}")
    if not args.run:
        print("[introspective-log-review] reviewer not run; pass --run to execute")
        return 0

    rc = run_reviewer(
        prompt_path,
        output_path,
        run_path,
        codex_bin=args.codex_bin,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        sandbox=args.sandbox,
        timeout=args.timeout,
    )
    print(f"[introspective-log-review] output: {output_path}")
    print(f"[introspective-log-review] run: {run_path}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
