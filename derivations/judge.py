#!/usr/bin/env python3
"""Pedagogical quality judge with an adversarial second pass.

Primary pass: the configured engine/model evaluates the graph against the
rubric in prompts/judge_eval.md (deepseek-* models dispatch to
deepseek_judge.py; both backends write the same sidecar schema).

Adversarial pass: when the primary verdict is PASS and adversarial_judge is
enabled in the pipeline config, a second model is prompted to refute the PASS
(prompts/judge_adversarial.md), ideally on a different engine so errors
decorrelate. A validated refutation flips `overall` to FAIL. If the
adversarial pass cannot run, the verdict fails closed (`overall` ERROR)
unless adversarial_judge.fail_mode is "open" -- a PASS that skipped its
second gate must not be silently accepted.

Exit code: 0 iff final `overall` is PASS; 1 if FAIL (including refuted);
2 on wrapper errors (engine failure, unparseable JSON, adversarial error in
fail-closed mode).
"""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from to_canvas import eq_to_latex, parse  # noqa: E402
from config import load_config  # noqa: E402
from llm_cli import LLMEngineError, QuotaExhaustedError, run_prompt, step_engine  # noqa: E402

JUDGE_VERSION = "0.3"
ADVERSARIAL_VERSION = "0.1"
RUBRIC_KEYS = ("one_rule_per_edge", "given_facts_visible", "target_goal_reached")


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


def adversarial_settings(cfg: dict) -> dict:
    section = dict(cfg.get("adversarial_judge") or {})
    model_override = os.environ.get("ADVERSARIAL_JUDGE_MODEL")
    if model_override is not None and model_override.strip().lower() in ("", "default", "none"):
        model = None
    else:
        model = model_override or section.get("model", "anthropic/claude-sonnet-4.6")
    return {
        "enabled": bool(section.get("enabled", False)),
        "engine": os.environ.get("ADVERSARIAL_JUDGE_ENGINE") or section.get("engine", "openrouter"),
        "model": model,
        "budget": str(section.get("budget_usd", cfg.get("budgets_usd", {}).get("judge", 1))),
        "timeout": str(section.get("timeout_s", cfg.get("timeouts_s", {}).get("judge", 180))),
        "fail_mode": section.get("fail_mode", "closed"),
    }


def validate_refutation(parsed: dict) -> tuple[bool, str]:
    """A refutation must be well-formed before it may flip a verdict, and a
    malformed uphold must not silently count as upheld either."""
    if not isinstance(parsed, dict):
        return False, "adversarial verdict must be a JSON object"
    refuted = parsed.get("refuted")
    if not isinstance(refuted, bool):
        return False, "refuted must be a JSON boolean"
    reason = parsed.get("reason")
    if not isinstance(reason, str):
        return False, "reason must be a JSON string"
    if refuted:
        if parsed.get("criterion") not in RUBRIC_KEYS:
            return False, f"refutation must name one rubric criterion from {list(RUBRIC_KEYS)}"
        if not reason.strip():
            return False, "refutation must include a non-empty reason"
    else:
        if parsed.get("criterion") is not None:
            return False, "upheld verdict must set criterion to null"
        if reason.strip():
            return False, "upheld verdict must leave reason empty"
    return True, ""


def apply_adversarial(record: dict, adv: dict) -> dict:
    """Merge an adversarial result into a primary judge record.

    refuted -> overall FAIL; error in fail-closed mode -> overall ERROR
    (never silently keep a PASS that skipped its second gate)."""
    out = dict(record)
    out["primary_overall"] = record.get("overall")
    out["adversarial"] = adv
    status = adv.get("status")
    if status == "refuted":
        out["overall"] = "FAIL"
    elif status == "error" and adv.get("fail_mode", "closed") == "closed":
        out["overall"] = "ERROR"
    return out


