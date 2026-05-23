#!/usr/bin/env bash
# Closure test for an implemented proposal.
# Usage: scripts/closure_test.sh derivations/reports/epoch_NNN/proposal_01_<rule>.md
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/_derivation_python.sh"
exec "$PY" "$ROOT/derivations/closure_test.py" "$@"
