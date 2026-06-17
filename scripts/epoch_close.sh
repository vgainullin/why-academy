#!/usr/bin/env bash
# Close out the current epoch and start the next one.
#
# Sequence:
#   1. Run holdout.sh for the current epoch (writes results_epoch_<NNN>.json)
#   2. Run outer.sh against the current epoch's logs (writes reports/epoch_<NNN>/...)
#   3. Bump state.json epoch
#   4. Pre-create logs/epoch_<NEW>/ so the next inner.sh has a place to write
#
# Re-running on a closed epoch is a no-op for steps 1-2 (they overwrite) and
# would only re-bump in step 3 if the user is being deliberate. The wrapper
# does not enforce idempotency past that -- each invocation closes ONE epoch.
#
# This is intended to be invoked manually (or by a cron) after a batch run
# accumulates "enough" logs, typically >=100 per the outer prompt's threshold.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

source "$ROOT/scripts/_derivation_python.sh"
EPOCH="$("$PY" -c 'import json; print(json.load(open("derivations/state.json"))["epoch"])')"
EPOCH_NNN="$(printf '%03d' "$EPOCH")"
LOG_COUNT="$(find "derivations/logs/epoch_$EPOCH_NNN" -maxdepth 1 -name 'run_*.jsonl' 2>/dev/null | wc -l | tr -d ' ')"

echo "[epoch_close] closing epoch_$EPOCH_NNN  ($LOG_COUNT jsonl logs)" >&2
echo

echo "[epoch_close] 1/3 running holdout"
scripts/holdout.sh "$EPOCH" > /dev/null
echo "[epoch_close]     -> derivations/test_corpus/holdout/results_epoch_${EPOCH_NNN}.json"
echo

echo "[epoch_close] 2/3 running outer loop"
OUTER_BUDGET="${OUTER_BUDGET:-10}" scripts/outer.sh "epoch_$EPOCH_NNN"
echo "[epoch_close]     -> derivations/reports/epoch_${EPOCH_NNN}/"
echo

echo "[epoch_close] 3/3 bumping state.json"
NEW_EPOCH=$((EPOCH + 1))
"$PY" -c "
import json, pathlib
p = pathlib.Path('derivations/state.json')
d = json.loads(p.read_text())
d['epoch'] = $NEW_EPOCH
p.write_text(json.dumps(d, indent=2) + '\n')
print(f'  epoch: {$EPOCH} -> {$NEW_EPOCH}')
print(f'  prompt_version: {d[\"prompt_version\"]}  (unchanged)')
print(f'  validator_version: {d[\"validator_version\"]}  (unchanged)')
"
mkdir -p "derivations/logs/epoch_$(printf '%03d' $NEW_EPOCH)"

echo
echo "[epoch_close] epoch_$EPOCH_NNN closed. Review proposals at:" >&2
echo "[epoch_close]   derivations/reports/epoch_$EPOCH_NNN/summary.md" >&2
echo "[epoch_close] Approved proposals can be implemented with:" >&2
echo "[epoch_close]   scripts/implement.sh derivations/reports/epoch_$EPOCH_NNN/<proposal>.md" >&2
