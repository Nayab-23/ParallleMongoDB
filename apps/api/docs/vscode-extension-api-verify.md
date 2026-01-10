# VS Code Extension API Verification (TestClient)

- Ran `python scripts/verify_vscode_api.py` against a fresh SQLite DB (`verify_vscode_api.db`), `RAG_ENABLED=false`, `SECRET_KEY=verifysecret`.
- Seeded org/users/workspaces/chats (u1 member of ws1, u2 member of ws2), created PATs via the API, and exercised endpoints through FastAPI `TestClient`.
- Result: all seven readiness checks **PASS** (routing, PAT security, authz, delta sync, context bundle, RAG, SSE events).

## Coverage by area
- **Routing/OpenAPI**: `/api/v1/me`, PAT CRUD, workspaces, chats/messages, tasks CRUD + delta params, context-bundle, RAG search, events are registered in `main.py` and respond with expected status codes.
- **PAT security**: token only on creation, listing hides secrets, secrets hashed with pepper, revoked/expired PATs now return 401.
- **PAT scopes**: `write` scope enforced for message/task mutations; read-only tokens cannot mutate data.
- **Auth/authorization**: 401 unauthenticated; 403 for non-members and ID-only endpoints; members scoped to their workspace.
- **Delta sync**: `updated_after` works for chats/tasks; soft deletes expose `deleted_at`; cursor pagination is deterministic (no duplicates) after descending-cursor fix.
- **Context bundle**: respects `max_*` and `recent_hours`, returns recent chats/messages and open tasks only.
- **RAG**: `/workspaces/{workspace_id}/rag/search` returns chunk schema (source_id/type/text/score/metadata) and stays workspace-scoped.
- **SSE events**: `text/event-stream` response emits message/task create/update/delete events with required fields; `since_event_id` resumes correctly.

## Fixes and added tests
- Normalized PAT expiry comparison to handle naive timestamps; expired PATs now reject with 401. Added pytest `test_expired_pat_rejected`.
- Cursor pagination for tasks (and chats) now paginates descending without duplicates. Added pytest `test_task_cursor_pagination_stable`.

## How to rerun
- `python scripts/verify_vscode_api.py` for the smoke checklist.
- `pytest` for regression coverage.
- `bash scripts/verify_vscode_api_postgres.sh` for the Postgres + alembic + verifier + pytest sweep (now also runs multi-worker SSE).
- `bash scripts/test_sse_stream.sh` for single-worker SSE.
- `bash scripts/test_sse_multiworker.sh` for multi-worker SSE.

## Multi-worker SSE verification
- Ran `bash scripts/test_sse_multiworker.sh` (uvicorn `--workers 2`, Postgres DB seed via verify helper).
- Observed `PASS multi-worker SSE (4 events received)`; SSE stream delivered message + task create/update/delete reliably with concurrent workers.
- Caveat: relies on local Postgres (docker-compose db) and uses PAT created via API; ensure port 5432 available and Docker running.
