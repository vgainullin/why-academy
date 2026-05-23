#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

source "$ROOT/scripts/_derivation_python.sh"
exec "$PY" derivations/capability_synthesize.py "$@"
