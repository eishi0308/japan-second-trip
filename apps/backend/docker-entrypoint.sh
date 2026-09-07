#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="/app/src:${PYTHONPATH:-}"

if [[ "${RUN_MIGRATIONS:-true}" == "true" ]]; then
  echo "==> applying database migrations"
  (cd /app && alembic -c alembic.ini upgrade head)
fi

if [[ "${RUN_SEED:-true}" == "true" ]]; then
  echo "==> seeding demo catalogue and evidence (idempotent)"
  python /app/scripts/seed.py || echo "!! seeding failed; the API will start but /ready will report degraded"
fi

echo "==> starting: $*"
exec "$@"
