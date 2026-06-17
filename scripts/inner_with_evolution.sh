#!/usr/bin/env bash
# Per-target evolution loop.
#
# For ONE target, runs up to MAX_ITER iterations of: generate -> verify ->
# canvas_check -> judge -> on judge FAIL, evolve a new prompt addendum,
# regenerate. Each iteration's full workspace lives under
# _evolutions/batches/<BATCH_ID>/targets/target_<index>/iter_<N>/.
#
# Aborts on:
#   - verify FAIL  (math is wrong; not fixable via prompt evolution)
#   - canvas FAIL  (sympy auto-simplification or render bug; ditto)
#   - engine error / timeout / missing graph id
#   - MAX_ITER hit without judge PASS
#
# Env:
#   BATCH_ID         (required for batches; defaults to a timestamped 'solo')
#   TARGET_INDEX     0-based target index within the batch (default 0)
#   MAX_ITER         default 3
#   INNER_MODEL      default opus
#   INNER_ENGINE     default codex
#   JUDGE_MODEL      default deepseek-v4-flash
#   EVOLVE_MODEL     default codex default model
#   INNER_BUDGET     default 3
#   INNER_TIMEOUT    default 600

set -uo pipefail

TARGET="${1:?usage: inner_with_evolution.sh <target>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

source "$ROOT/scripts/_derivation_python.sh"
eval "$("$PY" "$ROOT/derivations/config.py" shell-export)"
BATCH_ID="${BATCH_ID:-$(date +%Y%m%d_%H%M%S)_solo}"
TARGET_INDEX="${TARGET_INDEX:-0}"
MAX_ITER="${MAX_ITER:-$CONFIG_EVOLUTION_MAX_ITER}"
INNER_MODEL="${INNER_MODEL:-$CONFIG_MODELS_INNER}"
INNER_ENGINE="${INNER_ENGINE:-${CONFIG_ENGINES_INNER:-codex}}"
JUDGE_MODEL="${JUDGE_MODEL:-$CONFIG_MODELS_JUDGE}"
JUDGE_ENGINE="${JUDGE_ENGINE:-${CONFIG_ENGINES_JUDGE:-deepseek}}"
EVOLVE_MODEL="${EVOLVE_MODEL:-$CONFIG_MODELS_EVOLVE}"
EVOLVE_ENGINE="${EVOLVE_ENGINE:-${CONFIG_ENGINES_EVOLVE:-codex}}"
INNER_BUDGET="${INNER_BUDGET:-$CONFIG_BUDGETS_USD_INNER}"
INNER_TIMEOUT="${INNER_TIMEOUT:-$CONFIG_TIMEOUTS_S_INNER}"

EVO_BASE="$ROOT/derivations/_evolutions/batches/$BATCH_ID"
TARGET_DIR="$EVO_BASE/targets/target_$(printf '%03d' "$TARGET_INDEX")"
mkdir -p "$TARGET_DIR"

# Write batch-level checkpoint on first target encountered (race-free enough for our use)
if [[ ! -f "$EVO_BASE/checkpoint.json" ]]; then
  "$PY" - <<'PYEOF' "$EVO_BASE/checkpoint.json" "$BATCH_ID" "$MAX_ITER" "$INNER_ENGINE" "$INNER_MODEL" "$JUDGE_ENGINE" "$JUDGE_MODEL" "$EVOLVE_ENGINE" "$EVOLVE_MODEL"
import json, datetime, sys
out, batch_id, max_iter, ie, im, je, jm, ee, em = sys.argv[1:10]
state = json.load(open("derivations/state.json"))
json.dump({
  "batch_id": batch_id,
  "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "epoch": state["epoch"],
  "prompt_version": state["prompt_version"],
  "validator_version": state["validator_version"],
  "max_iter": int(max_iter),
  "inner_engine": ie,
  "inner_model": im,
  "judge_engine": je,
  "judge_model": jm,
  "evolve_engine": ee,
  "evolve_model": em,
}, open(out, "w"), indent=2)
PYEOF
fi

