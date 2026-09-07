#!/usr/bin/env bash
# Bring up everything for local development.
#
#   ./scripts/dev.sh          start database, API and web
#   ./scripts/dev.sh --reset  drop and re-seed the database first
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
RESET=${1:-}

: "${DATABASE_URL:=postgresql+asyncpg://jst:jst@localhost:5433/jst}"
export DATABASE_URL
export LOG_JSON=${LOG_JSON:-false}
export NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL:-http://localhost:8000}
export API_BASE_URL=${API_BASE_URL:-http://localhost:8000}

if [[ ! -d .venv ]]; then
  echo "==> creating the Python environment"
  python3.12 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -e ./packages/shared_schemas -e ./packages/travel_mcp -e "./apps/api[dev]"
fi

echo "==> starting PostgreSQL and Redis"
docker compose up -d db redis
until docker compose exec -T db pg_isready -U jst -d jst >/dev/null 2>&1; do sleep 1; done

if [[ "$RESET" == "--reset" ]]; then
  echo "==> resetting the database"
  docker compose exec -T db psql -U jst -d jst -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" >/dev/null
fi

echo "==> applying migrations"
(cd apps/api && "$ROOT/.venv/bin/alembic" upgrade head)

echo "==> seeding demo data (idempotent)"
./.venv/bin/python scripts/seed.py

echo "==> starting the API on :8000"
./.venv/bin/python -m uvicorn jst_api.main:app --app-dir apps/api/src --reload --port 8000 &
API_PID=$!

if [[ ! -d apps/web/node_modules ]]; then
  echo "==> installing web dependencies"
  (cd apps/web && npm install --no-audit --no-fund)
fi

echo "==> starting the web app on :3000"
(cd apps/web && npm run dev) &
WEB_PID=$!

trap 'kill $API_PID $WEB_PID 2>/dev/null || true' EXIT INT TERM

cat <<'BANNER'

  Japan Second Trip is up.

    web    http://localhost:3000
    api    http://localhost:8000/docs
    ready  http://localhost:8000/ready
    admin  http://localhost:3000/admin   (token: ADMIN_TOKEN, default dev-admin-token)

  Ctrl-C to stop.

BANNER

wait
