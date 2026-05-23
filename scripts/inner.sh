#!/usr/bin/env bash
# Inner-loop wrapper: one target -> one derivation graph -> one jsonl log line.
#
# Usage:
#   scripts/inner.sh "x + 2 = 5"
#   INNER_MODEL=sonnet INNER_BUDGET=2 scripts/inner.sh "..."
#   INNER_ENGINE=codex INNER_MODEL=gpt-5.2 scripts/inner.sh "..."
#
# Side effects:
#   - derivations/problems/<id>.json                 (written by claude)
#   - derivations/problems/<id>.verifier.json        (written by verify.py)
#   - derivations/logs/epoch_<NNN>/run_<uuid>.prompt.md   (rendered prompt, audit)
#   - derivations/logs/epoch_<NNN>/run_<uuid>.console.log (raw claude stdout/stderr)
#   - derivations/logs/epoch_<NNN>/run_<uuid>.jsonl       (the canonical record)
#
# Permission posture: --permission-mode bypassPermissions. v0 trade-off:
# the inner prompt has hard constraints scoping writes to problems/<id>.json,
# and locking down --allowedTools to every sub-pattern the LLM might use
# (xargs, basename, sed, sort, ls, verify.py) is brittle. Revisit once we
# have a baseline and know which commands actually show up in the logs.

set -euo pipefail

TARGET="${1:?usage: inner.sh <target equation>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

source "$ROOT/scripts/_derivation_python.sh"
eval "$("$PY" "$ROOT/derivations/config.py" shell-export)"
MODEL="${INNER_MODEL:-$CONFIG_MODELS_INNER}"
ENGINE="${INNER_ENGINE:-${CONFIG_ENGINES_INNER:-claude}}"
BUDGET="${INNER_BUDGET:-$CONFIG_BUDGETS_USD_INNER}"
TIMEOUT="${INNER_TIMEOUT:-$CONFIG_TIMEOUTS_S_INNER}"

RUN_ID="$(uuidgen | tr 'A-Z' 'a-z')"
EPOCH="$("$PY" -c 'import json; print(json.load(open("derivations/state.json"))["epoch"])')"
EPOCH_DIR="derivations/logs/epoch_$(printf '%03d' "$EPOCH")"
mkdir -p derivations/problems
mkdir -p "$EPOCH_DIR"

echo "[inner] run_id=$RUN_ID epoch=$EPOCH engine=$ENGINE model=$MODEL target=$TARGET" >&2

# Render the prompt with the target injected at <<TARGET>>. inner.sh runs in
# "AUTO" id mode -- the LLM picks the id from the target as before.
RENDERED="$EPOCH_DIR/run_${RUN_ID}.prompt.md"
"$PY" -c '
import sys
prompt_path, target, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
content = open(prompt_path).read()
content = content.replace("<<TARGET>>", target).replace("<<PROBLEM_ID>>", "AUTO")
open(out_path, "w").write(content)
' derivations/prompts/generate_derivation.md "$TARGET" "$RENDERED"

CONSOLE="$EPOCH_DIR/run_${RUN_ID}.console.log"

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
  echo "[inner] $ENGINE exited $LLM_EXIT; tail of console:" >&2
  tail -40 "$CONSOLE" >&2
  exit $LLM_EXIT
fi

# Parse problem id from the structured summary the prompt prints.
PID="$(grep -m1 '^GRAPH:' "$CONSOLE" | awk '{print $2}' || true)"
if [[ -z "$PID" ]]; then
  echo "[inner] FAIL: could not find 'GRAPH:' line in console output" >&2
  tail -40 "$CONSOLE" >&2
  exit 2
fi

SIDECAR="derivations/problems/${PID}.verifier.json"
if [[ ! -f "$SIDECAR" ]]; then
  echo "[inner] FAIL: sidecar not found at $SIDECAR" >&2
  echo "[inner] (claude reported GRAPH: $PID but verify.py never wrote the sidecar)" >&2
  exit 3
fi

cp "derivations/problems/${PID}.json" "derivations/problems/${PID}.raw.json"
set +e
"$PY" derivations/verify.py "derivations/problems/${PID}.json" > /dev/null
VERIFY_EXIT=$?
set -e
if [[ $VERIFY_EXIT -eq 0 ]]; then
  cp "$SIDECAR" "derivations/problems/${PID}.raw.verifier.json"
  "$PY" derivations/graph_normalize.py "derivations/problems/${PID}.json" > /dev/null
  "$PY" derivations/verify.py "derivations/problems/${PID}.json" > /dev/null
fi

# Canvas-derive round-trip integration check. Wrapper-level gate that catches
# sympy auto-simplification collapsing pedagogically distinct nodes and any
# sympy.latex -> parse_latex round-trip losses.
set +e
"$PY" derivations/canvas_check.py "derivations/problems/${PID}.json"
CANVAS_EXIT=$?
set -e

# On canvas-check pass, emit the canvas-derive block so the graph is
# immediately deliverable as a lesson. On fail, skip -- not serveable.
if [[ $CANVAS_EXIT -eq 0 ]]; then
  "$PY" derivations/to_canvas.py "derivations/problems/${PID}.json" > /dev/null
fi

# Pedagogical-quality judge (LLM-as-judge with Sonnet, separate cheap call).
# SOFT signal: result lands in the jsonl for outer-loop categorization, but
# does NOT gate inner.sh exit code. The "rejection" of pedagogically-wrong
# derivations is the outer loop's job (JUDGE_REJECTED category).
set +e
"$PY" derivations/judge.py "derivations/problems/${PID}.json" --target "$TARGET"
JUDGE_EXIT=$?
set -e

"$PY" derivations/emit_log.py \
  --sidecar "$SIDECAR" \
  --target "$TARGET" \
  --run-id "$RUN_ID" \
  --model "$ENGINE:$MODEL"

if [[ $CANVAS_EXIT -ne 0 ]]; then
  echo "[inner] canvas_check failed; graph is mathematically OK per verify.py but" >&2
  echo "[inner] cannot be served via canvas-derive as-is. See sidecar for details:" >&2
  echo "[inner]   derivations/problems/${PID}.canvas_check.json" >&2
  exit 4
fi

if [[ $JUDGE_EXIT -eq 1 ]]; then
  echo "[inner] judge FAIL (pedagogical); recorded in jsonl, not blocking. See:" >&2
  echo "[inner]   derivations/problems/${PID}.judge.json" >&2
elif [[ $JUDGE_EXIT -eq 2 ]]; then
  echo "[inner] judge wrapper error (claude or JSON parse); jsonl will have null judge_eval" >&2
fi

echo "[inner] done: $PID  (canvas: derivations/problems/${PID}.canvas.json)" >&2
