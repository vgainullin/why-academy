#!/usr/bin/env bash
# Apply an approved promote_proposal.md to the canonical inner-loop prompt,
# snapshot before/after, append to promotions_log, bump prompt_version.
#
# Usage:
#   scripts/promote_prompt.sh derivations/_evolutions/batches/<batch_id>/promote_proposal.md
#
# Exit codes:
#   0  promoted
#   2  proposal marked DENIED  -- no change
#   3  proposal has no "## Promote" section
#   4  promote section found but no addendum blocks
#   5  checkpoint for the target new version already exists
#
# Idempotency: re-running on the same proposal will fail at step 5 because the
# target checkpoint will exist. To re-promote, manually clear the checkpoint
# files first (and understand what you're doing).

set -euo pipefail

PROPOSAL="${1:?usage: promote_prompt.sh <path/to/promote_proposal.md>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/_derivation_python.sh"

if [[ ! -f "$PROPOSAL" ]]; then
  echo "[promote] FAIL: proposal not found at $PROPOSAL" >&2
  exit 1
fi

CHECK_DIR="$ROOT/derivations/_evolutions/checkpoints"
mkdir -p "$CHECK_DIR"

EXTRACTED="$(mktemp)"
"$PY" - "$PROPOSAL" "$EXTRACTED" <<'PYEOF'
import re, sys
proposal = open(sys.argv[1]).read()
out_path = sys.argv[2]

if re.search(r"\bDENIED\b", proposal):
    print("DENIED", file=sys.stderr)
    sys.exit(2)

m = re.search(r"^## Promote.*?(?=^## (?!Promote)|\Z)", proposal, re.MULTILINE | re.DOTALL)
if not m:
    print("NO_PROMOTE_SECTION", file=sys.stderr)
    sys.exit(3)

# Extract addendum blocks fenced as ```markdown
section = m.group(0)
blocks = re.findall(r"```(?:markdown)?\s*\n(.*?)\n```", section, re.DOTALL)
addenda = [b.strip() for b in blocks if b.strip().startswith("## Addendum")]
if not addenda:
    print("NO_ADDENDA", file=sys.stderr)
    sys.exit(4)

with open(out_path, "w") as f:
    for a in addenda:
        f.write(a + "\n\n")
print(len(addenda))
PYEOF

N_ADDENDA=$(wc -l < "$EXTRACTED" | tr -d ' ')

CURRENT_VERSION="$("$PY" -c 'import json; print(json.load(open("derivations/state.json"))["prompt_version"])')"
NEW_VERSION="$(echo "$CURRENT_VERSION" | sed -E 's/^v?([0-9]+).*/\1/' | awk '{print "v"$1+1}')"

if [[ -f "$CHECK_DIR/prompt_${NEW_VERSION}.md" ]]; then
  echo "[promote] FAIL: checkpoint $CHECK_DIR/prompt_${NEW_VERSION}.md already exists" >&2
  echo "[promote] (re-promotion not supported; clear the checkpoint manually if intentional)" >&2
  rm -f "$EXTRACTED"
  exit 5
fi

# Snapshot CURRENT state before mutating
cp derivations/prompts/generate_derivation.md "$CHECK_DIR/prompt_${CURRENT_VERSION}.md"
cp derivations/state.json "$CHECK_DIR/state_${CURRENT_VERSION}.json"

# Append addenda to canonical prompt
{
  echo
  echo "<!-- Promoted from $PROPOSAL at $(date -u +%Y-%m-%dT%H:%M:%SZ); see checkpoints/promotions_log.jsonl -->"
  echo
  cat "$EXTRACTED"
} >> derivations/prompts/generate_derivation.md

# Bump prompt_version + snapshot the new state
"$PY" - "$NEW_VERSION" <<'PYEOF'
import json, sys
new_v = sys.argv[1]
d = json.load(open("derivations/state.json"))
d["prompt_version"] = new_v
json.dump(d, open("derivations/state.json", "w"), indent=2)
PYEOF

cp derivations/prompts/generate_derivation.md "$CHECK_DIR/prompt_${NEW_VERSION}.md"
cp derivations/state.json "$CHECK_DIR/state_${NEW_VERSION}.json"

# Append to promotions log
"$PY" - "$PROPOSAL" "$CURRENT_VERSION" "$NEW_VERSION" "$CHECK_DIR/promotions_log.jsonl" <<'PYEOF'
import json, datetime, sys
proposal, from_v, to_v, log_path = sys.argv[1:5]
import re
n = len(re.findall(r"^## Addendum", open(proposal).read(), re.MULTILINE))
rec = {
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "from_version": from_v,
    "to_version": to_v,
    "proposal": proposal,
    "n_addenda_promoted": n,
}
with open(log_path, "a") as f:
    f.write(json.dumps(rec) + "\n")
PYEOF

rm -f "$EXTRACTED"

echo "[promote] $CURRENT_VERSION -> $NEW_VERSION"
echo "[promote] canonical prompt: derivations/prompts/generate_derivation.md"
echo "[promote] checkpoint:       $CHECK_DIR/prompt_${NEW_VERSION}.md"
echo "[promote] state snapshot:   $CHECK_DIR/state_${NEW_VERSION}.json"
echo "[promote] promotions log:   $CHECK_DIR/promotions_log.jsonl"
