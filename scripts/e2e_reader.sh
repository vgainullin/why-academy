#!/usr/bin/env bash
# Reader regression suite (tests/e2e/reader.e2e.mjs) against an isolated
# server with a seeded account. Needs Google Chrome installed.
# Screenshots: tests/e2e/out/

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$(mktemp -d "${TMPDIR:-/tmp}/why-e2e.XXXXXX")"
OUT="$ROOT/tests/e2e/out"
mkdir -p "$OUT"
source "$ROOT/scripts/feature_test/isolated_server.sh"
trap 'stop_isolated_server; rm -rf "$RUN"' EXIT

start_isolated_server "$RUN"
node "$ROOT/scripts/feature_test/make_fixture.mjs" "$RUN/attention-note.pdf"
node "$ROOT/scripts/feature_test/make_fixture.mjs" "$RUN/plain-note.pdf" --no-outline
E2E_ORIGIN="$ORIGIN" E2E_TOKEN="$TOKEN" E2E_FIXTURE="$RUN/attention-note.pdf" E2E_FIXTURE_PLAIN="$RUN/plain-note.pdf" E2E_OUT="$OUT" \
  node "$ROOT/tests/e2e/reader.e2e.mjs"
