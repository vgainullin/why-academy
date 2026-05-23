#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/_derivation_python.sh"
exec "$PY" "$ROOT/scripts/e2e_learning_probe.py" "$@"
