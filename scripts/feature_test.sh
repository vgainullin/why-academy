#!/usr/bin/env bash
# LLM feature tester: a headless Claude drives a real browser (Playwright MCP)
# through a charter and writes a bug report plus UX feedback.
#
# Each run is isolated: its own local D1/R2 state, a seeded account, a fixture
# paper, a fresh in-memory browser profile. The tester has no built-in tools
# (no shell, no file access); it can only use the browser.
#
# Usage: scripts/feature_test.sh [--area reader] [--device ipad|desktop]
#                                [--model MODEL] [--budget USD] [--keep-state] [--smoke] [--no-ai]
# --smoke runs a two-item charter to check the setup cheaply.
# --no-ai hides OPENROUTER_API_KEY from the browser to test the error paths.
# AI features are exercised for real when OPENROUTER_API_KEY is set;
# otherwise the tester checks their error handling.
#
# Output: tests/feature-reports/<timestamp>-<area>/{report.md,findings.json,shots/,server.log}

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL="$ROOT/.claude/skills/feature-test"
PLAYWRIGHT_MCP="@playwright/mcp@0.0.82"

AREA=reader
DEVICE=ipad
MODEL=""
BUDGET=10
KEEP_STATE=0
SMOKE=0
NO_AI=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --area) AREA="$2"; shift 2 ;;
    --device) DEVICE="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
    --keep-state) KEEP_STATE=1; shift ;;
    --smoke) SMOKE=1; BUDGET=2; shift ;;
    --no-ai) NO_AI=1; shift ;;
    -h|--help) sed -n 2,17p "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

CHARTER="$SKILL/charters/$AREA.md"
[[ -f "$CHARTER" ]] || { echo "No charter for area '$AREA' ($CHARTER)" >&2; exit 2; }
case "$DEVICE" in
  ipad) DEVICE_ARGS='"--device", "iPad Pro 11"' ;;
  desktop) DEVICE_ARGS='"--viewport-size", "1280x860"' ;;
  *) echo "--device must be ipad or desktop" >&2; exit 2 ;;
esac

RUN="$ROOT/tests/feature-reports/$(date +%Y%m%d-%H%M%S)-$AREA"
mkdir -p "$RUN/state" "$RUN/shots" "$RUN/fixture"
WRANGLER=(npx wrangler -c "$ROOT/worker/wrangler.toml")
PORT=$(node -e "const s=require('net').createServer().listen(0,()=>{console.log(s.address().port);s.close()})")
ORIGIN="http://localhost:$PORT"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    # npx -> wrangler -> workerd: stop the whole tree, then anything left on the port.
    pkill -P "$SERVER_PID" 2>/dev/null || true
    kill "$SERVER_PID" 2>/dev/null || true
    lsof -ti "tcp:$PORT" 2>/dev/null | xargs kill 2>/dev/null || true
  fi
  # The kit holds the session token and possibly the AI key.
  rm -f "$RUN/testkit.js" "$RUN/mcp.json"
  [[ $KEEP_STATE == 1 ]] || rm -rf "$RUN/state"
}
trap cleanup EXIT

echo "Run: $RUN"

# ── Isolated server with a seeded account ──
"${WRANGLER[@]}" d1 migrations apply why-academy --local --persist-to "$RUN/state" > "$RUN/setup.log" 2>&1
TOKEN=$(node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))")
HASH=$(printf %s "$TOKEN" | shasum -a 256 | cut -d' ' -f1)
NOW=$(node -e "console.log(Date.now())")
"${WRANGLER[@]}" d1 execute why-academy --local --persist-to "$RUN/state" --command \
  "INSERT INTO accounts (id, display_name, created_at, last_login_at) VALUES ('feature-tester', 'Feature Tester', $NOW, $NOW);
   INSERT INTO account_sessions (id, account_id, created_at, expires_at) VALUES ('$HASH', 'feature-tester', $NOW, $((NOW + 86400000)));" \
  >> "$RUN/setup.log" 2>&1

"${WRANGLER[@]}" dev --port "$PORT" --persist-to "$RUN/state" > "$RUN/server.log" 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 90); do
  grep -q "Ready on" "$RUN/server.log" && break
  kill -0 "$SERVER_PID" 2>/dev/null || { echo "Server exited:" >&2; tail -20 "$RUN/server.log" >&2; exit 1; }
  sleep 1
done
grep -q "Ready on" "$RUN/server.log" || { echo "Server not ready after 90s" >&2; tail -20 "$RUN/server.log" >&2; exit 1; }
curl -sf "$ORIGIN/api/me" -H "Cookie: __Host-wa_session=$TOKEN" > /dev/null \
  || { echo "Seeded session does not work against $ORIGIN" >&2; exit 1; }