# Per-target metadata (always written; idempotent overwrite)
"$PY" - <<'PYEOF' "$TARGET_DIR/target.json" "$BATCH_ID" "$TARGET_INDEX" "$TARGET"
import json, datetime, sys
out, batch_id, idx, target = sys.argv[1:5]
json.dump({
  "target": target,
  "batch_id": batch_id,
  "target_index": int(idx),
  "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}, open(out, "w"), indent=2)
PYEOF

CANONICAL_PROMPT="$ROOT/derivations/prompts/generate_derivation.md"
VARIANT_PROMPT="$CANONICAL_PROMPT"
SEED_VARIANT="$TARGET_DIR/seed_variant.md"
SEED_META="$TARGET_DIR/seed_variant.json"
"$PY" - "$TARGET" "$BATCH_ID" "$SEED_VARIANT" "$SEED_META" <<'PYEOF'
import json, shutil, sys
from pathlib import Path
sys.path.insert(0, "derivations")
from evolution_memory import find_seed_variant

target, batch_id, seed_variant, seed_meta = sys.argv[1:5]
seed = find_seed_variant(target, current_batch_id=batch_id)
if seed:
    shutil.copy(Path(seed["variant_path"]), seed_variant)
    Path(seed_meta).write_text(json.dumps(seed, indent=2))
PYEOF
if [[ -f "$SEED_VARIANT" ]]; then
  VARIANT_PROMPT="$SEED_VARIANT"
fi
ACCEPTED_ITER=""
FAIL_REASON=""

for ((ITER=0; ITER<MAX_ITER; ITER++)); do
  ITER_DIR="$TARGET_DIR/iter_$(printf '%02d' "$ITER")"
  mkdir -p "$ITER_DIR"

  # Snapshot the variant the LLM will see. On iter_01+ the evolve step already
  # wrote variant.md directly into this iter_dir, so a self-copy would error
  # under `set -e` -- only copy when source and destination differ.
  if [[ "$VARIANT_PROMPT" != "$ITER_DIR/variant.md" ]]; then
    cp "$VARIANT_PROMPT" "$ITER_DIR/variant.md"
  fi

  # Assign a unique problem id per iteration -- guarantees the canonical path
  # is free regardless of leftover artifacts from prior runs / other batches.
  PROBLEM_ID="evo_${BATCH_ID//[^a-zA-Z0-9_]/_}_t$(printf '%03d' "$TARGET_INDEX")_i$(printf '%02d' "$ITER")"

  # Defensively clear any stale canonical artifacts under that id (shouldn't
  # exist; this is belt-and-suspenders against weird state).
  rm -f "$ROOT/derivations/problems/${PROBLEM_ID}".*

  # Render <<TARGET>> + <<PROBLEM_ID>>
  "$PY" - <<'PYEOF' "$ITER_DIR/variant.md" "$TARGET" "$PROBLEM_ID" "$ITER_DIR/rendered_prompt.md"
import sys
src, target, pid, out = sys.argv[1:5]
content = open(src).read()
content = content.replace("<<TARGET>>", target).replace("<<PROBLEM_ID>>", pid)
open(out, "w").write(content)
PYEOF

  CONSOLE="$ITER_DIR/console.log"

  # Generate
  set +e
  "$PY" derivations/run_llm.py \
    --engine "$INNER_ENGINE" \
    --model "$INNER_MODEL" \
    --budget "$INNER_BUDGET" \
    --timeout "$INNER_TIMEOUT" \
    --prompt-file "$ITER_DIR/rendered_prompt.md" \
    > "$CONSOLE" 2>&1
  LLM_EXIT=$?
  set -e

  if [[ $LLM_EXIT -ne 0 ]]; then
    echo "${INNER_ENGINE}_fail_exit_$LLM_EXIT" > "$ITER_DIR/status.txt"
    FAIL_REASON="${INNER_ENGINE}_fail_iter_$ITER"
    break
  fi

  # We told the LLM to use $PROBLEM_ID; the file should be at that path.
  CANON_PROBLEM="$ROOT/derivations/problems/$PROBLEM_ID.json"
  if [[ ! -f "$CANON_PROBLEM" ]]; then
    echo "problem_missing" > "$ITER_DIR/status.txt"
    FAIL_REASON="problem_missing_iter_$ITER"
    break
  fi

  # Move LLM's outputs to the iter workspace
  mv "$CANON_PROBLEM" "$ITER_DIR/problem.json"
  [[ -f "$ROOT/derivations/problems/$PROBLEM_ID.verifier.json" ]] && \
    mv "$ROOT/derivations/problems/$PROBLEM_ID.verifier.json" "$ITER_DIR/problem.verifier.json"

  rm -f "$ITER_DIR/problem.verifier.json" "$ITER_DIR/problem.canvas_check.json" \
    "$ITER_DIR/problem.target_check.json" "$ITER_DIR/problem.judge.json" \
    "$ITER_DIR/problem.canvas.json" "$ITER_DIR/problem.raw.json" \
    "$ITER_DIR/problem.raw.verifier.json"

  cp "$ITER_DIR/problem.json" "$ITER_DIR/problem.raw.json"
  "$PY" derivations/verify.py "$ITER_DIR/problem.json" > "$ITER_DIR/verify_raw.log" 2>&1

  # Raw verifier failure is unrecoverable by graph normalization.
  VERIFIER_FAIL="$("$PY" - <<PYEOF
import json
try:
    d = json.load(open("$ITER_DIR/problem.verifier.json"))
    es = d["edge_summary"]
    print("yes" if (es["FAIL"] + es["ERROR"]) > 0 else "no")
except Exception:
    print("error")
PYEOF
)"
  if [[ "$VERIFIER_FAIL" == "yes" || "$VERIFIER_FAIL" == "error" ]]; then
    cp "$ITER_DIR/verify_raw.log" "$ITER_DIR/verify.log"
    echo "verify_fail" > "$ITER_DIR/status.txt"
    FAIL_REASON="verify_fail_iter_$ITER"
    break
  fi

  cp "$ITER_DIR/problem.verifier.json" "$ITER_DIR/problem.raw.verifier.json"
  "$PY" derivations/graph_normalize.py "$ITER_DIR/problem.json" > "$ITER_DIR/graph_normalize.log" 2>&1
  "$PY" derivations/verify.py "$ITER_DIR/problem.json" > "$ITER_DIR/verify.log" 2>&1

  VERIFIER_FAIL="$("$PY" - <<PYEOF
import json
try:
    d = json.load(open("$ITER_DIR/problem.verifier.json"))
    es = d["edge_summary"]
    print("yes" if (es["FAIL"] + es["ERROR"]) > 0 else "no")
except Exception:
    print("error")
PYEOF
)"
  if [[ "$VERIFIER_FAIL" == "yes" || "$VERIFIER_FAIL" == "error" ]]; then
    echo "verify_fail" > "$ITER_DIR/status.txt"
    FAIL_REASON="verify_fail_iter_$ITER"
    break
  fi

  # canvas_check
  set +e
  "$PY" derivations/canvas_check.py "$ITER_DIR/problem.json" > "$ITER_DIR/canvas_check.log" 2>&1
  CANVAS_EXIT=$?
  set -e

  # to_canvas only on canvas pass
  if [[ $CANVAS_EXIT -eq 0 ]]; then
    "$PY" derivations/to_canvas.py "$ITER_DIR/problem.json" > /dev/null || true
  fi

  if [[ $CANVAS_EXIT -ne 0 ]]; then
    echo "canvas_fail" > "$ITER_DIR/status.txt"
    FAIL_REASON="canvas_fail_iter_$ITER"
    break
  fi

  # Judge
  set +e
  "$PY" derivations/judge.py "$ITER_DIR/problem.json" --target "$TARGET" --engine "$JUDGE_ENGINE" --model "$JUDGE_MODEL" \
    > "$ITER_DIR/judge.log" 2>&1
  JUDGE_EXIT=$?
  set -e

  OVERALL="$("$PY" - <<PYEOF
