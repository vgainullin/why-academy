#!/usr/bin/env python3
"""Per-target evolution loop, driven by a shared LLM worker pool.

Replaces the per-target subprocess (inner_with_evolution.sh) with an in-process
function that submits prompts to the pool. Each target's evolution iterations
all run through an engine-specific pool. Claude reuses long-running sessions;
Codex reuses persisted `codex exec` threads through `codex exec resume`.

API:
    from inner_evolve import process_target
    result = process_target(target, target_index, batch_id, pool, max_iter=3)

The function writes the same on-disk artifacts as the old shell wrapper:
    derivations/_evolutions/batches/<batch_id>/targets/target_<i>/
      target.json
      iter_<n>/
        variant.md, rendered_prompt.md, problem.json (+ sidecars), addendum.md
        status.txt
      ACCEPTED.txt | FAILED.txt
      target_metrics.json
"""
from __future__ import annotations
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))
from claude_worker import QuotaExhaustedError as ClaudeQuotaExhaustedError  # noqa: E402
from evolution_memory import find_seed_variant  # noqa: E402
from evolve import build_evolve_prompt, normalize_addendum, validate_addendum  # noqa: E402
from failure_diagnosis import diagnose_iter  # noqa: E402
from json_inner import (  # noqa: E402
    ProblemJsonError,
    append_addenda_unique,
    adapt_seed_variant,
    problem_from_response,
    render_json_prompt,
)
from llm_cli import QuotaExhaustedError as LLMQuotaExhaustedError  # noqa: E402
from transition_score import write_transition  # noqa: E402


