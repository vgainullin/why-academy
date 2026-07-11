#!/usr/bin/env python3
"""Frozen-supervisor pilot for typed Grade 8 derivation tasks.

The candidate process receives only a public task envelope and emits one graph.
This supervisor, executed from an operator-pinned clean checkout, owns the task
bundle, mathematical gates, pedagogical gates, and atomic acceptance records.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


DERIVATIONS = Path(__file__).resolve().parent
ORACLE_ROOT = DERIVATIONS.parent
PUBLIC_TASK_VERSION = "derivation_task_public.v1"
RUN_VERSION = "typed_derivation_pilot.v1"
ACCEPTANCE_VERSION = "typed_derivation_acceptance.v1"


class TypedPilotError(ValueError):
    """The trusted pilot configuration or provenance is invalid."""


def _sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()
    return _sha256_bytes(raw)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as handle:
        tmp = Path(handle.name)
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def read_task_ids(path: Path) -> list[str]:
    ids = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not ids:
        raise TypedPilotError("task queue is empty")
    if len(ids) != len(set(ids)):
        raise TypedPilotError("task queue contains duplicate task ids")
    for task_id in ids:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task_id):
            raise TypedPilotError(f"invalid task id: {task_id!r}")
    return ids


def public_task_envelope(contract: dict[str, Any]) -> dict[str, Any]:
    """Return the only task data exposed to the candidate/model."""
    if contract.get("task_type") != "linear_equation":
        raise TypedPilotError("typed pilot currently supports linear_equation only")
    expected = contract.get("expected")
    if not isinstance(expected, dict) or expected.get("cardinality") != "one":
        raise TypedPilotError("typed pilot currently supports one-solution equations only")
    return {
        "schema_version": PUBLIC_TASK_VERSION,
        "id": contract["id"],
        "task_type": contract["task_type"],
        "display": {"prompt": contract["display"]["prompt"]},
        "givens": copy.deepcopy(contract["givens"]),
    }


def _git_output(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise TypedPilotError(f"git {' '.join(args)} failed for {root}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def oracle_provenance(expected_commit: str, *, allow_dirty: bool = False) -> dict[str, Any]:
    actual_commit = _git_output(ORACLE_ROOT, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        raise TypedPilotError(
            f"oracle commit mismatch: expected {expected_commit}, found {actual_commit}"
        )
    status = _git_output(ORACLE_ROOT, "status", "--porcelain", "--untracked-files=all")
    if status and not allow_dirty:
        raise TypedPilotError("oracle checkout is dirty; run from a clean frozen worktree")
    return {
        "root": str(ORACLE_ROOT.resolve()),
        "commit": actual_commit,
        "dirty": bool(status),
    }


def candidate_provenance(root: Path) -> dict[str, Any]:
    try:
        commit = _git_output(root, "rev-parse", "HEAD")
        dirty = bool(_git_output(root, "status", "--porcelain", "--untracked-files=all"))
    except TypedPilotError:
        commit, dirty = None, None
    return {"root": str(root.resolve()), "commit": commit, "dirty": dirty}


def _trusted_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "DERIVATION_VALIDATOR_DIRS": "",
        "DERIVATION_VALIDATOR_PREPEND": "",
        "DERIVATION_PROMPT_ADDENDA": "",
        "EVOLVE_REUSE_POOL": "0",
        "CODEX_REUSE_SESSION": "0",
    })
    return env


def _run_logged(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
    timeout: int,
) -> tuple[int | None, str | None]:
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(
            f"# started: {started}\n# timeout_s: {timeout}\n\n"
            f"{exc.stdout or ''}{exc.stderr or ''}"
        )
        return None, f"timed out after {timeout}s"
    log_path.write_text(
        f"# started: {started}\n# returncode: {proc.returncode}\n"
        f"# command: {json.dumps(cmd)}\n\nSTDOUT\n{proc.stdout}\nSTDERR\n{proc.stderr}"
    )
    return proc.returncode, None


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except Exception as exc:
        raise TypedPilotError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise TypedPilotError(f"{path.name} must contain a JSON object")
    return value


def _gate_status(returncode: int | None, sidecar: Path) -> tuple[str, list[str]]:
    if returncode is None:
        return "ERROR", ["gate timed out"]
    if not sidecar.exists():
        return "ERROR", ["gate wrote no sidecar"]
    if returncode == 0:
        return "PASS", []
    if returncode == 1:
        return "FAIL", ["gate rejected submission"]
    return "ERROR", [f"gate exited {returncode}"]


def _final_status(gates: dict[str, dict[str, Any]]) -> str:
    statuses = {gate.get("status") for gate in gates.values()}
    if "ERROR" in statuses:
        return "ERROR"
    if statuses == {"PASS"}:
        return "PASS"
    return "FAIL"


def _stable_run_fields(run: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in run.items() if key not in {"started_at"}}


def _prepare_run_dir(out_dir: Path, run_record: dict[str, Any], *, resume: bool) -> None:
    run_path = out_dir / "run.json"
    if run_path.exists():
        if not resume:
            raise TypedPilotError(f"run already exists at {out_dir}; pass --resume")
        prior = _read_json_object(run_path)
        if _stable_run_fields(prior) != _stable_run_fields(run_record):
            raise TypedPilotError("resume provenance does not match frozen run configuration")
        return
    if out_dir.exists() and any(out_dir.iterdir()):
        raise TypedPilotError(f"refusing non-empty output directory without run.json: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(run_path, run_record)


def _task_from_store(store: Any, task_id: str) -> dict[str, Any]:
    for method_name in ("get", "task", "get_task"):
        method = getattr(store, method_name, None)
        if callable(method):
            task = method(task_id)
            if isinstance(task, dict):
                return task
            contract = getattr(task, "contract", None)
            if isinstance(contract, dict):
                return copy.deepcopy(contract)
    raise TypedPilotError("FrozenTaskStore does not expose a task lookup method")


def _selected_digest(store: Any, task_ids: list[str]) -> str:
    method = getattr(store, "selected_task_list_digest", None)
    if callable(method):
        return str(method(task_ids))
    return _canonical_digest(task_ids)


def _evaluate_equation(contract: dict[str, Any], graph: dict[str, Any], verifier: dict[str, Any]) -> dict[str, Any]:
    from typed_linear_equation_oracle import evaluate_typed_linear_equation

    return evaluate_typed_linear_equation(contract, graph, verifier)


def run_task(
    *,
    contract: dict[str, Any],
    task_index: int,
    out_dir: Path,
    candidate_root: Path,
    candidate_python: str,
    trusted_python: str,
    engine: str,
    model: str,
    judge_engine: str,
    judge_model: str,
    generation_timeout: int,
    gate_timeout: int,
    run_record: dict[str, Any],
    resume: bool,
) -> dict[str, Any]:
    task_id = contract["id"]
    task_dir = out_dir / "tasks" / f"task_{task_index:03d}_{task_id}"
    workspace = task_dir / "candidate_workspace"
    task_dir.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    acceptance_path = task_dir / "acceptance.json"
    acceptance_path.unlink(missing_ok=True)

    public_path = workspace / "public_task.json"
    _atomic_json(public_path, public_task_envelope(contract))
    submission_path = task_dir / "submission.json"
    generation_metadata_path = task_dir / "generation.json"
    generator_log = task_dir / "generator.log"
    generation_gate: dict[str, Any]

    if resume and submission_path.exists():
        generation_gate = {"status": "PASS", "mode": "resume_re_evaluate"}
    else:
        generator = candidate_root / "derivations" / "generate_typed_graph.py"
        if not generator.exists():
            generation_gate = {
                "status": "ERROR",
                "reasons": [f"candidate generator missing: {generator}"],
            }
        else:
            cmd = [
                candidate_python,
                str(generator),
                "--task",
                str(public_path),
                "--out",
                str(submission_path),
                "--metadata-out",
                str(generation_metadata_path),
                "--model-cwd",
                str(workspace),
                "--engine",
                engine,
                "--model",
                model,
            ]
            rc, error = _run_logged(
                cmd,
                cwd=candidate_root,
                env=_trusted_env(),
                log_path=generator_log,
                timeout=generation_timeout,
            )
            reasons = [error] if error else []
            if rc not in (0, None):
                reasons.append(f"candidate generator exited {rc}")
            if not submission_path.exists():
                reasons.append("candidate generator wrote no submission")
            if not generation_metadata_path.exists():
                reasons.append("candidate generator wrote no generation metadata")
            generation_gate = {
                "status": "PASS" if not reasons else "ERROR",
                "mode": "one_shot_no_repair",
                "returncode": rc,
                "reasons": reasons,
            }

    gates: dict[str, dict[str, Any]] = {"generation": generation_gate}
    reasons = list(generation_gate.get("reasons") or [])
    graph_sha256 = None

    if generation_gate["status"] == "PASS":
        try:
            graph_sha256 = _sha256_path(submission_path)
            graph = _read_json_object(submission_path)
        except Exception as exc:
            gates["typed_oracle"] = {"status": "ERROR", "reasons": [str(exc)]}
            reasons.append(str(exc))
        else:
            for suffix in (".verifier.json", ".canvas_check.json", ".judge.json"):
                submission_path.with_name(submission_path.stem + suffix).unlink(missing_ok=True)

            verifier_path = submission_path.with_name(submission_path.stem + ".verifier.json")
            verify_rc, verify_error = _run_logged(
                [trusted_python, str(DERIVATIONS / "verify.py"), str(submission_path)],
                cwd=ORACLE_ROOT,
                env=_trusted_env(),
                log_path=task_dir / "verify.log",
                timeout=gate_timeout,
            )
            verifier_status, verifier_reasons = _gate_status(verify_rc, verifier_path)
            if verify_error:
                verifier_reasons.append(verify_error)
            gates["verifier"] = {
                "status": verifier_status,
                "returncode": verify_rc,
                "reasons": verifier_reasons,
            }
            reasons.extend(verifier_reasons)

            if verifier_path.exists():
                try:
                    verifier = _read_json_object(verifier_path)
                    oracle_result = _evaluate_equation(contract, graph, verifier)
                except Exception as exc:
                    oracle_result = {"status": "ERROR", "reasons": [f"oracle raised: {exc}"]}
            else:
                oracle_result = {"status": "ERROR", "reasons": ["missing verifier evidence"]}
            gates["typed_oracle"] = oracle_result
            reasons.extend(oracle_result.get("reasons") or [])

            if verifier_status == "PASS" and oracle_result.get("status") == "PASS":
                canvas_path = submission_path.with_name(submission_path.stem + ".canvas_check.json")
                canvas_rc, canvas_error = _run_logged(
                    [trusted_python, str(DERIVATIONS / "canvas_check.py"), str(submission_path)],
                    cwd=ORACLE_ROOT,
                    env=_trusted_env(),
                    log_path=task_dir / "canvas.log",
                    timeout=gate_timeout,
                )
                canvas_status, canvas_reasons = _gate_status(canvas_rc, canvas_path)
                if canvas_error:
                    canvas_reasons.append(canvas_error)
                gates["canvas"] = {
                    "status": canvas_status,
                    "returncode": canvas_rc,
                    "reasons": canvas_reasons,
                }
                reasons.extend(canvas_reasons)

                if canvas_status == "PASS":
                    judge_path = submission_path.with_name(submission_path.stem + ".judge.json")
                    judge_rc, judge_error = _run_logged(
                        [
                            trusted_python,
                            str(DERIVATIONS / "judge.py"),
                            str(submission_path),
                            "--target",
                            contract["display"]["prompt"],
                            "--engine",
                            judge_engine,
                            "--model",
                            judge_model,
                        ],
                        cwd=ORACLE_ROOT,
                        env=_trusted_env(),
                        log_path=task_dir / "judge.log",
                        timeout=max(gate_timeout, 420),
                    )
                    judge_status, judge_reasons = _gate_status(judge_rc, judge_path)
                    judge_record = None
                    if judge_path.exists():
                        try:
                            judge_record = _read_json_object(judge_path)
                        except TypedPilotError as exc:
                            judge_status = "ERROR"
                            judge_reasons.append(str(exc))
                    if judge_status == "PASS" and (
                        not isinstance(judge_record, dict)
                        or judge_record.get("overall") != "PASS"
                        or (judge_record.get("adversarial") or {}).get("status") != "upheld"
                    ):
                        judge_status = "ERROR"
                        judge_reasons.append("judge PASS lacked an upheld adversarial verdict")
                    if judge_error:
                        judge_reasons.append(judge_error)
                    gates["judge"] = {
                        "status": judge_status,
                        "returncode": judge_rc,
                        "overall": judge_record.get("overall") if isinstance(judge_record, dict) else None,
                        "adversarial_status": (
                            (judge_record.get("adversarial") or {}).get("status")
                            if isinstance(judge_record, dict)
                            else None
                        ),
                        "reasons": judge_reasons,
                    }
                    reasons.extend(judge_reasons)

            current_hash = _sha256_path(submission_path)
            if current_hash != graph_sha256:
                gates["graph_immutability"] = {
                    "status": "ERROR",
                    "reasons": ["submission changed while trusted gates were running"],
                }
                reasons.append("submission changed while trusted gates were running")
            else:
                gates["graph_immutability"] = {"status": "PASS", "reasons": []}

    status = _final_status(gates)
    acceptance = {
        "schema_version": ACCEPTANCE_VERSION,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": status,
        "task_id": task_id,
        "task_index": task_index,
        "contract_digest": contract["contract_digest"],
        "bundle_sha256": run_record["bundle_sha256"],
        "selected_task_list_sha256": run_record["selected_task_list_sha256"],
        "oracle_commit": run_record["oracle"]["commit"],
        "evaluator_version": run_record["evaluator_version"],
        "graph_sha256": graph_sha256,
        "gates": gates,
        "reasons": list(dict.fromkeys(reason for reason in reasons if reason)),
    }
    _atomic_json(acceptance_path, acceptance)
    return acceptance


def main(argv: list[str] | None = None) -> int:
    from frozen_task_store import FrozenTaskStore
    from typed_linear_equation_oracle import EVALUATOR_VERSION

    parser = argparse.ArgumentParser()
    parser.add_argument("queue", help="newline-delimited frozen task IDs")
    parser.add_argument("--bundle", required=True, help="full frozen task bundle")
    parser.add_argument("--bundle-sha256", required=True, help="operator-pinned bundle byte hash")
    parser.add_argument("--expected-oracle-commit", required=True)
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--candidate-python", default=sys.executable)
    parser.add_argument("--trusted-python", default=sys.executable)
    parser.add_argument("--engine", default="codex")
    parser.add_argument("--model", required=True, help="explicit generation model for reproducibility")
    parser.add_argument("--judge-engine", default="deepseek")
    parser.add_argument("--judge-model", default="deepseek-v4-flash")
    parser.add_argument("--generation-timeout", type=int, default=900)
    parser.add_argument("--gate-timeout", type=int, default=240)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-dirty-oracle", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    bundle = Path(args.bundle).resolve()
    queue = Path(args.queue).resolve()
    candidate_root = Path(args.candidate_root).resolve()
    out_dir = Path(args.out).resolve()
    task_ids = read_task_ids(queue)
    oracle = oracle_provenance(
        args.expected_oracle_commit,
        allow_dirty=args.allow_dirty_oracle,
    )
    store = FrozenTaskStore.load(bundle, args.bundle_sha256)
    contracts = [_task_from_store(store, task_id) for task_id in task_ids]
    for contract in contracts:
        public_task_envelope(contract)

    normalized_bundle_sha256 = "sha256:" + store.bundle_sha256
    run_record = {
        "schema_version": RUN_VERSION,
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "oracle": oracle,
        "evaluator_version": EVALUATOR_VERSION,
        "bundle_path": str(bundle),
        "bundle_sha256": normalized_bundle_sha256,
        "queue_path": str(queue),
        "task_ids": task_ids,
        "selected_task_list_sha256": _selected_digest(store, task_ids),
        "candidate": candidate_provenance(candidate_root),
        "generation": {
            "mode": "one_shot_no_repair",
            "engine": args.engine,
            "model": args.model,
            "candidate_python": args.candidate_python,
        },
        "judge": {"engine": args.judge_engine, "model": args.judge_model},
    }
    _prepare_run_dir(out_dir, run_record, resume=args.resume)

    results = []
    for index, contract in enumerate(contracts):
        result = run_task(
            contract=contract,
            task_index=index,
            out_dir=out_dir,
            candidate_root=candidate_root,
            candidate_python=args.candidate_python,
            trusted_python=args.trusted_python,
            engine=args.engine,
            model=args.model,
            judge_engine=args.judge_engine,
            judge_model=args.judge_model,
            generation_timeout=args.generation_timeout,
            gate_timeout=args.gate_timeout,
            run_record=run_record,
            resume=args.resume,
        )
        results.append(result)
        print(f"[typed-pilot] {result['status']:5s} {contract['id']}", file=sys.stderr)

    counts = {status: sum(result["status"] == status for result in results) for status in ("PASS", "FAIL", "ERROR")}
    summary = {
        "schema_version": RUN_VERSION,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "task_count": len(results),
        "counts": counts,
        "all_passed": counts["PASS"] == len(results),
        "results": [
            {
                "task_id": result["task_id"],
                "status": result["status"],
                "acceptance": str(
                    out_dir
                    / "tasks"
                    / f"task_{result['task_index']:03d}_{result['task_id']}"
                    / "acceptance.json"
                ),
            }
            for result in results
        ],
    }
    _atomic_json(out_dir / "summary.json", summary)
    print(json.dumps(summary["counts"], sort_keys=True))
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