import json
try:
    print(json.load(open("$ITER_DIR/problem.judge.json"))["overall"])
except Exception:
    print("ERROR")
PYEOF
)"
  echo "$OVERALL" > "$ITER_DIR/status.txt"

  if [[ "$OVERALL" == "PASS" ]]; then
    ACCEPTED_ITER="iter_$(printf '%02d' "$ITER")"
    break
  fi

  # Judge FAIL: evolve if we have more iterations
  if (( ITER + 1 < MAX_ITER )); then
    NEXT_DIR="$TARGET_DIR/iter_$(printf '%02d' $((ITER + 1)))"
    mkdir -p "$NEXT_DIR"
    set +e
    "$PY" derivations/evolve.py \
      --target "$TARGET" \
      --judge "$ITER_DIR/problem.judge.json" \
      --current-variant "$ITER_DIR/variant.md" \
      --iteration "$ITER" \
      --out "$NEXT_DIR/addendum.md" \
      --engine "$EVOLVE_ENGINE" \
      --model "$EVOLVE_MODEL"
    EVOLVE_EXIT=$?
    set -e
    if [[ $EVOLVE_EXIT -ne 0 ]]; then
      echo "evolve_fail" > "$ITER_DIR/status.txt"
      FAIL_REASON="evolve_fail_iter_$ITER"
      break
    fi
    # Next variant = current variant + new addendum
    {
      cat "$ITER_DIR/variant.md"
      echo
      cat "$NEXT_DIR/addendum.md"
    } > "$NEXT_DIR/variant.md"
    VARIANT_PROMPT="$NEXT_DIR/variant.md"
  fi
done

if [[ -n "$ACCEPTED_ITER" ]]; then
  echo "$ACCEPTED_ITER" > "$TARGET_DIR/ACCEPTED.txt"
  echo "[evolve_target] ACCEPTED at $ACCEPTED_ITER  target=$TARGET" >&2
else
  echo "${FAIL_REASON:-exhausted}" > "$TARGET_DIR/FAILED.txt"
  echo "[evolve_target] FAILED ($FAIL_REASON)  target=$TARGET" >&2
fi

# target_metrics.json
"$PY" - <<'PYEOF' "$TARGET_DIR" "$TARGET_INDEX"
import json, sys
from pathlib import Path
td = Path(sys.argv[1])
target_index = int(sys.argv[2])
iters = sorted(td.glob("iter_*"))
statuses = [(it.name, (it / "status.txt").read_text().strip() if (it / "status.txt").exists() else "missing") for it in iters]
accepted = (td / "ACCEPTED.txt").exists()
accepted_at = None
if accepted:
    accepted_at = int((td / "ACCEPTED.txt").read_text().strip().replace("iter_", ""))
first_try_pass = statuses[0][1] == "PASS" if statuses else False
metrics = {
    "target_index": target_index,
    "n_iterations": len(iters),
    "accepted": accepted,
    "accepted_at_iter": accepted_at,
    "first_try_pass": first_try_pass,
    "iter_statuses": statuses,
    "failure_reason": (td / "FAILED.txt").read_text().strip() if not accepted and (td / "FAILED.txt").exists() else None,
}
json.dump(metrics, open(td / "target_metrics.json", "w"), indent=2)
print(json.dumps(metrics))
PYEOF
