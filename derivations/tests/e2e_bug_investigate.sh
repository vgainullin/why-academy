#!/usr/bin/env bash
# E2E test for the BUG_INVESTIGATE phase and BUGFIX closure path.
#
# Drives the REAL autonomous_epoch.py main() through:
#   BUG_INVESTIGATE (reads synthetic logs, writes BUGFIX proposal)
#   -> EXPERIMENT (disabled, skips)
#   -> IMPLEMENT (stub implement.sh + REAL closure_test.sh)
#   -> CLOSE
#
# Only the LLM-calling implement.sh is stubbed. Everything else —
# phase_bug_investigate, closure_test.sh -> closure_test.py, verify.verify_edge,
# the real divide_both_sides validator, holdout check, regression test writing —
# runs through the actual code paths.
#
# Usage: bash derivations/tests/e2e_bug_investigate.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV_PY="$REPO/derivations/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
	echo "FAIL: derivations/.venv not found. Run: uv venv derivations/.venv && uv pip install -r derivations/requirements.txt --python derivations/.venv/bin/python" >&2
	exit 1
fi

SANDBOX="$(mktemp -d /tmp/why-academy-e2e-XXXXXX)"
trap 'rm -rf "$SANDBOX"' EXIT

echo "[e2e] sandbox: $SANDBOX"

# Copy the real derivations/ tree (validators, verify.py, closure_test.py, etc.)
cp -R "$REPO/derivations" "$SANDBOX/derivations"
# Copy scripts/ (closure_test.sh, _derivation_python.sh, implement.sh)
cp -R "$REPO/scripts" "$SANDBOX/scripts"

# Clean out stale runtime artifacts from the copy
rm -rf "$SANDBOX/derivations/logs" "$SANDBOX/derivations/reports" "$SANDBOX/derivations/_evolutions"
rm -f "$SANDBOX/derivations/_epoch_state.json"

# ── 1. Config: enable bug_investigate ────────────────────────────────────
"$VENV_PY" - "$SANDBOX/derivations/configs/v5.json" <<'PYEOF'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["runner"]["bug_investigate"]["enabled"] = True
json.dump(d, open(p, "w"), indent=2)
print("[e2e] enabled bug_investigate in config")
PYEOF

# ── 2. Synthetic logs: 3 VALIDATOR_REJECTED edges for divide_both_sides ──
LOGS_DIR="$SANDBOX/derivations/logs/epoch_001"
mkdir -p "$LOGS_DIR"
"$VENV_PY" - "$LOGS_DIR/run_test.jsonl" <<'PYEOF'
import json, sys
p = sys.argv[1]
with open(p, "w") as f:
    for i in range(3):
        rec = {
            "timestamp": f"2026-06-19T10:0{i}:00Z",
            "target": f"target_{i}",
            "batch_id": "batch_test",
            "edge_results": [
                {"from": "n0", "to": "n1", "rule": "divide_both_sides",
                 "status": "FAIL", "reason": "dividing by 3 should give Eq(x, 5); got Eq(5, x)"}
            ]
        }
        f.write(json.dumps(rec) + "\n")
print(f"[e2e] wrote 3 synthetic VALIDATOR_REJECTED log records")
PYEOF

# ── 3. Epoch state: start at BUG_INVESTIGATE ─────────────────────────────
mkdir -p "$SANDBOX/derivations/reports/epoch_001"
"$VENV_PY" - "$SANDBOX/derivations/_epoch_state.json" <<'PYEOF'
import json, sys
p = sys.argv[1]
json.dump({"phase": "BUG_INVESTIGATE", "started_at": "2026-06-19T14:00:00Z"}, open(p, "w"), indent=2)
print("[e2e] _epoch_state.json: phase=BUG_INVESTIGATE")
PYEOF

# ── 4. Stub implement.sh (the only LLM call in the path) ─────────────────
# For BUGFIX, implement.sh would ask an LLM to edit the validator. We stub it
# to exit 0 (simulating "LLM succeeded"). The validator already accepts swapped
# orientation (commit 3957884), so the reproduction case will PASS without any
# code change. closure_test.sh runs REAL — it invokes closure_test.py which
# runs verify.verify_edge on the reproduction case.
cat >"$SANDBOX/scripts/implement.sh" <<'STUB'
#!/usr/bin/env bash
# STUB: simulates a successful LLM implementation without calling any LLM.
# Bump validator_version (the real implement.sh does this on success).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/scripts/_derivation_python.sh"
"$PY" -c '
import json, re
p = "derivations/state.json"
d = json.load(open(p))
old = d["validator_version"]
m = re.match(r"v?(\d+)", old)
new = f"v{int(m.group(1)) + 1}"
d["validator_version"] = new
json.dump(d, open(p, "w"), indent=2)
print(f"[stub-implement] validator_version: {old} -> {new}", flush=True)
'
exit 0
STUB
chmod +x "$SANDBOX/scripts/implement.sh"
echo "[e2e] stubbed implement.sh (exits 0, bumps validator_version)"