# ── Fixture, test kit, browser ──
node "$ROOT/scripts/feature_test/make_fixture.mjs" "$RUN/fixture/attention-note.pdf"

AI_KEY="${OPENROUTER_API_KEY:-}"
[[ $NO_AI == 1 ]] && AI_KEY=""
AI_KEY="$AI_KEY" node -e '
const cfg = { token: process.argv[1], origin: process.argv[2], openrouterKey: process.env.AI_KEY || "" };
process.stdout.write("const __WA_CONFIG = " + JSON.stringify(cfg) + ";\n");
' "$TOKEN" "$ORIGIN" > "$RUN/testkit.js"
cat "$ROOT/scripts/feature_test/testkit.js" >> "$RUN/testkit.js"

cat > "$RUN/mcp.json" <<EOF
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "$PLAYWRIGHT_MCP", "--headless", "--isolated", "--browser", "chrome",
               $DEVICE_ARGS,
               "--init-script", "$RUN/testkit.js",
               "--output-dir", "$RUN/shots",
               "--console-level", "warning"]
    }
  }
}
EOF

AI_NOTE="No AI key is set: test the AI features' error handling and manual fallbacks only."
[[ -n "$AI_KEY" ]] && AI_NOTE="An OpenRouter key is set in the browser: exercise the AI features for real and judge their output."

PROMPT="Run the feature test for area '$AREA'.

Run details:
- App URL: $ORIGIN/reader (already signed in as 'Feature Tester'; window.__wa is available on every page)
- Device: $DEVICE ($( [[ $DEVICE == ipad ]] && echo 'iPad Pro 11 emulation in headless Chrome' || echo '1280x860 desktop'))
- Fixture paper to upload: $RUN/fixture/attention-note.pdf (relative: fixture/attention-note.pdf)
- Screenshots: save as shots/NN-name.png (relative to the working directory, e.g. shots/01-import.png) and cite them by that name
- $AI_NOTE
- Date: $(date +%Y-%m-%d)

Follow the method and report format in your instructions. Your final message must be the report."

CHARTER_TEXT="$(cat "$CHARTER")"
if [[ $SMOKE == 1 ]]; then
  CHARTER_TEXT="# Charter: smoke

C1 Import: upload the fixture PDF with Add PDF; it opens and appears under Papers.
C2 Pen: with the Pen tool, __wa.penOnPage(1) draws ink that is still there after reload and is in __wa.serverItems('ink').

Skip the exploratory pass. Keep the report short."
fi
SYSTEM="$(cat "$SKILL/SKILL.md")

$CHARTER_TEXT"

echo "Tester running (budget \$$BUDGET)..."
set +e
# Run from the run folder: the browser resolves relative screenshot paths and
# allows file uploads only inside the working directory.
cd "$RUN"
claude -p "$PROMPT" \
  --append-system-prompt "$SYSTEM" \
  --restricted --tools "" \
  --mcp-config "$RUN/mcp.json" --strict-mcp-config \
  --allowedTools "mcp__playwright" \
  --permission-mode dontAsk \
  --no-session-persistence \
  --output-format json \
  --max-budget-usd "$BUDGET" \
  ${MODEL:+--model "$MODEL"} \
  > "$RUN/claude.json" 2> "$RUN/claude.stderr"
STATUS=$?
set -e

node - "$RUN" <<'EOF'
const fs = require('fs');
const run = process.argv[2];
let out;
try {
  out = JSON.parse(fs.readFileSync(run + '/claude.json', 'utf8'));
} catch (e) {
  console.error('Tester produced no JSON result; see claude.stderr');
  process.exit(1);
}
const report = out.result || '';
fs.writeFileSync(run + '/report.md', report);
const blocks = [...report.matchAll(/```json\s*([\s\S]*?)```/g)];
if (!blocks.length) {
  console.error('Report has no findings JSON block (is_error=' + out.is_error + ', subtype=' + out.subtype + ')');
  process.exit(1);
}
const findings = JSON.parse(blocks[blocks.length - 1][1]);
fs.writeFileSync(run + '/findings.json', JSON.stringify(findings, null, 2));
const by = s => findings.bugs.filter(b => b.severity === s).length;
const charter = findings.charter || [];
console.log(`Charter: ${charter.filter(c => c.result === 'pass').length} pass, ${charter.filter(c => c.result === 'fail').length} fail, ${charter.filter(c => c.result === 'blocked').length} blocked`);
console.log(`Bugs: ${by('critical')} critical, ${by('major')} major, ${by('minor')} minor, ${by('polish')} polish; UX notes: ${(findings.ux || []).length}`);
if (out.total_cost_usd !== undefined) console.log('Cost: $' + out.total_cost_usd.toFixed(2) + ', turns: ' + out.num_turns);
EOF
echo "Report: $RUN/report.md"
exit $STATUS
