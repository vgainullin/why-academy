#!/usr/bin/env bash
# Apply retention policy to evolution batches.
# Usage: scripts/prune_evolutions.sh [--dry-run]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/_derivation_python.sh"
exec "$PY" "$ROOT/derivations/prune.py" "$@"
