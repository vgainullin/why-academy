#!/usr/bin/env python3
"""CLI wrapper around llm_cli.run_prompt."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from llm_cli import LLMEngineError, QuotaExhaustedError, run_prompt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="codex")
    ap.add_argument("--model", default=None)
    ap.add_argument("--budget", default=None)
    ap.add_argument("--timeout", default=None)
    ap.add_argument("--prompt-file", required=True)
    args = ap.parse_args()

    prompt = Path(args.prompt_file).read_text()
    try:
        result = run_prompt(
            prompt,
            engine=args.engine,
            model=args.model,
            budget=args.budget,
            timeout_s=args.timeout,
        )
    except QuotaExhaustedError as e:
        print(f"[llm] quota exhausted: {e}", file=sys.stderr)
        return 75
    except LLMEngineError as e:
        print(f"[llm] {e}", file=sys.stderr)
        return 2

    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
