#!/usr/bin/env bash
# Resolve the Python interpreter for derivation pipeline wrappers.
#
# Callers may set DERIVATION_PYTHON explicitly. Otherwise use the local
# derivations venv when present, falling back to PYTHON or python3.

if [[ -z "${ROOT:-}" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

if [[ -n "${DERIVATION_PYTHON:-}" ]]; then
  PY="$DERIVATION_PYTHON"
elif [[ -x "$ROOT/derivations/.venv/bin/python" ]]; then
  PY="$ROOT/derivations/.venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi
