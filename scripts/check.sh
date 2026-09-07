#!/usr/bin/env bash
# Everything CI runs, locally, in the same order.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=./.venv/bin
FAILED=()
run() {
  echo ""
  echo "==> $1"
  shift
  if "$@"; then echo "    ok"; else echo "    FAILED"; FAILED+=("$1"); fi
}

run "ruff format"   $PY/ruff format --check backend/src backend/tests evals packages scripts
run "ruff lint"     $PY/ruff check backend/src backend/tests evals packages scripts
run "mypy"          $PY/mypy backend/src/jst_api packages/shared_schemas/src packages/travel_mcp/src
run "pytest"        $PY/python -m pytest backend/tests -q
run "web typecheck" npm --prefix frontend run typecheck
run "web unit"      npm --prefix frontend test

echo ""
if [[ ${#FAILED[@]} -eq 0 ]]; then
  echo "All checks passed."
else
  echo "Failed: ${FAILED[*]}"
  exit 1
fi
