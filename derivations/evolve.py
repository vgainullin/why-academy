#!/usr/bin/env python3
"""Prompt evolution step.

Given a failed iteration (current variant prompt + structured failure
diagnosis), produces a SHORT addendum section intended to be appended to the
next iteration's prompt. The legacy judge-only mode is still accepted.

Output: the addendum text written to --out (default: stdout).
Exit:   0 on success; 1 if the LLM signalled CONTRADICTION_DETECTED or output
        was otherwise unusable; 2 on wrapper error (timeout, claude failure).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "prompts" / "evolve_prompt.md"
REPAIR_TEMPLATE = ROOT / "prompts" / "repair_prompt.md"

sys.path.insert(0, str(ROOT))
from config import load_config  # noqa: E402
from llm_cli import LLMEngineError, QuotaExhaustedError, run_prompt, step_engine  # noqa: E402


def build_evolve_prompt(
    *,
    target: str,
    current_variant: str,
    iteration: int,
    diagnosis: dict | None = None,
    judge: dict | None = None,
) -> str:
    if diagnosis is not None:
        template = REPAIR_TEMPLATE.read_text()
        return (template
                .replace("<<TARGET>>", target)
                .replace("<<DIAGNOSIS>>", json.dumps(diagnosis, indent=2))
                .replace("<<CURRENT_VARIANT>>", current_variant)
                .replace("<<ITERATION>>", str(iteration + 1)))
    if judge is not None:
        judge_text = json.dumps(judge.get("verdicts", judge), indent=2)
        template = TEMPLATE.read_text()
        return (template
                .replace("<<TARGET>>", target)
                .replace("<<JUDGE>>", judge_text)
                .replace("<<CURRENT_VARIANT>>", current_variant)
                .replace("<<ITERATION>>", str(iteration + 1)))
    raise ValueError("either diagnosis or judge is required")


def normalize_addendum(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def validate_addendum(text: str) -> tuple[bool, str | None]:
    if text.startswith("CONTRADICTION DETECTED"):
        return False, f"addendum rejected by evolve task: {text}"
    if not text.startswith("## Addendum"):
        return False, "output missing '## Addendum' header; treating as unusable"
    return True, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--judge", default=None, help="legacy: path to <problem>.judge.json from the failed iteration")
    ap.add_argument("--diagnosis", default=None, help="path to failure_diagnosis.json")
    ap.add_argument("--current-variant", required=True, help="path to the prompt the failed iteration used")
    ap.add_argument("--iteration", type=int, required=True, help="iteration index of the FAILED attempt (0-based)")
    ap.add_argument("--out", default="-", help="output path or '-' for stdout")
    cfg, _ = load_config()
    ap.add_argument("--engine", default=step_engine(cfg, "evolve"), help="LLM engine: claude or codex")
    ap.add_argument("--model", default=cfg["models"]["evolve"])
    ap.add_argument("--budget", default=str(cfg["budgets_usd"]["evolve"]))
    ap.add_argument("--timeout", default=str(cfg["timeouts_s"]["evolve"]))
    args = ap.parse_args()

    current_variant = Path(args.current_variant).read_text()

    if args.diagnosis:
        diagnosis = json.loads(Path(args.diagnosis).read_text())
        prompt = build_evolve_prompt(
            target=args.target,
            current_variant=current_variant,
            iteration=args.iteration,
            diagnosis=diagnosis,
        )
    elif args.judge:
        judge = json.loads(Path(args.judge).read_text())
        prompt = build_evolve_prompt(
            target=args.target,
            current_variant=current_variant,
            iteration=args.iteration,
            judge=judge,
        )
    else:
        print("[evolve] either --diagnosis or --judge is required", file=sys.stderr)
        return 2

    try:
        result = run_prompt(
            prompt,
            engine=args.engine,
            model=args.model,
            budget=args.budget,
            timeout_s=args.timeout,
        )
    except QuotaExhaustedError as e:
        print(f"[evolve] quota exhausted: {e}", file=sys.stderr)
        return 75
    except LLMEngineError as e:
        print(f"[evolve] {e}", file=sys.stderr)
        return 2
    if result.returncode != 0:
        print(f"[evolve] {args.engine} exited {result.returncode}", file=sys.stderr)
        print(result.stderr[-500:], file=sys.stderr)
        return 2

    text = normalize_addendum(result.stdout)
    ok, reason = validate_addendum(text)
    if not ok:
        print(f"[evolve] {reason}", file=sys.stderr)
        print(f"[evolve] raw (first 300):\n{text[:300]}", file=sys.stderr)
        return 1

    if args.out == "-":
        print(text)
    else:
        Path(args.out).write_text(text + "\n")
        print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
