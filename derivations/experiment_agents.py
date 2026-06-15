#!/usr/bin/env python3
"""Render reusable headless-agent gate prompts for derivation experiments."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
ROLE_DIR = ROOT / "experiment_agent_roles"
MANIFEST_PATH = ROLE_DIR / "manifest.json"
DEFAULT_OUT_ROOT = ROOT / "_evolutions" / "experiment_agents"
PLACEHOLDER_RE = re.compile(r"{{[A-Z0-9_]+}}")

HEADLESS_CONTRACT = """\
## Headless Contract

- Do not request permissions or approvals.
- Do not run commands that require escalation or interactive confirmation.
- If a needed command would require approval, skip it and report the exact
  command, why it was needed, and what evidence is missing.
- Do not commit unless explicitly asked.

"""


@dataclass(frozen=True)
class RenderContext:
    experiment_id: str
    hypothesis: str
    repo_root: Path
    worktree: str
    prototype_worktree: str
    evidence_paths: list[str]


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text())


def role_ids(manifest: dict[str, Any]) -> list[str]:
    return list(manifest.get("roles", {}))


def expand_roles(manifest: dict[str, Any], requested: list[str] | None) -> list[str]:
    groups = manifest.get("groups", {})
    roles = manifest.get("roles", {})
    if not requested:
        requested = ["prebuild"]

    expanded: list[str] = []
    for item in requested:
        names = groups.get(item, [item])
        for name in names:
            if name not in roles:
                raise ValueError(f"unknown experiment agent role or group: {name}")
            if name not in expanded:
                expanded.append(name)
    return expanded


def evidence_block(paths: list[str]) -> str:
    if not paths:
        return "- No evidence paths supplied."
    return "\n".join(f"- `{path}`" for path in paths)


def render_template(text: str, ctx: RenderContext) -> str:
    values = {
        "EXPERIMENT_ID": ctx.experiment_id,
        "HYPOTHESIS": ctx.hypothesis,
        "REPO_ROOT": str(ctx.repo_root),
        "WORKTREE": ctx.worktree,
        "PROTOTYPE_WORKTREE": ctx.prototype_worktree,
        "EVIDENCE_PATHS": evidence_block(ctx.evidence_paths),
    }
    out = text
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", value)
    unresolved = sorted(set(PLACEHOLDER_RE.findall(out)))
    if unresolved:
        raise ValueError(f"unresolved placeholders: {unresolved}")
    return HEADLESS_CONTRACT + out


def render_role(manifest: dict[str, Any], role_id: str, ctx: RenderContext) -> tuple[str, dict[str, Any]]:
    role = manifest["roles"][role_id]
    template_path = ROLE_DIR / role["template"]
    prompt = render_template(template_path.read_text(), ctx)
    metadata = {
        "role_id": role_id,
        "agent_type": role.get("agent_type"),
        "phase": role.get("phase"),
        "expected_output": role.get("output"),
        "template": str(template_path.relative_to(PROJECT_ROOT)),
    }
    return prompt, metadata


def write_packet(ctx: RenderContext, roles: list[str], out_dir: Path) -> dict[str, Any]:
    manifest = load_manifest()
    prompts_dir = out_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    rendered_roles = []
    for role_id in roles:
        prompt, metadata = render_role(manifest, role_id, ctx)
        prompt_path = prompts_dir / f"{role_id}.md"
        prompt_path.write_text(prompt)
        rendered_roles.append({**metadata, "prompt_path": str(prompt_path)})

    packet = {
        "schema_version": "experiment_agent_packet.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment_id": ctx.experiment_id,
        "hypothesis": ctx.hypothesis,
        "repo_root": str(ctx.repo_root),
        "worktree": ctx.worktree,
        "prototype_worktree": ctx.prototype_worktree,
        "evidence_paths": ctx.evidence_paths,
        "roles": rendered_roles,
    }
    (out_dir / "packet.json").write_text(json.dumps(packet, indent=2) + "\n")
    return packet


def cmd_list_roles() -> int:
    manifest = load_manifest()
    for role_id, role in manifest["roles"].items():
        print(f"{role_id}\t{role.get('phase')}\t{role.get('agent_type')}\t{role.get('output')}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    try:
        roles = expand_roles(manifest, args.role)
    except ValueError as e:
        print(f"[experiment-agents] {e}", file=sys.stderr)
        return 2

    out_root = Path(args.out_root) if args.out_root else DEFAULT_OUT_ROOT
    out_dir = Path(args.out_dir) if args.out_dir else (out_root / args.experiment_id)
    ctx = RenderContext(
        experiment_id=args.experiment_id,
        hypothesis=args.hypothesis,
        repo_root=PROJECT_ROOT,
        worktree=args.worktree,
        prototype_worktree=args.prototype_worktree or "",
        evidence_paths=args.evidence or [],
    )
    packet = write_packet(ctx, roles, out_dir)
    print(json.dumps({
        "packet": str(out_dir / "packet.json"),
        "roles": [
            {"role_id": role["role_id"], "prompt_path": role["prompt_path"]}
            for role in packet["roles"]
        ],
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-roles")

    render = sub.add_parser("render")
    render.add_argument("--experiment-id", required=True)
    render.add_argument("--hypothesis", required=True)
    render.add_argument("--worktree", required=True)
    render.add_argument("--prototype-worktree", default="")
    render.add_argument("--evidence", action="append", default=[])
    render.add_argument("--role", action="append", default=None,
                        help="role or group to render; default: prebuild")
    render.add_argument("--out-root", default=None)
    render.add_argument("--out-dir", default=None)

    args = parser.parse_args()
    if args.cmd == "list-roles":
        return cmd_list_roles()
    if args.cmd == "render":
        return cmd_render(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
