#!/usr/bin/env python3
"""DeepSeek-based pedagogical judge.

Same rubric (prompts/judge_eval.md) as the Claude judge, called via the
OpenAI-compatible DeepSeek API. Output schema identical to judge.py so
side-by-side comparison is straightforward.

Env: DEEPSEEK_API_KEY must be set.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from to_canvas import eq_to_latex, parse  # noqa: E402

JUDGE_VERSION = "0.2-deepseek"
DEFAULT_MODEL = "deepseek-v4-flash"   # reasoning ON; `deepseek-chat` aliases to flash but disables reasoning
BASE_URL = "https://api.deepseek.com"


def render_graph(problem: dict) -> str:
    parsed = {n["id"]: parse(n["sympy_srepr"]) for n in problem["nodes"]}
    lines = ["Nodes:"]
    for n in problem["nodes"]:
        nid = n["id"]
        marker = "  (root)" if nid == problem["root_node"] else ("  (goal)" if nid == problem["goal_node"] else "")
        lines.append(f"  {nid}: {eq_to_latex(parsed[nid])}{marker}")
    lines.append("")
    lines.append("Edges:")
    for e in problem["edges"]:
        args = e.get("rule_args") or {}
        args_str = " " + json.dumps(args) if args else ""
        lines.append(f"  {e['from']} -> {e['to']}  via {e['rule']}{args_str}")
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("problem", help="path to derivations/problems/<id>.json")
    ap.add_argument("--target", required=True)
    ap.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL))
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--out-suffix", default=".judge_deepseek.json",
                    help="sidecar suffix (default .judge_deepseek.json so it doesn't collide with the Claude judge sidecar)")
    args = ap.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("[judge_deepseek] FAIL: DEEPSEEK_API_KEY not set", file=sys.stderr)
        return 2

    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=BASE_URL, timeout=args.timeout)

    problem_path = Path(args.problem)
    problem = json.loads(problem_path.read_text())
    pid = problem["id"]
    template = (ROOT / "prompts" / "judge_eval.md").read_text()
    prompt = template.replace("<<TARGET>>", args.target).replace("<<GRAPH>>", render_graph(problem))

    try:
        resp = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
    except Exception as e:
        print(f"[judge_deepseek] API call failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    raw = resp.choices[0].message.content or ""
    try:
        parsed_json = _extract_json(raw)
    except Exception as e:
        print(f"[judge_deepseek] JSON parse failed: {e}", file=sys.stderr)
        print(f"[judge_deepseek] raw (first 400):\n{raw[:400]}", file=sys.stderr)
        return 2

    overall = parsed_json.get("overall", "FAIL")
    usage = getattr(resp, "usage", None)
    record = {
        "problem_id": pid,
        "judge_version": JUDGE_VERSION,
        "model": args.model,
        "backend": "deepseek",
        "target": args.target,
        "verdicts": {
            k: parsed_json.get(k)
            for k in ("one_rule_per_edge", "given_facts_visible", "target_goal_reached")
        },
        "overall": overall,
        "usage": {
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
        } if usage else None,
    }
    sidecar = problem_path.with_name(problem_path.stem + args.out_suffix)
    sidecar.write_text(json.dumps(record, indent=2))

    print(f"JUDGE (deepseek/{args.model}): {pid}")
    for k in ("one_rule_per_edge", "given_facts_visible", "target_goal_reached"):
        v = parsed_json.get(k, {})
        print(f"  {k:25s}  {v.get('verdict','?'):6s}  {v.get('reason','')[:100]}")
    print(f"  OVERALL: {overall}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
