#!/usr/bin/env bash
# Compare Claude judge vs DeepSeek judge on a set of existing graphs.
#
# Usage:
#   scripts/judge_compare.sh <batch_dir>              # all iter graphs in a batch
#   scripts/judge_compare.sh --files a.json b.json    # specific problem.json files
#   scripts/judge_compare.sh --all-problems           # everything under derivations/problems/
#
# Side-effect: each graph gets <stem>.judge.json (Claude) and
# <stem>.judge_deepseek.json (DeepSeek). Both must run for the row to count.
# Final summary: agreement rate + disagreement details.
#
# Requires: ANTHROPIC OAuth (claude CLI) AND DEEPSEEK_API_KEY env var.

set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/_derivation_python.sh"

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "[compare] FAIL: DEEPSEEK_API_KEY not set in environment" >&2
  exit 2
fi

FILES=()
case "${1:-}" in
  --files)
    shift
    FILES=("$@")
    ;;
  --all-problems)
    while IFS= read -r f; do FILES+=("$f"); done < <(find derivations/problems -maxdepth 1 -name '*.json' -not -name '*.verifier.json' -not -name '*.canvas*.json' -not -name '*.judge*.json' | sort)
    ;;
  '')
    echo "usage: $0 <batch_dir>|--files ...|--all-problems" >&2
    exit 2
    ;;
  *)
    BATCH_DIR="$1"
    while IFS= read -r f; do FILES+=("$f"); done < <(find "$BATCH_DIR/targets" -path '*/iter_*/problem.json' 2>/dev/null | sort)
    ;;
esac

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "[compare] no graphs found" >&2
  exit 1
fi

echo "[compare] graphs to evaluate: ${#FILES[@]}"

for ((i=0; i<${#FILES[@]}; i++)); do
  F="${FILES[$i]}"
  PID=$("$PY" -c "import json; print(json.load(open('$F'))['id'])")
  TGT_FILE="$(dirname "$(dirname "$F")")/target.json"
  if [[ -f "$TGT_FILE" ]]; then
    TARGET=$("$PY" -c "import json; print(json.load(open('$TGT_FILE'))['target'])")
  else
    TARGET="$PID"
  fi
  echo "[compare] [$((i+1))/${#FILES[@]}] $PID"
  (
    "$PY" derivations/judge.py "$F" --target "$TARGET" > /dev/null 2>&1
  ) &
  CPID=$!
  (
    "$PY" derivations/deepseek_judge.py "$F" --target "$TARGET" > /dev/null 2>&1
  ) &
  DPID=$!
  wait $CPID $DPID
done

echo
echo "[compare] aggregating..."
"$PY" - "${FILES[@]}" <<'PYEOF'
import sys, json
from pathlib import Path

files = sys.argv[1:]
rows = []
for f in files:
    p = Path(f)
    cj = p.with_name(p.stem + ".judge.json")
    dj = p.with_name(p.stem + ".judge_deepseek.json")
    if not (cj.exists() and dj.exists()):
        continue
    c = json.load(open(cj))
    d = json.load(open(dj))
    rows.append({
        "pid": json.load(open(p))["id"],
        "claude": c["overall"],
        "deepseek": d["overall"],
        "claude_verdicts": c.get("verdicts", {}),
        "deepseek_verdicts": d.get("verdicts", {}),
    })

n = len(rows)
if n == 0:
    print("no rows with both sidecars; nothing to aggregate")
    sys.exit(0)
n_agree = sum(1 for r in rows if r["claude"] == r["deepseek"])
print(f"\n=== Agreement: {n_agree}/{n}  ({100*n_agree/n:.0f}%) ===\n")

print(f"{'pid':50s} {'claude':8s} {'deepseek':10s}")
for r in rows:
    flag = "  ***" if r["claude"] != r["deepseek"] else ""
    print(f"{r['pid']:50s} {r['claude']:8s} {r['deepseek']:10s}{flag}")

dis = [r for r in rows if r["claude"] != r["deepseek"]]
if dis:
    print(f"\n--- {len(dis)} disagreement(s) ---")
    for r in dis:
        print(f"\n{r['pid']}:")
        for crit in ('one_rule_per_edge', 'given_facts_visible'):
            cv = (r['claude_verdicts'].get(crit) or {}).get('verdict', '?')
            dv = (r['deepseek_verdicts'].get(crit) or {}).get('verdict', '?')
            if cv != dv:
                cr = (r['claude_verdicts'].get(crit) or {}).get('reason','')[:100]
                dr = (r['deepseek_verdicts'].get(crit) or {}).get('reason','')[:100]
                print(f"  {crit}: claude={cv}  ({cr})")
                print(f"  {crit}: deepseek={dv}  ({dr})")
PYEOF