# ── 5. Run the real driver loop ──────────────────────────────────────────
echo "[e2e] running autonomous_epoch.py main()..."
cd "$SANDBOX"
DERIVATION_PYTHON="$VENV_PY" "$VENV_PY" derivations/autonomous_epoch.py 2>&1 | tee /tmp/e2e-driver.log

# ── 6. Assertions ────────────────────────────────────────────────────────
echo "[e2e] checking results..."
"$VENV_PY" - "$SANDBOX" <<'PYEOF'
import json, sys
from pathlib import Path
sandbox = Path(sys.argv[1])
errors = []

# (a) BUGFIX proposal was written by phase_bug_investigate
reports = sandbox / "derivations" / "reports" / "epoch_001"
props = sorted(reports.glob("proposal_bug_*.md"))
if not props:
    errors.append("no proposal_bug_*.md found in reports/epoch_001")
else:
    text = props[0].read_text()
    if "**Kind**: BUGFIX" not in text:
        errors.append(f"proposal {props[0].name} is not Kind: BUGFIX")
    if "**Seed hypothesis**: orientation_false_rejection" not in text:
        errors.append("proposal missing seed hypothesis id")
    if "## Reproduction case" not in text:
        errors.append("proposal missing reproduction case section")
    print(f"[e2e] PASS: proposal written -> {props[0].name}")

# (b) Closure sidecar exists with lift=1.0 (reproduction now passes)
closure_sidecars = sorted(reports.glob("proposal_bug_*_closure.json"))
if not closure_sidecars:
    errors.append("no closure sidecar found")
else:
    rec = json.loads(closure_sidecars[0].read_text())
    if rec.get("kind") != "BUGFIX":
        errors.append(f"closure kind={rec.get('kind')!r}, expected BUGFIX")
    if rec.get("lift_fraction") != 1.0:
        errors.append(f"closure lift={rec.get('lift_fraction')}, expected 1.0")
    if rec.get("actual_status") != "PASS":
        errors.append(f"closure actual_status={rec.get('actual_status')!r}, expected PASS")
    if rec.get("holdout_regressed") is not None:
        errors.append(f"unexpected holdout regression: {rec['holdout_regressed']}")
    print(f"[e2e] PASS: closure lift=1.0, actual=PASS, holdout=none")

# (c) Regression corpus entries were auto-written on promotion
pos = sandbox / "derivations" / "test_corpus" / "divide_both_sides" / "positive.json"
neg = sandbox / "derivations" / "test_corpus" / "divide_both_sides" / "negative.json"
if not pos.exists():
    errors.append("regression positive.json not written")
else:
    pos_entries = json.loads(pos.read_text())
    bugfix_entries = [e for e in pos_entries if "bugfix:orientation" in e.get("description", "")]
    if not bugfix_entries:
        errors.append("no bugfix regression entry in positive.json")
    else:
        print(f"[e2e] PASS: regression positive entry -> {bugfix_entries[0]['from_srepr']}")
if not neg.exists():
    errors.append("regression negative.json not written")
else:
    neg_entries = json.loads(neg.read_text())
    bugfix_neg = [e for e in neg_entries if "bugfix:orientation" in e.get("description", "")]
    if not bugfix_neg:
        errors.append("no bugfix regression entry in negative.json")
    else:
        print(f"[e2e] PASS: regression negative entry (must FAIL) present")

# (d) Driver reached DONE (CLOSE bumped the epoch)
state = json.loads((sandbox / "derivations" / "_epoch_state.json").read_text())
if state.get("phase") != "DONE":
    errors.append(f"driver ended at phase={state.get('phase')!r}, expected DONE")
else:
    print(f"[e2e] PASS: driver reached DONE")

# (e) Epoch was bumped (CLOSE phase ran)
epoch_state = json.loads((sandbox / "derivations" / "state.json").read_text())
if epoch_state.get("epoch") != 2:
    errors.append(f"state.json epoch={epoch_state.get('epoch')}, expected 2 (bumped by CLOSE)")
else:
    print(f"[e2e] PASS: epoch bumped 1 -> 2")

# (f) validator_version was bumped by stub implement.sh
if epoch_state.get("validator_version") != "v3":
    errors.append(f"validator_version={epoch_state.get('validator_version')!r}, expected v3")
else:
    print(f"[e2e] PASS: validator_version bumped v2 -> v3")

if errors:
    print()
    print("E2E FAILED:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print()
print("E2E PASSED: all assertions OK")
PYEOF
