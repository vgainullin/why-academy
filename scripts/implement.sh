#!/usr/bin/env bash
# Implement-Proposal wrapper. Invokes the implement_proposal.md prompt against
# a specific approved proposal file. The most consequential step in the
# pipeline -- it's the only one that modifies validator code.
#
# Usage:
#   scripts/implement.sh derivations/reports/epoch_000/proposal_01_NEW_VALIDATOR.md
#
# Locks the model to a writes-restricted permission set; the prompt itself has
# hard constraints that are the primary safety mechanism, but allowedTools is
# the belt to the prompt's suspenders.

set -euo pipefail

PROPOSAL="${1:?usage: implement.sh <path/to/proposal.md>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f "$PROPOSAL" ]]; then
  echo "[implement] FAIL: proposal not found at $PROPOSAL" >&2
  exit 1
fi

source "$ROOT/scripts/_derivation_python.sh"
eval "$("$PY" "$ROOT/derivations/config.py" shell-export)"
MODEL="${IMPLEMENT_MODEL:-$CONFIG_MODELS_IMPLEMENT}"
ENGINE="${IMPLEMENT_ENGINE:-${CONFIG_ENGINES_IMPLEMENT:-codex}}"
BUDGET="${IMPLEMENT_BUDGET:-$CONFIG_BUDGETS_USD_IMPLEMENT}"
TIMEOUT="${IMPLEMENT_TIMEOUT:-$CONFIG_TIMEOUTS_S_IMPLEMENT}"

RUN_ID="$(uuidgen | tr 'A-Z' 'a-z')"
LOG_DIR="$ROOT/derivations/logs/implementations"
mkdir -p "$LOG_DIR"

echo "[implement] proposal=$PROPOSAL  engine=$ENGINE  model=$MODEL  run_id=$RUN_ID" >&2

RENDERED="$LOG_DIR/run_${RUN_ID}.prompt.md"
"$PY" -c '
import sys
template = open(sys.argv[1]).read()
out = template.replace("<<PROPOSAL_PATH>>", sys.argv[2])
open(sys.argv[3], "w").write(out)
' derivations/prompts/implement_proposal.md "$PROPOSAL" "$RENDERED"

CONSOLE="$LOG_DIR/run_${RUN_ID}.console.log"

set +e
"$PY" derivations/run_llm.py \
  --engine "$ENGINE" \
  --model "$MODEL" \
  --budget "$BUDGET" \
  --timeout "$TIMEOUT" \
  --prompt-file "$RENDERED" \
  > "$CONSOLE" 2>&1
LLM_EXIT=$?
set -e

if [[ $LLM_EXIT -ne 0 ]]; then
  echo "[implement] $ENGINE exited $LLM_EXIT; tail of console:" >&2
  tail -60 "$CONSOLE" >&2
  exit $LLM_EXIT
fi

# Surface the implementation report
echo "---" >&2
tail -30 "$CONSOLE"
echo "---" >&2
echo "[implement] done. full log: $CONSOLE" >&2
