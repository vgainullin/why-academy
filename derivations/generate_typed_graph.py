#!/usr/bin/env python3
"""Generate one legacy graph candidate from a public typed task envelope.

This is intentionally a generation-only boundary. It does not run repair,
verification, acceptance, or any bundle workflow. The model sees only the
public display prompt and typed givens, and it runs from a caller-supplied
isolated working directory.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any, Sequence

from config import load_config
from json_inner import PROMPT, ProblemJsonError, problem_from_response, render_json_prompt
from llm_cli import run_prompt, step_engine


PUBLIC_TASK_SCHEMA_VERSION = "derivation_task_public.v1"
GENERATION_METADATA_VERSION = "typed_graph_generation.v1"
PUBLIC_TASK_KEYS = {"schema_version", "id", "task_type", "display", "givens"}
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class PublicTaskError(ValueError):
    """The public task envelope is malformed or outside this generator's scope."""


class GenerationError(RuntimeError):
    """The model call did not produce a usable graph candidate."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicTaskError(message)


def _exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    actual = set(value)
    _require(actual == expected, f"{path} keys must be {sorted(expected)}; got {sorted(actual)}")


def _rational(value: Any, path: str) -> Fraction:
    _require(isinstance(value, dict), f"{path} must be a rational object")
    _exact_keys(value, {"numerator", "denominator"}, path)
    numerator = value["numerator"]
    denominator = value["denominator"]
    _require(
        isinstance(numerator, int) and not isinstance(numerator, bool),
        f"{path}.numerator must be an integer",
    )
    _require(
        isinstance(denominator, int) and not isinstance(denominator, bool),
        f"{path}.denominator must be an integer",
    )
    _require(denominator > 0, f"{path}.denominator must be positive")
    result = Fraction(numerator, denominator)
    _require(
        numerator == result.numerator and denominator == result.denominator,
        f"{path} must be reduced with a positive denominator",
    )
    return result


def validate_public_task(task: Any) -> dict[str, Any]:
    """Validate the strict, answer-free envelope accepted by this generator."""
    _require(isinstance(task, dict), "task must be an object")
    _exact_keys(task, PUBLIC_TASK_KEYS, "task")
    _require(
        task["schema_version"] == PUBLIC_TASK_SCHEMA_VERSION,
        f"schema_version must be {PUBLIC_TASK_SCHEMA_VERSION!r}",
    )
    _require(isinstance(task["id"], str) and TASK_ID_RE.fullmatch(task["id"]) is not None,
             "id must be a filesystem-safe non-empty task id")
    _require(task["task_type"] == "linear_equation", "task_type must be 'linear_equation'")

    display = task["display"]
    _require(isinstance(display, dict), "display must be an object")
    _exact_keys(display, {"prompt"}, "display")
    _require(isinstance(display["prompt"], str) and display["prompt"].strip(),
             "display.prompt must be a non-empty string")

    givens = task["givens"]
    _require(isinstance(givens, dict), "givens must be an object")
    _exact_keys(givens, {"variable", "lhs", "rhs"}, "givens")
    _require(givens["variable"] == "x", "givens.variable must be 'x'")

    sides: dict[str, tuple[Fraction, Fraction]] = {}
    for side_name in ("lhs", "rhs"):
        side = givens[side_name]
        _require(isinstance(side, dict), f"givens.{side_name} must be an object")
        _exact_keys(side, {"coefficient", "constant"}, f"givens.{side_name}")
        sides[side_name] = (
            _rational(side["coefficient"], f"givens.{side_name}.coefficient"),
            _rational(side["constant"], f"givens.{side_name}.constant"),
        )

    _require(
        sides["lhs"][0] != sides["rhs"][0],
        "linear_equation must have exactly one solution",
    )
    return task


def load_public_task(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise PublicTaskError(f"task is not valid JSON: {exc}") from exc
    return validate_public_task(payload)


def public_target_text(task: dict[str, Any]) -> str:
    typed_givens = json.dumps(task["givens"], sort_keys=True, separators=(",", ":"))
    return (
        f"{task['display']['prompt'].strip()}\n\n"
        "Authoritative typed givens (public task data):\n"
        f"{typed_givens}\n"
        "Use these givens exactly when constructing the derivation graph."
    )


def render_model_prompt(task: dict[str, Any]) -> str:
    validate_public_task(task)
    return render_json_prompt(
        PROMPT.read_text(),
        target=public_target_text(task),
        problem_id=task["id"],
    )


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def generate_candidate(
    task: dict[str, Any],
    *,
    output_path: Path,
    metadata_path: Path,
    model_cwd: Path,
    engine: str,
    model: str | None,
    budget: str | None,
    timeout_s: int | float | str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_public_task(task)
    model_cwd = model_cwd.resolve()
    if not model_cwd.is_dir():
        raise GenerationError(f"model cwd is not an existing directory: {model_cwd}")

    output_path = output_path.resolve()
    metadata_path = metadata_path.resolve()
    if output_path == metadata_path:
        raise GenerationError("graph output and metadata output must be different files")

    prompt = render_model_prompt(task)
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        result = run_prompt(
            prompt,
            engine=engine,
            model=model,
            budget=budget,
            timeout_s=timeout_s,
            cwd=model_cwd,
            step="inner",
        )
    except Exception as exc:
        raise GenerationError(f"model generation failed: {type(exc).__name__}: {exc}") from exc
    if result.returncode != 0:
        stderr_tail = (result.stderr or "").strip()[-1000:]
        detail = f"; stderr={stderr_tail}" if stderr_tail else ""
        raise GenerationError(
            f"model generation failed: {engine} exited {result.returncode}{detail}"
        )

    try:
        graph = problem_from_response(result.stdout, problem_id=task["id"])
    except ProblemJsonError as exc:
        raise GenerationError(f"model response was not a strict legacy graph: {exc}") from exc

    graph_bytes = _json_bytes(graph)
    task_bytes = json.dumps(task, sort_keys=True, separators=(",", ":")).encode("utf-8")
    prompt_bytes = prompt.encode("utf-8")
    response_bytes = result.stdout.encode("utf-8")
    completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata = {
        "schema_version": GENERATION_METADATA_VERSION,
        "candidate_only": True,
        "task_id": task["id"],
        "task_type": task["task_type"],
        "problem_id": graph["id"],
        "engine": engine,
        "model": model,
        "model_cwd": str(model_cwd),
        "output_path": str(output_path),
        "task_envelope_sha256": _sha256(task_bytes),
        "prompt_sha256": _sha256(prompt_bytes),
        "response_sha256": _sha256(response_bytes),
        "graph_sha256": _sha256(graph_bytes),
        "started_at": started_at,
        "completed_at": completed_at,
    }

    _atomic_write(output_path, graph_bytes)
    _atomic_write(metadata_path, _json_bytes(metadata))
    return graph, metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, help="strict public task-envelope JSON")
    parser.add_argument("--out", required=True, help="candidate graph JSON output")
    parser.add_argument("--metadata-out", required=True, help="generation metadata JSON output")
    parser.add_argument(
        "--model-cwd",
        required=True,
        help="existing isolated directory used as the model process working directory",
    )
    parser.add_argument("--engine", default=None, help="LLM engine override")
    parser.add_argument("--model", default=None, help="LLM model override")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg, _version = load_config()
    engine = (args.engine or step_engine(cfg, "inner")).strip().lower()
    model = args.model if args.model is not None else cfg.get("models", {}).get("inner")
    model = model or None

    try:
        task_path = Path(args.task).resolve()
        output_path = Path(args.out).resolve()
        metadata_path = Path(args.metadata_out).resolve()
        if task_path in {output_path, metadata_path}:
            raise GenerationError("task input must not be overwritten by an output")
        task = load_public_task(task_path)
        generate_candidate(
            task,
            output_path=output_path,
            metadata_path=metadata_path,
            model_cwd=Path(args.model_cwd),
            engine=engine,
            model=model,
            budget=str(cfg.get("budgets_usd", {}).get("inner", 1)),
            timeout_s=cfg.get("timeouts_s", {}).get("inner", 600),
        )
    except (GenerationError, PublicTaskError, OSError) as exc:
        print(f"[generate_typed_graph] FAIL: {exc}", file=os.sys.stderr)
        return 2

    print(json.dumps({
        "status": "GENERATED",
        "candidate_only": True,
        "task_id": task["id"],
        "output": str(output_path),
        "metadata": str(metadata_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