def _safe_batch_id(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", s)


def _write_target_metrics(target_dir: Path, target_index: int) -> dict:
    iters = sorted(target_dir.glob("iter_*"))
    statuses = []
    for it in iters:
        s = (it / "status.txt").read_text().strip() if (it / "status.txt").exists() else "missing"
        statuses.append([it.name, s])
    accepted = (target_dir / "ACCEPTED.txt").exists()
    accepted_at = None
    if accepted:
        accepted_at = int((target_dir / "ACCEPTED.txt").read_text().strip().replace("iter_", ""))
    first_try_pass = statuses[0][1] == "PASS" if statuses else False
    failure_reason = None
    if not accepted and (target_dir / "FAILED.txt").exists():
        failure_reason = (target_dir / "FAILED.txt").read_text().strip()
    metrics = {
        "target_index": target_index,
        "n_iterations": len(iters),
        "accepted": accepted,
        "accepted_at_iter": accepted_at,
        "first_try_pass": first_try_pass,
        "iter_statuses": statuses,
        "failure_reason": failure_reason,
    }
    (target_dir / "target_metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


def _run_py(*args, cwd=None) -> subprocess.CompletedProcess:
    py = os.environ.get("DERIVATION_PYTHON") or sys.executable
    return subprocess.run([py, *args], cwd=str(cwd or PROJECT_ROOT),
                          capture_output=True, text=True)


def _verifier_says_fail(verifier_path: Path) -> bool:
    try:
        d = json.loads(verifier_path.read_text())
        es = d.get("edge_summary", {})
        return (es.get("FAIL", 0) + es.get("ERROR", 0)) > 0
    except Exception:
        return True


def _judge_overall(judge_path: Path) -> str:
    try:
        return json.loads(judge_path.read_text()).get("overall", "ERROR")
    except Exception:
        return "ERROR"


def _write_failure_diagnosis(iter_dir: Path, gate: str) -> Path:
    diagnosis = diagnose_iter(iter_dir, gate)
    out = iter_dir / "failure_diagnosis.json"
    out.write_text(json.dumps(diagnosis, indent=2))
    return out


def _clear_problem_sidecars(iter_dir: Path) -> None:
    for name in (
        "problem.verifier.json",
        "problem.canvas_check.json",
        "problem.target_check.json",
        "problem.judge.json",
        "problem.canvas.json",
        "problem.raw.json",
        "problem.raw.verifier.json",
    ):
        (iter_dir / name).unlink(missing_ok=True)


def _write_transition_if_possible(target_dir: Path, it: int) -> None:
    if it <= 0:
        return
    prev_dir = target_dir / f"iter_{it - 1:02d}"
    this_dir = target_dir / f"iter_{it:02d}"
    if (prev_dir / "status.txt").exists() and (this_dir / "status.txt").exists():
        write_transition(prev_dir, this_dir)


def _load_prompt_addenda() -> tuple[str, list[str]]:
    paths = [
        Path(p)
        for p in os.environ.get("DERIVATION_PROMPT_ADDENDA", "").split(os.pathsep)
        if p.strip()
    ]
    chunks = []
    loaded = []
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text().strip()
        if not text:
            continue
        chunks.append(text)
        loaded.append(str(path))
    return "\n\n".join(chunks), loaded


def _evolve_next_variant(target: str, target_dir: Path, iter_dir: Path, it: int,
                         diagnosis_path: Path, evolve_engine: str,
                         evolve_model: str, pool=None) -> tuple[bool, str | None]:
    next_dir = target_dir / f"iter_{it + 1:02d}"
    next_dir.mkdir(exist_ok=True)
    addendum_path = next_dir / "addendum.md"

    reuse_evolve_pool = os.environ.get("EVOLVE_REUSE_POOL", "0").strip().lower() in (
        "1", "true", "yes", "on"
    )
    can_reuse_pool = (
        reuse_evolve_pool
        and pool is not None
        and getattr(pool, "engine", None) == evolve_engine
        and getattr(pool, "model", None) == evolve_model
    )
    if can_reuse_pool:
        diagnosis = json.loads(diagnosis_path.read_text())
        prompt = build_evolve_prompt(
            target=target,
            current_variant=(iter_dir / "variant.md").read_text(),
            iteration=it,
            diagnosis=diagnosis,
        )
        response = pool.submit(prompt)
        raw = response.get("text", "")
        text = normalize_addendum(raw)
        ok, reason = validate_addendum(text)
        (iter_dir / "evolve.log").write_text(raw)
        (iter_dir / "evolve_result_event.json").write_text(json.dumps({
            "engine": evolve_engine,
            "model": evolve_model,
            "via": "reused_pool",
            "session_id": response.get("session_id"),
            "turn_count": response.get("turn_count"),
            "saturation": response.get("saturation"),
            "needs_rotation": response.get("needs_rotation"),
            "result": response.get("result", {}),
        }, indent=2))
        if not ok:
            (iter_dir / "status.txt").write_text("evolve_fail")
            (iter_dir / "evolve.log").write_text(
                raw + f"\n\n[evolve] {reason}\n[evolve] raw (first 300):\n{text[:300]}\n"
            )
            return False, f"evolve_fail_iter_{it}"
        addendum_path.write_text(text + "\n")
    else:
        started = time.time()
        ev = _run_py("derivations/evolve.py",
                     "--target", target,
                     "--diagnosis", str(diagnosis_path),
                     "--current-variant", str(iter_dir / "variant.md"),
                     "--iteration", str(it),
                     "--out", str(addendum_path),
                     "--engine", evolve_engine,
                     "--model", evolve_model)
        (iter_dir / "evolve.log").write_text(ev.stdout + ev.stderr)
        (iter_dir / "evolve_result_event.json").write_text(json.dumps({
            "engine": evolve_engine,
            "model": evolve_model,
            "via": "subprocess",
            "returncode": ev.returncode,
            "duration_ms": int((time.time() - started) * 1000),
            "result": {
                "usage": None,
                "resumed": False,
            },
        }, indent=2))
        if ev.returncode == 75:
            raise LLMQuotaExhaustedError("quota exhausted during evolve")
        if ev.returncode != 0 or not addendum_path.exists():
            (iter_dir / "status.txt").write_text("evolve_fail")
            return False, f"evolve_fail_iter_{it}"

    next_variant = next_dir / "variant.md"
    with next_variant.open("w") as out:
        out.write((iter_dir / "variant.md").read_text())
        out.write("\n")
        out.write(addendum_path.read_text())
    return True, None


def process_target(target: str, target_index: int, batch_id: str, pool,
                   *, max_iter: int = 3,
                   inner_engine: str = "claude",
                   inner_mode: str = "agent",
                   judge_engine: str = "claude",
                   evolve_engine: str = "claude",
                   judge_model: str = "sonnet",
                   evolve_model: str = "sonnet") -> dict:
    """Run one target through up to max_iter generation+judge+evolve iterations.

    `pool` must expose .submit(user_text)->dict.

    Resumable: if target_metrics.json already exists for this (batch_id, target_index),
    return it without re-running. Callers can rerun batch.sh against the same
    --batch-id to pick up where a previous interrupted run left off.
    """
    safe_bid = _safe_batch_id(batch_id)
    evo_base = PROJECT_ROOT / "derivations" / "_evolutions" / "batches" / batch_id
    target_dir = evo_base / "targets" / f"target_{target_index:03d}"
    target_dir.mkdir(parents=True, exist_ok=True)

    # Resumability: skip targets that already completed in a prior run of the
    # same batch_id (whether PASS or fail). The marker is target_metrics.json
    # AND ACCEPTED.txt or FAILED.txt -- those guarantee the per-target loop
    # finished cleanly. Partial state (iter dirs but no final marker) is
    # treated as incomplete and the target re-runs from scratch.
    existing_metrics = target_dir / "target_metrics.json"
    accepted = target_dir / "ACCEPTED.txt"
    failed = target_dir / "FAILED.txt"
    if existing_metrics.exists() and (accepted.exists() or failed.exists()):
        return json.loads(existing_metrics.read_text())

    # batch-level checkpoint (only the first target to land writes this; race-safe enough)
    checkpoint = evo_base / "checkpoint.json"
    if not checkpoint.exists():
        state = json.loads((PROJECT_ROOT / "derivations" / "state.json").read_text())
        checkpoint.write_text(json.dumps({
            "batch_id": batch_id,
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "epoch": state["epoch"],
            "prompt_version": state["prompt_version"],
            "validator_version": state["validator_version"],
            "config_version": state.get("config_version", "v1"),
            "max_iter": max_iter,
            "inner_via": f"{inner_engine}_worker_pool",
            "inner_mode": inner_mode,
            "inner_engine": inner_engine,
            "inner_model": getattr(pool, "model", "unknown"),
            "judge_engine": judge_engine,
            "judge_model": judge_model,
            "evolve_engine": evolve_engine,
            "evolve_model": evolve_model,
            "validator_dirs": os.environ.get("DERIVATION_VALIDATOR_DIRS", ""),
            "validator_prepend": os.environ.get("DERIVATION_VALIDATOR_PREPEND", ""),
            "prompt_addenda": os.environ.get("DERIVATION_PROMPT_ADDENDA", ""),
        }, indent=2))

    (target_dir / "target.json").write_text(json.dumps({
        "target": target,
        "batch_id": batch_id,
        "target_index": target_index,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }, indent=2))

    if inner_mode == "json":
        canonical_prompt = PROJECT_ROOT / "derivations" / "prompts" / "generate_derivation_json.md"
    else:
        canonical_prompt = PROJECT_ROOT / "derivations" / "prompts" / "generate_derivation.md"
    base_prompt_text = canonical_prompt.read_text()
    prompt_addenda, prompt_addenda_sources = _load_prompt_addenda()
    variant_prompt_path = canonical_prompt
    if prompt_addenda:
        base_prompt_text = append_addenda_unique(base_prompt_text, prompt_addenda)
        repaired_prompt_path = target_dir / "prompt_with_capability_repairs.md"
        repaired_prompt_path.write_text(base_prompt_text)
        (target_dir / "prompt_addenda_sources.json").write_text(json.dumps(prompt_addenda_sources, indent=2))
        variant_prompt_path = repaired_prompt_path
    seed = find_seed_variant(target, current_batch_id=batch_id)
    if seed:
        seed_variant_path = target_dir / "seed_variant.md"
        if inner_mode == "json":
            seed_text = Path(seed["variant_path"]).read_text()
            seed_variant_path.write_text(adapt_seed_variant(base_prompt_text, seed_text))
        else:
            seed_text = Path(seed["variant_path"]).read_text()
            if prompt_addenda:
                seed_variant_path.write_text(append_addenda_unique(seed_text, prompt_addenda))
            else:
                shutil.copy(Path(seed["variant_path"]), seed_variant_path)
        (target_dir / "seed_variant.json").write_text(json.dumps(seed, indent=2))
        variant_prompt_path = seed_variant_path
    accepted_iter = None
    fail_reason = None

    for it in range(max_iter):
        iter_dir = target_dir / f"iter_{it:02d}"
        iter_dir.mkdir(exist_ok=True)

        # Snapshot the variant being used this iter
        if variant_prompt_path != iter_dir / "variant.md":
            shutil.copy(variant_prompt_path, iter_dir / "variant.md")

        problem_id = f"evo_{safe_bid}_t{target_index:03d}_i{it:02d}"

        # Defensively clear any stale canonical artifacts under this id
        for stale in (PROJECT_ROOT / "derivations" / "problems").glob(f"{problem_id}.*"):
            stale.unlink(missing_ok=True)

        rendered = (iter_dir / "variant.md").read_text()
        if inner_mode == "json":
            rendered = render_json_prompt(rendered, target=target, problem_id=problem_id)
        else:
            rendered = rendered.replace("<<TARGET>>", target).replace("<<PROBLEM_ID>>", problem_id)
        (iter_dir / "rendered_prompt.md").write_text(rendered)

        # Generate via the worker pool (long-running session)
        try:
            response = pool.submit(rendered)
        except (ClaudeQuotaExhaustedError, LLMQuotaExhaustedError):
            raise
        except Exception as e:
            (iter_dir / "status.txt").write_text(f"worker_error: {type(e).__name__}: {e}")
            fail_reason = f"worker_error_iter_{it}"
            break

        # Persist the worker's verbatim text reply for audit / debugging
        (iter_dir / "console.log").write_text(response.get("text", ""))
        # Capture per-turn usage / saturation
        result_event = response.get("result", {})
        (iter_dir / "result_event.json").write_text(json.dumps({
            "saturation": response.get("saturation"),
            "turn_count": response.get("turn_count"),
            "needs_rotation": response.get("needs_rotation"),
            "session_id": response.get("session_id"),
            "usage": result_event.get("usage"),
            "duration_ms": result_event.get("duration_ms"),
            "duration_api_ms": result_event.get("duration_api_ms"),
            "total_cost_usd": result_event.get("total_cost_usd"),
            "thread_id": result_event.get("thread_id"),
            "resumed": result_event.get("resumed"),
        }, indent=2))

        if inner_mode == "json":
            try:
                problem = problem_from_response(response.get("text", ""), problem_id=problem_id)
            except ProblemJsonError as e:
                (iter_dir / "problem_parse_error.json").write_text(json.dumps({
                    "error": str(e),
                    "raw": response.get("text", ""),
                }, indent=2))
                (iter_dir / "status.txt").write_text("problem_invalid")
                fail_reason = f"problem_invalid_iter_{it}"
                _write_transition_if_possible(target_dir, it)
                if it + 1 < max_iter:
                    diagnosis_path = _write_failure_diagnosis(iter_dir, "runtime")
                    ok, reason = _evolve_next_variant(target, target_dir, iter_dir, it,
                                                      diagnosis_path, evolve_engine, evolve_model,
                                                      pool=pool)
                    if not ok:
                        fail_reason = reason
                        break
                    variant_prompt_path = target_dir / f"iter_{it + 1:02d}" / "variant.md"
                    continue
                break
            (iter_dir / "problem.json").write_text(json.dumps(problem, indent=2) + "\n")
        else:
            # The LLM was instructed to write the problem to derivations/problems/<id>.json.
            # If it didn't, that's a generation failure.
            canon_problem = PROJECT_ROOT / "derivations" / "problems" / f"{problem_id}.json"
            if not canon_problem.exists():
                (iter_dir / "status.txt").write_text("problem_missing")
                fail_reason = f"problem_missing_iter_{it}"
                break

            # Move LLM outputs from canonical to iter workspace
            canon_verifier = PROJECT_ROOT / "derivations" / "problems" / f"{problem_id}.verifier.json"
            shutil.move(str(canon_problem), str(iter_dir / "problem.json"))
            if canon_verifier.exists():
                shutil.move(str(canon_verifier), str(iter_dir / "problem.verifier.json"))

        _clear_problem_sidecars(iter_dir)
        shutil.copy(iter_dir / "problem.json", iter_dir / "problem.raw.json")

        # Verify the raw generated graph first. Normalization is a presentation
        # pre-pass for canvas/target/judge, not a way to hide invalid edges.
        verifier_sidecar = iter_dir / "problem.verifier.json"
        verify_res = _run_py("derivations/verify.py", str(iter_dir / "problem.json"))
        (iter_dir / "verify_raw.log").write_text(verify_res.stdout + verify_res.stderr)
        if not verifier_sidecar.exists():
            (iter_dir / "status.txt").write_text("verifier_didnt_run")
            fail_reason = f"verifier_didnt_run_iter_{it}"
            break

        if _verifier_says_fail(verifier_sidecar):
            (iter_dir / "verify.log").write_text(verify_res.stdout + verify_res.stderr)
            (iter_dir / "status.txt").write_text("verify_fail")
            fail_reason = f"verify_fail_iter_{it}"
            _write_transition_if_possible(target_dir, it)
            if it + 1 < max_iter:
                diagnosis_path = _write_failure_diagnosis(iter_dir, "verify")
                ok, reason = _evolve_next_variant(target, target_dir, iter_dir, it,
                                                  diagnosis_path, evolve_engine, evolve_model,
                                                  pool=pool)
                if not ok:
                    fail_reason = reason
                    break
                variant_prompt_path = target_dir / f"iter_{it + 1:02d}" / "variant.md"
                continue
            break
        shutil.copy(verifier_sidecar, iter_dir / "problem.raw.verifier.json")

        normalize_res = _run_py("derivations/graph_normalize.py", str(iter_dir / "problem.json"))
        (iter_dir / "graph_normalize.log").write_text(normalize_res.stdout + normalize_res.stderr)
        if normalize_res.returncode != 0:
            (iter_dir / "status.txt").write_text("normalize_fail")
            fail_reason = f"normalize_fail_iter_{it}"
            _write_transition_if_possible(target_dir, it)
            if it + 1 < max_iter:
                diagnosis_path = _write_failure_diagnosis(iter_dir, "runtime")
                ok, reason = _evolve_next_variant(target, target_dir, iter_dir, it,
                                                  diagnosis_path, evolve_engine, evolve_model,
                                                  pool=pool)
                if not ok:
                    fail_reason = reason
                    break
                variant_prompt_path = target_dir / f"iter_{it + 1:02d}" / "variant.md"
                continue
            break

        verify_res = _run_py("derivations/verify.py", str(iter_dir / "problem.json"))
        (iter_dir / "verify.log").write_text(verify_res.stdout + verify_res.stderr)
        if not verifier_sidecar.exists():
            (iter_dir / "status.txt").write_text("verifier_didnt_run")
            fail_reason = f"verifier_didnt_run_iter_{it}"
            break

        if _verifier_says_fail(verifier_sidecar):
            (iter_dir / "status.txt").write_text("verify_fail")
            fail_reason = f"verify_fail_iter_{it}"
            _write_transition_if_possible(target_dir, it)
            if it + 1 < max_iter:
                diagnosis_path = _write_failure_diagnosis(iter_dir, "verify")
                ok, reason = _evolve_next_variant(target, target_dir, iter_dir, it,
                                                  diagnosis_path, evolve_engine, evolve_model,
                                                  pool=pool)
                if not ok:
                    fail_reason = reason
                    break
                variant_prompt_path = target_dir / f"iter_{it + 1:02d}" / "variant.md"
                continue
            break

        # canvas_check
        canvas_res = _run_py("derivations/canvas_check.py", str(iter_dir / "problem.json"))
        (iter_dir / "canvas_check.log").write_text(canvas_res.stdout + canvas_res.stderr)
        if canvas_res.returncode != 0:
            (iter_dir / "status.txt").write_text("canvas_fail")
            fail_reason = f"canvas_fail_iter_{it}"
            _write_transition_if_possible(target_dir, it)
            if it + 1 < max_iter:
                diagnosis_path = _write_failure_diagnosis(iter_dir, "canvas")
                ok, reason = _evolve_next_variant(target, target_dir, iter_dir, it,
                                                  diagnosis_path, evolve_engine, evolve_model,
                                                  pool=pool)
                if not ok:
                    fail_reason = reason
                    break
                variant_prompt_path = target_dir / f"iter_{it + 1:02d}" / "variant.md"
                continue
            break

        # to_canvas on success
        _run_py("derivations/to_canvas.py", str(iter_dir / "problem.json"))

        target_res = _run_py("derivations/target_check.py",
                             str(iter_dir / "problem.json"),
                             "--target", target)
        (iter_dir / "target_check.log").write_text(target_res.stdout + target_res.stderr)
        if target_res.returncode != 0:
            (iter_dir / "status.txt").write_text("target_fail")
            fail_reason = f"target_fail_iter_{it}"
            _write_transition_if_possible(target_dir, it)
            if it + 1 < max_iter:
                diagnosis_path = _write_failure_diagnosis(iter_dir, "target")
                ok, reason = _evolve_next_variant(target, target_dir, iter_dir, it,
                                                  diagnosis_path, evolve_engine, evolve_model,
                                                  pool=pool)
                if not ok:
                    fail_reason = reason
                    break
                variant_prompt_path = target_dir / f"iter_{it + 1:02d}" / "variant.md"
                continue
            break

        # judge -- judge.py dispatches deepseek-* models internally and runs
        # the adversarial second pass on PASS verdicts (config: adversarial_judge),
        # so every caller goes through the same hardened gate.
        judge_res = _run_py("derivations/judge.py",
                            str(iter_dir / "problem.json"),
                            "--target", target,
                            "--engine", judge_engine,
                            "--model", judge_model)
        (iter_dir / "judge.log").write_text(judge_res.stdout + judge_res.stderr)
        judge_sidecar = iter_dir / "problem.judge.json"
        overall = _judge_overall(judge_sidecar)

        if overall != "PASS":
            (iter_dir / "status.txt").write_text(overall)
            _write_transition_if_possible(target_dir, it)
            fail_reason = f"judge_fail_iter_{it}"
            # Judge FAIL: evolve if we have budget
            if it + 1 < max_iter:
                diagnosis_path = _write_failure_diagnosis(iter_dir, "judge")
                ok, reason = _evolve_next_variant(target, target_dir, iter_dir, it,
                                                  diagnosis_path, evolve_engine, evolve_model,
                                                  pool=pool)
                if not ok:
                    fail_reason = reason
                    break
                variant_prompt_path = target_dir / f"iter_{it + 1:02d}" / "variant.md"
                continue
            break

        (iter_dir / "status.txt").write_text("PASS")
        _write_transition_if_possible(target_dir, it)
        if overall == "PASS":
            accepted_iter = f"iter_{it:02d}"
            break

    if accepted_iter:
        (target_dir / "ACCEPTED.txt").write_text(accepted_iter)
    else:
        (target_dir / "FAILED.txt").write_text(fail_reason or "exhausted")

    return _write_target_metrics(target_dir, target_index)
