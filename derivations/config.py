#!/usr/bin/env python3
"""Pipeline config loader.

Single source of truth for which model / budget / timeout / max_iter / parallelism
applies to each step. The version is declared in state.json (`config_version`);
the file lives at configs/<version>.json.

CLI:
  config.py version              -> prints current config_version
  config.py get models.inner     -> prints "opus"  (any dotted path)
  config.py shell-export         -> emits one-line `export CONFIG_*=...` per leaf

Convention: leaves are exported as CONFIG_<SECTION>_<KEY>, uppercased, with
dotted path joined by underscores.  models.inner -> CONFIG_MODELS_INNER

Env override pattern in callers:
  eval "$(derivations/config.py shell-export)"
  INNER_MODEL="${INNER_MODEL:-$CONFIG_MODELS_INNER}"
  INNER_ENGINE="${INNER_ENGINE:-${CONFIG_ENGINES_INNER:-claude}}"
"""
from __future__ import annotations
import argparse
import json
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_config() -> tuple[dict, str]:
    state = json.loads((ROOT / "state.json").read_text())
    version = state.get("config_version", "v1")
    path = ROOT / "configs" / f"{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"config file missing: {path}")
    return json.loads(path.read_text()), version


def get_path(cfg: dict, dotted: str):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _emit_shell(prefix: str, value):
    """Yield (env_var_name, str_value) for every scalar leaf under `prefix`."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _emit_shell(f"{prefix}_{k.upper()}", v)
    elif isinstance(value, list):
        # list -> space-joined string; rare in our schema
        yield (prefix, " ".join(str(x) for x in value))
    else:
        yield (prefix, str(value))


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version")
    g = sub.add_parser("get")
    g.add_argument("path", help="dotted path, e.g. models.inner")
    sub.add_parser("shell-export")
    args = ap.parse_args()

    cfg, version = load_config()

    if args.cmd == "version":
        print(version)
        return 0

    if args.cmd == "get":
        v = get_path(cfg, args.path)
        if v is None:
            print(f"[config] not found: {args.path}", file=sys.stderr)
            return 1
        if isinstance(v, (dict, list)):
            print(json.dumps(v))
        else:
            print(v)
        return 0

    if args.cmd == "shell-export":
        lines = []
        lines.append(f"export CONFIG_VERSION={shlex.quote(version)}")
        for k, v in cfg.items():
            if k.startswith("_") or k == "description":
                continue
            for env_name, env_val in _emit_shell(f"CONFIG_{k.upper()}", v):
                lines.append(f"export {env_name}={shlex.quote(env_val)}")
        print("; ".join(lines))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