def run_adversarial_judge(problem: dict, target: str, record: dict, settings: dict) -> dict:
    base = {
        "adversarial_version": ADVERSARIAL_VERSION,
        "engine": settings["engine"],
        "model": settings["model"],
        "fail_mode": settings["fail_mode"],
    }
    template = (ROOT / "prompts" / "judge_adversarial.md").read_text()
    prompt = (
        template.replace("<<TARGET>>", target)
        .replace("<<GRAPH>>", render_graph(problem))
        .replace("<<PRIMARY_VERDICTS>>", json.dumps(record.get("verdicts"), indent=2))
    )
    try:
        result = run_prompt(
            prompt,
            engine=settings["engine"],
            model=settings["model"],
            budget=settings["budget"],
            timeout_s=settings["timeout"],
        )
    except (QuotaExhaustedError, LLMEngineError) as e:
        return {**base, "status": "error", "error": f"{type(e).__name__}: {e}"}
    if result.returncode != 0:
        return {
            **base,
            "status": "error",
            "error": f"{settings['engine']} exited {result.returncode}",
            "stderr_tail": result.stderr[-300:],
        }
    try:
        parsed = _extract_json(result.stdout)
    except Exception as e:
        return {
            **base,
            "status": "error",
            "error": f"could not parse adversarial JSON: {e}",
            "raw_tail": result.stdout[-300:],
        }
    ok, why = validate_refutation(parsed)
    if not ok:
        return {**base, "status": "error", "error": f"malformed adversarial verdict: {why}", "parsed": parsed}
    if parsed["refuted"]:
        return {**base, "status": "refuted", "criterion": parsed["criterion"], "reason": parsed["reason"].strip()}
    return {**base, "status": "upheld", "reason": str(parsed.get("reason", "")).strip()}


def _run_primary_deepseek(problem_path: Path, target: str, model: str, timeout: str, out_suffix: str) -> int:
    cmd = [
        sys.executable,
        str(ROOT / "deepseek_judge.py"),
        str(problem_path),
        "--target",
        target,
        "--model",
        model,
        "--out-suffix",
        out_suffix,
    ]
    try:
        result = subprocess.run(cmd, timeout=int(timeout) + 30)
    except subprocess.TimeoutExpired:
        print(f"[judge] deepseek timed out after {timeout}s", file=sys.stderr)
        return 2
    return result.returncode


def main() -> int:
    cfg, cfg_version = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("problem", help="path to derivations/problems/<id>.json")
    ap.add_argument("--target", required=True, help="original target passed to the inner-loop run")
    ap.add_argument("--engine", default=step_engine(cfg, "judge"), help="LLM engine: claude, codex, or deepseek")
    ap.add_argument("--model", default=cfg["models"]["judge"], help="model alias")
    ap.add_argument("--budget", default=str(cfg["budgets_usd"]["judge"]), help="--max-budget-usd")
    ap.add_argument("--timeout", default=str(cfg["timeouts_s"]["judge"]), help="seconds")
    ap.add_argument("--out-suffix", default=".judge.json")
    ap.add_argument("--no-adversarial", action="store_true",
                    help="skip the adversarial second pass (e.g. to calibrate the primary judge alone)")
    args = ap.parse_args()

    problem_path = Path(args.problem)
    problem = json.loads(problem_path.read_text())
    pid = problem["id"]
    sidecar = problem_path.with_name(problem_path.stem + args.out_suffix)

    if args.engine == "deepseek" or args.model.startswith("deepseek"):
        rc = _run_primary_deepseek(problem_path, args.target, args.model, args.timeout, args.out_suffix)
        if rc not in (0, 1) or not sidecar.exists():
            return 2
        record = json.loads(sidecar.read_text())
        record["config_version"] = cfg_version
    else:
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
            print(f"[judge] could not parse JSON from {args.engine} output: {e}", file=sys.stderr)
            print(f"[judge] raw output (last 500 chars):\n{raw[-500:]}", file=sys.stderr)
            return 2
        record = {
            "problem_id": pid,
            "judge_version": JUDGE_VERSION,
            "config_version": cfg_version,
            "backend": args.engine,
            "model": args.model,
            "target": args.target,
            "verdicts": {k: parsed_json.get(k) for k in RUBRIC_KEYS},
            "overall": parsed_json.get("overall", "FAIL"),
        }

    settings = adversarial_settings(cfg)
    run_adv = settings["enabled"] and not args.no_adversarial
    if not run_adv:
        record["adversarial"] = {"status": "disabled" if not settings["enabled"] else "skipped"}
    elif record.get("overall") == "PASS":
        adv = run_adversarial_judge(problem, args.target, record, settings)
        record = apply_adversarial(record, adv)
    else:
        record["adversarial"] = {"status": "not_run", "reason": "primary verdict was not PASS"}
    sidecar.write_text(json.dumps(record, indent=2))

    print(f"JUDGE: {pid}")
    for k in RUBRIC_KEYS:
        v = record.get("verdicts", {}).get(k) or {}
        print(f"  {k:22s}{v.get('verdict', '?'):6s}  {v.get('reason', '')}")
    adv = record.get("adversarial", {})
    if adv.get("status") in ("refuted", "upheld", "error"):
        detail = adv.get("reason") or adv.get("error") or ""
        print(f"  adversarial:          {adv['status'].upper():6s}  {detail}")
    overall = record.get("overall", "FAIL")
    print(f"  OVERALL:              {overall}")

    if overall == "ERROR":
        return 2
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
