#!/usr/bin/env python3
"""Run one self-contained review packet through Codex and OpenRouter Fusion."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import introspective_log_review as ilr


ARTIFACT_PREFIX = "reviewer_parity"


def artifact_path(out_dir: Path, target_id: str, suffix: str) -> Path:
    safe_target = target_id.replace("/", "_")
    return out_dir / f"{ARTIFACT_PREFIX}_{safe_target}_{suffix}"


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception as e:
        return {"_error": str(e), "_path": str(path)}


def write_packet(batch_dir: Path, target_id: str, out_dir: Path) -> tuple[Path, str]:
    target_dir = ilr.find_target_dir(batch_dir, target_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt = ilr.build_prompt(batch_dir, target_dir, inline_files=True)
    packet_path = artifact_path(out_dir, target_dir.name, "packet.md")
    packet_path.write_text(prompt)
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return packet_path, prompt_sha256


def run_pair(
    *,
    packet_path: Path,
    target_id: str,
    out_dir: Path,
    codex_model: str,
    codex_reasoning_effort: str,
    fusion_model: str,
    timeout: int,
    codex_bin: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="reviewer-parity-codex-") as tmp:
        codex_cwd = Path(tmp)
        codex_output = artifact_path(out_dir, target_id, "codex_output.json")
        codex_run = artifact_path(out_dir, target_id, "codex_run.json")
        codex_rc = ilr.run_reviewer(
            packet_path,
            codex_output,
            codex_run,
            engine="codex",
            codex_bin=codex_bin,
            model=codex_model,
            reasoning_effort=codex_reasoning_effort,
            sandbox="read-only",
            timeout=timeout,
            codex_cwd=codex_cwd,
            codex_packet_only=True,
        )

    fusion_output = artifact_path(out_dir, target_id, "fusion_output.json")
    fusion_run = artifact_path(out_dir, target_id, "fusion_run.json")
    fusion_rc = ilr.run_reviewer(
        packet_path,
        fusion_output,
        fusion_run,
        engine="openrouter",
        codex_bin=codex_bin,
        model=fusion_model,
        reasoning_effort="",
        sandbox="read-only",
        timeout=timeout,
    )

    codex_meta = read_json(codex_run)
    fusion_meta = read_json(fusion_run)
    prompt_hashes_match = (
        codex_meta.get("prompt_sha256")
        and codex_meta.get("prompt_sha256") == fusion_meta.get("prompt_sha256")
    )
    comparison = {
        "packet_path": str(packet_path),
        "target_id": target_id,
        "prompt_sha256": codex_meta.get("prompt_sha256"),
        "prompt_hashes_match": bool(prompt_hashes_match),
        "codex": {
            "model": codex_model,
            "reasoning_effort": codex_reasoning_effort,
            "returncode": codex_rc,
            "output_path": str(codex_output),
            "run_path": str(codex_run),
            "output_json_valid": codex_meta.get("output_json_valid"),
            "cwd": codex_meta.get("cwd"),
            "packet_only": codex_meta.get("codex_packet_only"),
        },
        "fusion": {
            "model": fusion_model,
            "returncode": fusion_rc,
            "output_path": str(fusion_output),
            "run_path": str(fusion_run),
            "output_json_valid": fusion_meta.get("output_json_valid"),
        },
    }
    comparison_path = artifact_path(out_dir, target_id, "comparison.json")
    comparison_path.write_text(json.dumps(comparison, indent=2) + "\n")
    comparison["comparison_path"] = str(comparison_path)
    return comparison


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch_dir")
    ap.add_argument("--target-id", "--target", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--codex-model", default=ilr.DEFAULT_MODEL)
    ap.add_argument("--codex-reasoning-effort", default=ilr.DEFAULT_REASONING_EFFORT)
    ap.add_argument("--fusion-model", default=ilr.DEFAULT_OPENROUTER_MODEL)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--codex-bin", default="codex")
    args = ap.parse_args()

    batch_dir = Path(args.batch_dir)
    out_dir = Path(args.out_dir)
    packet_path, prompt_sha256 = write_packet(batch_dir, args.target_id, out_dir)
    comparison = run_pair(
        packet_path=packet_path,
        target_id=args.target_id,
        out_dir=out_dir,
        codex_model=args.codex_model,
        codex_reasoning_effort=args.codex_reasoning_effort,
        fusion_model=args.fusion_model,
        timeout=args.timeout,
        codex_bin=args.codex_bin,
    )
    comparison["packet_prompt_sha256"] = prompt_sha256
    print(json.dumps(comparison, indent=2))
    return 0 if comparison["prompt_hashes_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
