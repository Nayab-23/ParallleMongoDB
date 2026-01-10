# VS Code Extension API (v1)

Base path: `/api/v1`

Authentication: `Authorization: Bearer <token>` where `<token>` is a PAT created via `POST /api/v1/auth/pat`. Tokens are returned once on creation and stored hashed. All requests are workspace-scoped and enforce membership.
Scopes: PATs can include granular scopes (`tasks:read`, `files:read`, `edits:propose`, `edits:apply`, `commands:run`) in addition to `read`/`write` shorthand.

## Auth / Identity
- `GET /api/v1/me` → user id, name, email, workspaces (id, name, role).
- `POST /api/v1/auth/pat` body `{ name, scopes[], expires_at? }` → returns `{ token, pat }`. Token shown once.
- `GET /api/v1/auth/pat` → list PAT metadata (no raw token).
- `DELETE /api/v1/auth/pat/{pat_id}` → revoke PAT.

## Workspaces
- `GET /api/v1/workspaces` → workspaces the user can access.

## Chats
- `GET /api/v1/workspaces/{workspace_id}/chats?updated_after=&cursor=&limit=` → delta-friendly chat list including `deleted_at`.
- `GET /api/v1/chats/{chat_id}/messages?after_message_id=&limit=` → paginated message history.
- `POST /api/v1/chats/{chat_id}/messages` body `{ content, metadata? }` → create message authored by current user (metadata can include `source`, `file_path`, `selection`) — requires `write` scope.

## Tasks
- `GET /api/v1/workspaces/{workspace_id}/tasks?updated_after=&cursor=&limit=` → includes `deleted_at` for soft deletes.
- `POST /api/v1/workspaces/{workspace_id}/tasks` body `{ title, description?, status?, due_at?, priority?, tags[]? }` — requires `write` scope.
- `PATCH /api/v1/tasks/{task_id}` → partial update — requires `write` scope.
- `DELETE /api/v1/tasks/{task_id}` → soft delete (sets `deleted_at`) — requires `write` scope.

## Context Bundle
- `GET /api/v1/workspaces/{workspace_id}/context-bundle?max_chats=&max_messages=&max_tasks=&recent_hours=` → recent chats, messages, and open tasks for the workspace.

## RAG Search
- `POST /api/v1/workspaces/{workspace_id}/rag/search` body `{ query, room_id?, top_k?, filters? }` → array of chunks `{ source_id, source_type, text, score, metadata }`. Uses pgvector cosine when enabled; falls back to recency if embeddings missing.

## Realtime Events (SSE)
- `GET /api/v1/events?workspace_id=&since_event_id=` (or `Last-Event-ID` header) → SSE stream emitting `chat.message.created`, `task.created/updated/deleted` with payload `{ event_id, event_type, entity_type, entity_id, workspace_id, room_id, occurred_at, payload }`. Heartbeats sent as comments; IDs monotonic per workspace; reconnect resumes from last id.

# VS Code Extension Integration

## Auth
- Use PAT/extension token created via `POST /api/v1/auth/pat` (Bearer pat_<id>.<secret>).
- Scopes: `read` for sync/RAG, `write` for mutations.
- Rate limited token creation (10/min).

## Bootstrap
- `GET /api/v1/bootstrap` → user identity, accessible workspaces, per-workspace sync cursors (`timestamp|id`). Cache-Control: `private, max-age=30`.

## Sync
- `GET /api/v1/workspaces/{workspace_id}/sync?since=<cursor>&limit=` returns messages/tasks since cursor, tombstones for deletes, and `next_cursor`. Cursor ordering `(updated_at, id)` to avoid duplicates under identical timestamps.

## SSE
- `GET /api/v1/events?workspace_id=...&since_event_id=` or `Last-Event-ID` header.
- Events include: `event_id`, `event_type`, `entity_type`, `entity_id`, `workspace_id`, `room_id`, `occurred_at`, `payload`.
- Heartbeats keep connections alive; monotonic IDs per workspace; replay from last id on reconnect.

## RAG
- `POST /api/v1/workspaces/{workspace_id}/rag/search` with `query` (optional `room_id`) returns chunks with `source_id`, `source_type`, `text`, `score`, `metadata`.
- Uses pgvector cosine when available; falls back to recency otherwise.

## Editor-Native Agent
- `POST /api/v1/workspaces/{workspace_id}/vscode/agent/propose` → propose edits/commands using workspace file context.
- Requires scopes: `edits:propose`, `files:read` (when file contents included), `files:search` (when search results included), `edits:apply` (for `mode=apply`), `commands:run` (when command results included / commands suggested).
- The backend enriches prompts with workspace RAG context (recent messages, team activity, timeline) when available.
- Provide `repo.root` when sending absolute paths so the backend can normalize to safe relative paths.

Request body (trimmed):
```json
{
  "request": "Add logging around auth failures",
  "mode": "dry-run",
  "repo": {
    "name": "parallel-backend",
    "files": [
      {
        "relative": "app/api/v1/auth.py",
        "content": "..."
      }
    ],
    "searchResults": [
      { "file": "app/api/v1/auth.py", "line": 42, "preview": "raise HTTPException(...)" }
    ],
    "commandResults": [
      { "command": "pytest tests/test_vscode_api.py", "exitCode": 0, "stdout": "..." }
    ],
    "diagnostics": []
  },
  "output": { "format": "fullText", "max_files": 5, "max_commands": 3 }
}
```

Response body (trimmed):
```json
{
  "plan": ["Review auth flow", "Update logging", "Validate tests"],
  "edits": [{ "filePath": "app/api/v1/auth.py", "newText": "...", "diff": "..." }],
  "commands": [{ "command": "pytest tests/test_vscode_api.py", "purpose": "Verify changes" }],
  "dryRun": true,
  "contextUsed": { "tasks": 0, "conversations": 1, "rag_messages": 2 }
}
```

## VS Code Chat
- `POST /api/v1/vscode/chat` → conversational assistant for the VS Code sidebar, now optionally enriched with repo context.
- Requires scope: `chats:write` (and `files:read` / `files:search` when file content or search results are included).

Request body (trimmed):
```json
{
  "workspace_id": "room-123",
  "chat_id": "chat-456",
  "message": "What is this repo about?",
  "repo": {
    "name": "parallel-backend",
    "open_files": ["app/api/v1/vscode.py"],
    "files": [
      { "relative": "app/api/v1/vscode.py", "content": "..." }
    ],
    "searchResults": [
      { "file": "app/api/v1/vscode.py", "line": 20, "preview": "VSCODE_SYSTEM_PROMPT" }
    ],
    "diagnostics": []
  }
}
```

## Headers
- `Authorization: Bearer <PAT>`
- `Content-Type: application/json`

## Notes
- All endpoints enforce workspace membership (RoomMember).
- Delta sync uses `updated_after` plus cursor pagination.
- Deletions are signaled via `deleted_at` for tasks/chats/messages.
- PATs are hashed at rest and record `last_used_at` on each request.
