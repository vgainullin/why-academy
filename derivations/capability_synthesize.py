#!/usr/bin/env python3
"""Ask an LLM to synthesize a candidate validator package for a proposal."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "prompts" / "capability_synthesis.md"
sys.path.insert(0, str(ROOT))
from capability_eval import evaluate  # noqa: E402
from config import load_config  # noqa: E402
from llm_cli import LLMEngineError, QuotaExhaustedError, run_prompt, step_engine  # noqa: E402


def extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def write_candidate(proposal_dir: Path, payload: dict) -> None:
    candidate_dir = proposal_dir / "candidate"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    if payload.get("reject"):
        for stale in ("validator.py", "tests.json", "synthesis.json", "eval.json"):
            (candidate_dir / stale).unlink(missing_ok=True)
        (candidate_dir / "rejected.json").write_text(json.dumps(payload, indent=2) + "\n")
        return
    (candidate_dir / "rejected.json").unlink(missing_ok=True)
    validator_py = payload.get("validator_py")
    tests = payload.get("tests")
    if not isinstance(validator_py, str) or not validator_py.strip():
        raise ValueError("LLM output missing non-empty validator_py")
    if not isinstance(tests, dict):
        raise ValueError("LLM output missing tests object")
    (candidate_dir / "validator.py").write_text(validator_py.strip() + "\n")
    (candidate_dir / "tests.json").write_text(json.dumps(tests, indent=2) + "\n")
    (candidate_dir / "synthesis.json").write_text(json.dumps(payload, indent=2) + "\n")


def render_prompt(proposal_dir: Path) -> str:
    proposal_path = proposal_dir / "proposal.json"
    if not proposal_path.exists():
        raise FileNotFoundError(f"missing {proposal_path}")
    if not TEMPLATE.exists():
        raise FileNotFoundError(f"missing {TEMPLATE}")
    prompt = TEMPLATE.read_text().replace("<<CAPABILITY_PROPOSAL_JSON>>", proposal_path.read_text())
    (proposal_dir / "synthesis_prompt.md").write_text(prompt)
    return prompt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("proposal_dir")
    cfg, _ = load_config()
    ap.add_argument("--engine", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--budget", default=None)
    ap.add_argument("--timeout", default=None)
    ap.add_argument("--no-eval", action="store_true")
    args = ap.parse_args()

    proposal_dir = Path(args.proposal_dir)
    try:
        prompt = render_prompt(proposal_dir)
    except FileNotFoundError as e:
        print(f"[capability_synthesize] {e}", file=sys.stderr)
        return 2

    engine = args.engine or step_engine(cfg, "implement")
    model = args.model or cfg["models"]["implement"]
    budget = args.budget or str(cfg["budgets_usd"]["implement"])
    timeout = args.timeout or str(cfg["timeouts_s"]["implement"])

    try:
        result = run_prompt(
            prompt,
            engine=engine,
            model=model,
            budget=budget,
            timeout_s=timeout,
        )
    except QuotaExhaustedError as e:
        print(f"[capability_synthesize] quota exhausted: {e}", file=sys.stderr)
        return 75
    except LLMEngineError as e:
        print(f"[capability_synthesize] {e}", file=sys.stderr)
        return 2
    if result.returncode != 0:
        print(f"[capability_synthesize] {engine} exited {result.returncode}", file=sys.stderr)
        print((result.stderr or result.stdout)[-800:], file=sys.stderr)
        return 2

    raw_path = proposal_dir / "candidate" / "synthesis_raw.txt"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(result.stdout)
    try:
        payload = extract_json(result.stdout)
        write_candidate(proposal_dir, payload)
    except Exception as e:
        print(f"[capability_synthesize] could not materialize candidate: {e}", file=sys.stderr)
        return 2

    if payload.get("reject"):
        print(json.dumps(payload, indent=2))
        return 1

    if args.no_eval:
        print(f"[capability_synthesize] wrote candidate under {proposal_dir / 'candidate'}")
        return 0

    rc, eval_payload = evaluate(proposal_dir)
    (proposal_dir / "candidate" / "eval.json").write_text(json.dumps(eval_payload, indent=2) + "\n")
    print(json.dumps(eval_payload, indent=2))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
