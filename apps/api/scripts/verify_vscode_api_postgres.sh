#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_CMD="docker compose"
DB_SERVICE="db"

echo "Starting Postgres via docker compose..."
$COMPOSE_CMD up -d "$DB_SERVICE"

PORT="$($COMPOSE_CMD port "$DB_SERVICE" 5432 | awk -F: '{print $2}')"
if [[ -z "$PORT" ]]; then
  PORT=5432
fi

echo "Waiting for Postgres on port $PORT..."
for i in {1..30}; do
  if $COMPOSE_CMD exec -T "$DB_SERVICE" pg_isready -U parallel -d parallel >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

export DATABASE_URL="postgresql+psycopg2://parallel:parallel@localhost:${PORT}/parallel"
export RAG_ENABLED="${RAG_ENABLED:-false}"
export SECRET_KEY="${SECRET_KEY:-verifysecret}"

echo "DATABASE_URL=$DATABASE_URL"

# Reset schema to keep the run isolated
$COMPOSE_CMD exec -T "$DB_SERVICE" psql -U parallel -d parallel -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"

echo "Running alembic migrations..."
alembic upgrade head

echo "Running VS Code API verifier..."
python3 scripts/verify_vscode_api.py

echo "Running pytest..."
pytest -q

echo "Running multi-worker SSE check..."
bash scripts/test_sse_multiworker.sh

echo "verify_vscode_api_postgres.sh completed successfully."
