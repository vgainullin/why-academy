#!/usr/bin/env bash
# Autonomous epoch driver. Runs one full epoch (GENERATE -> ANALYZE -> IMPLEMENT -> CLOSE).
# Resumable: re-running picks up where the previous invocation left off.
#
# Usage:
#   scripts/autonomous_epoch.sh                                          # default queue
#   scripts/autonomous_epoch.sh --queue derivations/targets/foo.txt
#   scripts/autonomous_epoch.sh --reset                                   # start fresh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/_derivation_python.sh"
exec "$PY" "$ROOT/derivations/autonomous_epoch.py" "$@"
