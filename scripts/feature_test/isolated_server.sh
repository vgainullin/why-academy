# Sourced by scripts/feature_test.sh and scripts/e2e_reader.sh.
#
# start_isolated_server DIR: starts the site + API on a free port with its own
# local D1/R2 state in DIR/state and one seeded, signed-in account.
# Sets ORIGIN, TOKEN, SERVER_PID, PORT. stop_isolated_server stops it.

start_isolated_server() {
  local dir="$1"
  local wrangler=(npx wrangler -c "$ROOT/worker/wrangler.toml")
  mkdir -p "$dir/state"
  PORT=$(node -e "const s=require('net').createServer().listen(0,()=>{console.log(s.address().port);s.close()})")
  ORIGIN="http://localhost:$PORT"

  "${wrangler[@]}" d1 migrations apply why-academy --local --persist-to "$dir/state" > "$dir/setup.log" 2>&1
  TOKEN=$(node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))")
  local hash now
  hash=$(printf %s "$TOKEN" | shasum -a 256 | cut -d' ' -f1)
  now=$(node -e "console.log(Date.now())")
  "${wrangler[@]}" d1 execute why-academy --local --persist-to "$dir/state" --command \
    "INSERT INTO accounts (id, display_name, created_at, last_login_at) VALUES ('feature-tester', 'Feature Tester', $now, $now);
     INSERT INTO account_sessions (id, account_id, created_at, expires_at) VALUES ('$hash', 'feature-tester', $now, $((now + 86400000)));" \
    >> "$dir/setup.log" 2>&1

  "${wrangler[@]}" dev --port "$PORT" --persist-to "$dir/state" > "$dir/server.log" 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 1 90); do
    grep -q "Ready on" "$dir/server.log" && break
    kill -0 "$SERVER_PID" 2>/dev/null || { echo "Server exited:" >&2; tail -20 "$dir/server.log" >&2; return 1; }
    sleep 1
  done
  grep -q "Ready on" "$dir/server.log" || { echo "Server not ready after 90s" >&2; tail -20 "$dir/server.log" >&2; return 1; }
  curl -sf "$ORIGIN/api/me" -H "Cookie: __Host-wa_session=$TOKEN" > /dev/null \
    || { echo "Seeded session does not work against $ORIGIN" >&2; return 1; }
}

stop_isolated_server() {
  [[ -n "${SERVER_PID:-}" ]] || return 0
  # npx -> wrangler -> workerd: stop the whole tree, then anything left on the port.
  pkill -P "$SERVER_PID" 2>/dev/null || true
  kill "$SERVER_PID" 2>/dev/null || true
  lsof -ti "tcp:$PORT" 2>/dev/null | xargs kill 2>/dev/null || true
  SERVER_PID=""
}
