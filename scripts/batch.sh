#!/usr/bin/env bash
# Thin shell wrapper around batch.py so callers can use the same `scripts/`
# entry-point pattern as inner.sh / outer.sh / holdout.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/_derivation_python.sh"
exec "$PY" "$ROOT/scripts/batch.py" "$@"
