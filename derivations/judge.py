#!/usr/bin/env python3
"""Pedagogical quality judge.

Invokes a cheap LLM model against the rubric in prompts/judge_eval.md.
Reads the problem JSON, renders each node to LaTeX, builds the graph block, fills
the prompt's <<TARGET>> and <<GRAPH>> placeholders, calls the configured engine, parses the
returned JSON, and writes <problem>.judge.json next to the problem.

Exit code: 0 iff `overall` is "PASS"; 1 if FAIL; 2 on any wrapper error (claude
non-zero, JSON unparseable, etc.) -- wrapper errors are distinct from FAIL so
inner.sh can decide whether to treat them as gate failures.
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from to_canvas import eq_to_latex, parse  # noqa: E402
from config import load_config  # noqa: E402
from llm_cli import LLMEngineError, QuotaExhaustedError, run_prompt, step_engine  # noqa: E402

JUDGE_VERSION = "0.2"


def render_graph(problem: dict) -> str:
    parsed = {n["id"]: parse(n["sympy_srepr"]) for n in problem["nodes"]}
    lines = ["Nodes:"]
    for n in problem["nodes"]:
        nid = n["id"]
        ltx = eq_to_latex(parsed[nid])
        marker = ""
        if nid == problem["root_node"]:
            marker = "  (root)"
        elif nid == problem["goal_node"]:
            marker = "  (goal)"
        lines.append(f"  {nid}: {ltx}{marker}")
    lines.append("")
    lines.append("Edges:")
    for e in problem["edges"]:
        args = e.get("rule_args") or {}
        args_str = " " + json.dumps(args) if args else ""
        lines.append(f"  {e['from']} -> {e['to']}  via {e['rule']}{args_str}")
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of `text`, tolerating code fences / extra prose."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def main() -> int:
    cfg, cfg_version = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("problem", help="path to derivations/problems/<id>.json")
    ap.add_argument("--target", required=True, help="original target passed to the inner-loop run")
    ap.add_argument("--engine", default=step_engine(cfg, "judge"), help="LLM engine: claude or codex")
    ap.add_argument("--model", default=cfg["models"]["judge"], help="claude model alias")
    ap.add_argument("--budget", default=str(cfg["budgets_usd"]["judge"]), help="--max-budget-usd")
    ap.add_argument("--timeout", default=str(cfg["timeouts_s"]["judge"]), help="seconds")
    args = ap.parse_args()

    problem_path = Path(args.problem)
    problem = json.loads(problem_path.read_text())
    pid = problem["id"]

    if args.engine == "deepseek" or args.model.startswith("deepseek"):
        cmd = [
            sys.executable,
            str(ROOT / "deepseek_judge.py"),
            str(problem_path),
            "--target",
            args.target,
            "--model",
            args.model,
            "--out-suffix",
            ".judge.json",
        ]
        try:
            result = subprocess.run(cmd, timeout=int(args.timeout) + 30)
        except subprocess.TimeoutExpired:
            print(f"[judge] deepseek timed out after {args.timeout}s", file=sys.stderr)
            return 2
        return result.returncode

    template = (ROOT / "prompts" / "judge_eval.md").read_text()
    prompt = template.replace("<<TARGET>>", args.target).replace("<<GRAPH>>", render_graph(problem))

    try:
        result = run_prompt(
            prompt,
            engine=args.engine,
            model=args.model,
            budget=args.budget,
            timeout_s=args.timeout,
        )
    except QuotaExhaustedError as e:
        print(f"[judge] quota exhausted: {e}", file=sys.stderr)
        return 2
    except LLMEngineError as e:
        print(f"[judge] {e}", file=sys.stderr)
        return 2

    if result.returncode != 0:
        print(f"[judge] {args.engine} exited {result.returncode}", file=sys.stderr)
        print(result.stderr[-500:], file=sys.stderr)
        return 2

    raw = result.stdout
    try:
        parsed_json = _extract_json(raw)
    except Exception as e:
        print(f"[judge] could not parse JSON from claude output: {e}", file=sys.stderr)
        print(f"[judge] raw output (last 500 chars):\n{raw[-500:]}", file=sys.stderr)
        return 2

    overall = parsed_json.get("overall", "FAIL")

    record = {
        "problem_id": pid,
        "judge_version": JUDGE_VERSION,
        "config_version": cfg_version,
        "backend": args.engine,
        "model": args.model,
        "target": args.target,
        "verdicts": {
            k: parsed_json.get(k)
            for k in ("one_rule_per_edge", "given_facts_visible", "target_goal_reached")
        },
        "overall": overall,
    }
    sidecar = problem_path.with_name(problem_path.stem + ".judge.json")
    sidecar.write_text(json.dumps(record, indent=2))

    print(f"JUDGE: {pid}")
    print(f"  one_rule_per_edge:    {parsed_json.get('one_rule_per_edge', {}).get('verdict', '?'):6s}  "
          f"{parsed_json.get('one_rule_per_edge', {}).get('reason', '')}")
    print(f"  given_facts_visible:  {parsed_json.get('given_facts_visible', {}).get('verdict', '?'):6s}  "
          f"{parsed_json.get('given_facts_visible', {}).get('reason', '')}")
    print(f"  target_goal_reached:  {parsed_json.get('target_goal_reached', {}).get('verdict', '?'):6s}  "
          f"{parsed_json.get('target_goal_reached', {}).get('reason', '')}")
    print(f"  OVERALL:              {overall}")

    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
