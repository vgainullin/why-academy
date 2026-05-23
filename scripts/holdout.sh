#!/usr/bin/env bash
# Run verify.py over the legacy full-graph holdout corpus and write the
# aggregate result.
#
# Usage:
#   scripts/holdout.sh            # uses current epoch from state.json
#   scripts/holdout.sh 5          # forces epoch number (e.g. retroactive run)
#
# Output:
#   derivations/test_corpus/holdout/results_epoch_<NNN>.json
#
# Each holdout problem's sidecar is also (re)written to test_corpus/holdout/sidecars/.
# This deliberately keeps held-out artifacts segregated from the inner-loop
# problems/ directory so contamination during validator development is harder.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

source "$ROOT/scripts/_derivation_python.sh"
EPOCH="${1:-$("$PY" -c 'import json; print(json.load(open("derivations/state.json"))["epoch"])')}"
EPOCH_NNN="$(printf '%03d' "$EPOCH")"
VALIDATOR_VERSION="$("$PY" -c 'import json; print(json.load(open("derivations/state.json"))["validator_version"])')"

HOLDOUT_DIR="derivations/test_corpus/holdout"
PROBLEM_DIR="$HOLDOUT_DIR/problems_legacy_verifier"
SIDECAR_DIR="$HOLDOUT_DIR/sidecars/epoch_${EPOCH_NNN}"
RESULTS="$HOLDOUT_DIR/results_epoch_${EPOCH_NNN}.json"

mkdir -p "$SIDECAR_DIR"

PROBLEMS=()
for p in "$PROBLEM_DIR"/*.json; do
  [[ -f "$p" ]] || continue
  case "$(basename "$p")" in
    *.verifier.json|*.canvas_check.json) continue ;;
  esac
  PROBLEMS+=("$p")
done
if [[ ${#PROBLEMS[@]} -eq 0 || ! -f "${PROBLEMS[0]}" ]]; then
  echo "[holdout] FAIL: no legacy verifier problems in $PROBLEM_DIR/" >&2
  exit 1
fi

echo "[holdout] epoch=$EPOCH_NNN validator_version=$VALIDATOR_VERSION legacy_problems=${#PROBLEMS[@]}" >&2

# Run verify.py over each problem; sidecars land next to the source then move to per-epoch dir.
TMP_RESULTS="$(mktemp)"
trap 'rm -f "$TMP_RESULTS"' EXIT

CANVAS_FAILURES=()
for p in "${PROBLEMS[@]}"; do
  base="$(basename "$p" .json)"
  echo "[holdout]   verifying $base" >&2
  if "$PY" derivations/verify.py "$p" > /dev/null; then
    echo "$base PASS" >> "$TMP_RESULTS"
  else
    echo "$base FAIL" >> "$TMP_RESULTS"
  fi
  mv "$PROBLEM_DIR/${base}.verifier.json" "$SIDECAR_DIR/${base}.verifier.json"

  # Holdout problems are hand-curated; they must also be canvas-clean.
  # Any failure here is a curation bug, not a generation signal.
  if ! "$PY" derivations/canvas_check.py "$p" > /dev/null; then
    CANVAS_FAILURES+=("$base")
  fi
  mv "$PROBLEM_DIR/${base}.canvas_check.json" "$SIDECAR_DIR/${base}.canvas_check.json"
done

if [[ ${#CANVAS_FAILURES[@]} -gt 0 ]]; then
  echo "[holdout] FAIL: canvas_check failed on holdout problem(s): ${CANVAS_FAILURES[*]}" >&2
  echo "[holdout] hold-out problems must round-trip cleanly through sympy.latex/parse_latex." >&2
  exit 2
fi

"$PY" - <<PYEOF
import json, glob, datetime, pathlib
sidecar_dir = pathlib.Path("$SIDECAR_DIR")
results = []
total_edges = 0
total_pass = 0
total_weak = 0
total_fail = 0
for sc in sorted(sidecar_dir.glob("*.verifier.json")):
    data = json.loads(sc.read_text())
    es = data["edge_summary"]
    edges_ok = es["FAIL"] == 0 and es["ERROR"] == 0
    results.append({
        "id": data["problem_id"],
        "n_edges": data["n_edges"],
        "edge_summary": es,
        "status": "PASS" if edges_ok else "FAIL",
    })
    total_edges += data["n_edges"]
    total_pass += es["PASS"]
    total_weak += es["WEAK_PASS"]
    total_fail += es["FAIL"] + es["ERROR"]

passed = sum(1 for r in results if r["status"] == "PASS")
out = {
    "epoch": $EPOCH,
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "validator_version": "$VALIDATOR_VERSION",
    "problem_dir": "$PROBLEM_DIR",
    "n_problems": len(results),
    "problems_passed": passed,
    "problems_failed": len(results) - passed,
    "problem_pass_rate": passed / len(results),
    "edge_totals": {
        "PASS": total_pass,
        "WEAK_PASS": total_weak,
        "FAIL_OR_ERROR": total_fail,
        "total": total_edges,
    },
    "edge_pass_rate_strong": total_pass / total_edges if total_edges else 0,
    "edge_pass_rate_with_weak": (total_pass + total_weak) / total_edges if total_edges else 0,
    "per_problem": results,
}
pathlib.Path("$RESULTS").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
PYEOF

echo "[holdout] wrote $RESULTS" >&2
