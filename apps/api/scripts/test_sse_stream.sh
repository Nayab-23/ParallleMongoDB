#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export SECRET_KEY="${SECRET_KEY:-ssepatsecret}"
export RAG_ENABLED="${RAG_ENABLED:-false}"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg2://parallel:parallel@localhost:5432/parallel}"

SSE_LOG="$(mktemp /tmp/sse_events.XXXXXX)"
UVICORN_LOG="$(mktemp /tmp/sse_uvicorn.XXXXXX)"

cleanup() {
  if [[ -n "${SSE_PID:-}" ]]; then kill "$SSE_PID" 2>/dev/null || true; fi
  if [[ -n "${SERVER_PID:-}" ]]; then kill "$SERVER_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT

echo "Seeding database at $DATABASE_URL..."
python3 - <<'PY'
from scripts.verify_vscode_api import configure_db, seed_data, deps

SessionLocal = configure_db()
seed_data(SessionLocal)
PY

echo "Starting API server for SSE test..."
DATABASE_URL="$DATABASE_URL" SECRET_KEY="$SECRET_KEY" RAG_ENABLED="$RAG_ENABLED" python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload --log-level warning >"$UVICORN_LOG" 2>&1 &
SERVER_PID=$!

for i in {1..30}; do
  code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs || true)
  if [[ "$code" == "200" ]]; then
    break
  fi
  sleep 1
done

JWT=$(python3 - <<'PY'
from jose import jwt
import os
print(jwt.encode({"sub": "u1"}, os.environ.get("SECRET_KEY", "ssepatsecret"), algorithm="HS256"))
PY
)

PAT_RESPONSE=$(curl -s -X POST "http://localhost:8000/api/v1/auth/pat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${JWT}" \
  -d '{"name":"sse-test","scopes":["write"]}')
PAT=$(PAT_RESPONSE="$PAT_RESPONSE" python3 - <<'PY'
import json, os
resp = os.environ.get("PAT_RESPONSE", "")
token = ""
if resp.strip():
    try:
        token = json.loads(resp).get("token", "")
    except Exception:
        token = ""
print(token)
PY
)

if [[ -z "$PAT" || "$PAT" == "null" ]]; then
  echo "Failed to create PAT for SSE test; response: ${PAT_RESPONSE}"
  exit 1
fi

echo "Opening SSE stream..."
curl -s -N "http://localhost:8000/api/v1/events?workspace_id=ws1" \
  -H "Authorization: Bearer ${PAT}" >"$SSE_LOG" 2>&1 &
SSE_PID=$!
sleep 2

echo "Triggering message and task events..."
MSG_STATUS=$(curl -s -o /tmp/sse_msg.json -w "%{http_code}" -X POST "http://localhost:8000/api/v1/chats/chat1/messages" \
  -H "Authorization: Bearer ${PAT}" \
  -H "Content-Type: application/json" \
  -d '{"content":"sse message","metadata":{"source":"sse-script"}}')
if [[ "$MSG_STATUS" != "201" ]]; then
  echo "Message creation failed (status $MSG_STATUS): $(cat /tmp/sse_msg.json)"
  exit 1
fi

TASK_RESPONSE=$(curl -s -X POST "http://localhost:8000/api/v1/workspaces/ws1/tasks" \
  -H "Authorization: Bearer ${PAT}" \
  -H "Content-Type: application/json" \
  -d '{"title":"sse task"}')
TASK_ID=$(TASK_RESPONSE="$TASK_RESPONSE" python3 - <<'PY'
import os, json
resp = os.environ.get("TASK_RESPONSE", "")
task_id = ""
if resp.strip():
    try:
        task_id = json.loads(resp).get("id", "")
    except Exception:
        task_id = ""
print(task_id)
PY
)

if [[ -z "$TASK_ID" || "$TASK_ID" == "null" ]]; then
  echo "Failed to create task for SSE test; response: ${TASK_RESPONSE}"
  exit 1
fi

curl -s -X PATCH "http://localhost:8000/api/v1/tasks/${TASK_ID}" \
  -H "Authorization: Bearer ${PAT}" \
  -H "Content-Type: application/json" \
  -d '{"status":"in_progress"}' >/dev/null

curl -s -X DELETE "http://localhost:8000/api/v1/tasks/${TASK_ID}" \
  -H "Authorization: Bearer ${PAT}" >/dev/null

sleep 3
kill "$SSE_PID" 2>/dev/null || true

EVENT_COUNT=$(grep -c "^data:" "$SSE_LOG" || true)
if [[ "$EVENT_COUNT" -ge 4 ]]; then
  echo "PASS SSE stream (${EVENT_COUNT} events received)"
else
  echo "FAIL SSE stream (${EVENT_COUNT} events received)"
  echo "SSE log:"
  cat "$SSE_LOG"
  exit 1
fi

echo "Logs: SSE -> $SSE_LOG, server -> $UVICORN_LOG"
