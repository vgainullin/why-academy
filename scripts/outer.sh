#!/usr/bin/env bash
# Outer-loop wrapper: analyze accumulated logs, produce a proposal report.
#
# Usage:
#   scripts/outer.sh                        # defaults: just-this-epoch, MAX=5
#   scripts/outer.sh epoch_000..epoch_003   # explicit range
#   MAX_PROPOSALS=3 scripts/outer.sh ...
#
# The prompt is the gate. This wrapper does no analysis itself; it only renders
# the prompt with concrete values, invokes an LLM headless, and surfaces the
# resulting reports directory.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

source "$ROOT/scripts/_derivation_python.sh"
eval "$("$PY" "$ROOT/derivations/config.py" shell-export)"
MODEL="${OUTER_MODEL:-$CONFIG_MODELS_OUTER}"
ENGINE="${OUTER_ENGINE:-${CONFIG_ENGINES_OUTER:-codex}}"
BUDGET="${OUTER_BUDGET:-$CONFIG_BUDGETS_USD_OUTER}"
TIMEOUT="${OUTER_TIMEOUT:-$CONFIG_TIMEOUTS_S_OUTER}"
MAX_PROPOSALS="${MAX_PROPOSALS:-5}"

EPOCH="$("$PY" -c 'import json; print(json.load(open("derivations/state.json"))["epoch"])')"
EPOCH_NNN="$(printf '%03d' "$EPOCH")"
EPOCH_RANGE="${1:-epoch_${EPOCH_NNN}}"

RUN_ID="$(uuidgen | tr 'A-Z' 'a-z')"
REPORTS_DIR="derivations/reports/epoch_${EPOCH_NNN}"
mkdir -p "$REPORTS_DIR"

echo "[outer] epoch=$EPOCH_NNN range=$EPOCH_RANGE max=$MAX_PROPOSALS engine=$ENGINE model=$MODEL run_id=$RUN_ID" >&2

RENDERED="$REPORTS_DIR/run_${RUN_ID}.prompt.md"
"$PY" -c '
import sys
prompt_path, epoch_range, max_prop, out_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
content = open(prompt_path).read()
content = content.replace("<<EPOCH_RANGE>>", epoch_range)
content = content.replace("<<MAX_PROPOSALS>>", max_prop)
open(out_path, "w").write(content)
' derivations/prompts/outer_loop_epoch.md "$EPOCH_RANGE" "$MAX_PROPOSALS" "$RENDERED"

CONSOLE="$REPORTS_DIR/run_${RUN_ID}.console.log"

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
  echo "[outer] $ENGINE exited $LLM_EXIT; tail of console:" >&2
  tail -60 "$CONSOLE" >&2
  exit $LLM_EXIT
fi

echo "[outer] done. reports:" >&2
ls -1 "$REPORTS_DIR" >&2
