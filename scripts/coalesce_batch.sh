#!/usr/bin/env bash
# Batch-level coalescing: run coalesce.py over a finished batch.
#
# Usage:
#   scripts/coalesce_batch.sh derivations/_evolutions/batches/<batch_id>
#
# Reads accepted variants, clusters addenda, writes:
#   <batch>/batch_metrics.json
#   <batch>/coalesce_report.md
#   <batch>/promote_proposal.md
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/_derivation_python.sh"
exec "$PY" "$ROOT/derivations/coalesce.py" "$@"
