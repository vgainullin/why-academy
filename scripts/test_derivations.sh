#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

source "$ROOT/scripts/_derivation_python.sh"

"$PY" -m py_compile \
  derivations/graph_normalize.py \
  derivations/inner_evolve.py \
  derivations/canvas_check.py \
  derivations/target_check.py \
  derivations/verify.py

"$PY" -m unittest discover -s derivations/tests -p 'test_*.py'
