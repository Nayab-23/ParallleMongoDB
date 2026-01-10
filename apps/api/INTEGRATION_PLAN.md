# Web ↔ Extension Integration Plan

## Overview

This document outlines the minimal backend surface required to enable the **Web App ↔ VS Code Extension** demo loop using:
- **MongoDB Atlas** for data storage
- **Fireworks AI** for LLM responses
- **Voyage AI** for embeddings (optional, not used in basic loop)

## Demo Loop

```
1. CREATE CHAT (web)
   Web → POST /api/chats {name: "Demo Chat"}
   Web ← {id: "chat123", chat_id: "chat123", ...}

2. DISPATCH TASK (web → extension)
   Web → POST /api/chats/chat123/dispatch
         {mode: "vscode", content: "Refactor auth.py", repo_id: "myrepo"}
   Web ← {task_id: "task456", status: "pending"}

3. RECEIVE TASK (extension via SSE or polling)
   Extension listens → GET /api/v1/events?workspace_id=1 (SSE)
   Extension ← data: {"entity_type": "task", "id": "task456", payload: {...}}

   OR: Extension polls → GET /api/v1/workspaces/1/sync
       Extension ← {items: [{entity_type: "task", id: "task456", ...}]}

4. EXECUTE (extension)
   - Extension shows task in sidebar/notification
   - User approves or auto-executes
   - Extension makes code changes

5. RECORD COMPLETION (extension → backend)
   Extension → POST /api/v1/workspaces/1/vscode/agent/edits/record
               {edit_id: "edit789", files_modified: ["auth.py"], ...}
   Backend ← {ok: true}

6. POLL STATUS (web)
   Web → GET /api/v1/extension/tasks/task456
   Web ← {status: "done", result: {...}}
```

## Endpoints Implemented

### Core (10 endpoints in hack_api.py)

| # | Method | Path | Purpose |
|---|--------|------|---------|
| 1 | POST | `/api/chats` | Create chat |
| 2 | GET | `/api/chats` | List chats |
| 3 | GET | `/api/chats/{id}/messages` | Get messages |
| 4 | POST | `/api/chats/{id}/dispatch` | Dispatch to extension |
| 5 | GET | `/api/v1/extension/tasks/{id}` | Get task status |
| 6 | GET | `/api/v1/workspaces/{id}/sync` | Sync (polling) |
| 7 | GET | `/api/v1/events` | SSE stream |
| 8 | POST | `/api/v1/workspaces/{id}/vscode/agent/edits/record` | Record edit |
| 9 | POST | `/api/v1/vscode/chat` | Extension chat (Fireworks AI) |
| 10 | GET | `/api/me` | Get current user |

Plus bonus:
- `GET /api/health` - Health check

## MongoDB Collections

```javascript
// chats
{
  chat_id: string (UUID),
  name: string,
  workspace_id: "1",
  created_at: ISODate,
  updated_at: ISODate,
  last_message_at: ISODate | null
}
// Index: {chat_id: 1} unique, {workspace_id: 1, updated_at: -1}

// messages
{
  message_id: string (UUID),
  chat_id: string,
  role: "user" | "assistant" | "system",
  content: string,
  sender_id: string | null,
  sender_name: string | null,
  created_at: ISODate,
  metadata: object
}
// Index: {message_id: 1} unique, {chat_id: 1, created_at: -1}

// tasks
{
  task_id: string (UUID),
  workspace_id: "1",
  chat_id: string | null,
  repo_id: string | null,
  task_type: string, // "EXECUTE", "NOTIFY", etc.
  status: "pending" | "running" | "done" | "error",
  payload: object,
  result: object | null,
  error: string | null,
  created_at: ISODate,
  updated_at: ISODate
}
// Index: {task_id: 1} unique, {workspace_id: 1, status: 1, created_at: -1}

// events (for SSE)
{
  event_id: string (UUID),
  workspace_id: "1",
  entity_type: "task" | "message" | "edit",
  entity_id: string,
  payload: object,
  created_at: ISODate
}
// Index: {event_id: 1} unique, {workspace_id: 1, created_at: -1}

// edits
{
  edit_id: string,
  workspace_id: "1",
  description: string,
  source: "vscode-extension",
  files_modified: [string],
  created_at: ISODate
}
// Index: {edit_id: 1} unique, {workspace_id: 1, created_at: -1}
```

## Setup Instructions

### 1. Environment Variables

Add to `/Users/severinspagnola/Desktop/MongoDBHack/apps/api/.env`:

```bash
# MongoDB Atlas
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/
MONGODB_DB=parallel_demo
MONGODB_VECTOR_INDEX=memory_docs_embedding

# Fireworks AI
FIREWORKS_API_KEY=your-key-here
FIREWORKS_BASE_URL=https://api.fireworks.ai/inference/v1
FIREWORKS_MODEL=accounts/fireworks/models/llama-v3p1-70b-instruct

# Voyage AI (for embeddings - optional for basic demo)
VOYAGE_API_KEY=your-key-here
VOYAGE_MODEL=voyage-3
```

### 2. Create MongoDB Indexes

```javascript
// Connect to your MongoDB Atlas cluster
use parallel_demo

// Create indexes
db.chats.createIndex({chat_id: 1}, {unique: true})
db.chats.createIndex({workspace_id: 1, updated_at: -1})

db.messages.createIndex({message_id: 1}, {unique: true})
db.messages.createIndex({chat_id: 1, created_at: -1})

db.tasks.createIndex({task_id: 1}, {unique: true})
db.tasks.createIndex({workspace_id: 1, status: 1, created_at: -1})
db.tasks.createIndex({chat_id: 1})

db.events.createIndex({event_id: 1}, {unique: true})
db.events.createIndex({workspace_id: 1, created_at: -1})

db.edits.createIndex({edit_id: 1}, {unique: true})
db.edits.createIndex({workspace_id: 1, created_at: -1})
```

### 3. Run Backend

```bash
cd /Users/severinspagnola/Desktop/MongoDBHack/apps/api

# Ensure .env is configured
source .venv/bin/activate  # or your venv

# Install dependencies if needed
pip install pymongo[srv]

# Run hack_main.py
python -m uvicorn hack_main:app --reload --port 8000
```

### 4. Test Endpoints

See `SMOKE_TEST.md` for curl commands.

### 5. Run Frontend

```bash
cd /Users/severinspagnola/Desktop/MongoDBHack/apps/web
npm run dev
# Visits http://localhost:5173
```

### 6. Run Extension

Open MongoDBExtn in VS Code:
```bash
code /Users/severinspagnola/Desktop/MongoDBExtn
# Press F5 to launch extension development host
```

## Event Flow Details

### SSE Stream Format

Extension subscribes:
```
GET /api/v1/events?workspace_id=1 HTTP/1.1
Authorization: Bearer <token>
```

Server sends:
```
id: event123
data: {"entity_type": "task", "id": "task456", "payload": {...}}

id: event124
data: {"entity_type": "message", "id": "msg789", "payload": {...}}

:heartbeat
```

### Task Lifecycle

1. **Created** (web dispatches)
   ```json
   {
     "task_id": "task456",
     "status": "pending",
     "payload": {
       "content": "Refactor auth.py",
       "mode": "vscode"
     }
   }
   ```

2. **Received** (extension picks up via SSE/polling)
   - Extension shows notification
   - User approves

3. **Completed** (extension records)
   ```json
   POST /api/v1/workspaces/1/vscode/agent/edits/record
   {
     "edit_id": "edit789",
     "description": "Refactored auth.py",
     "files_modified": ["src/auth.py"]
   }
   ```

4. **Status Check** (web polls)
   ```json
   GET /api/v1/extension/tasks/task456
   {
     "task_id": "task456",
     "status": "done",
     "result": {...}
   }
   ```

## What's NOT Included

To keep the demo minimal, these features are **NOT** implemented:

- ❌ Full authentication (uses demo user)
- ❌ Database migrations (manual index creation)
- ❌ Admin panel
- ❌ Gmail/Calendar integrations
- ❌ Invite system
- ❌ RAG search (can be added via Voyage embeddings)
- ❌ Multi-workspace support (hardcoded workspace_id="1")
- ❌ User management
- ❌ OAuth flows
- ❌ Postgres/SQLAlchemy
- ❌ OpenAI

## Adding RAG (Optional)

The demo backend (`/api/demo/ask`) already uses Voyage embeddings for semantic search. To add RAG to chat:

1. Index chat messages with Voyage embeddings
2. Add vector search to `/api/chats/{id}/dispatch`
3. Include relevant context in task payload

See `hack_main.py` lines 196-250 for the existing RAG implementation.

## Troubleshooting

### Extension Not Receiving Tasks

1. Check SSE connection: Open browser DevTools → Network → EventSource
2. Verify `workspace_id=1` in query params
3. Check MongoDB `events` collection for new documents
4. Test polling endpoint: `curl http://localhost:8000/api/v1/workspaces/1/sync`

### Chat Not Creating

1. Check MongoDB connection: `curl http://localhost:8000/api/health`
2. Verify `chats` collection exists
3. Check backend logs for errors

### Fireworks AI Errors

1. Verify `FIREWORKS_API_KEY` in .env
2. Check model name: `accounts/fireworks/models/llama-v3p1-70b-instruct`
3. Test manually:
   ```bash
   curl -X POST http://localhost:8000/api/v1/vscode/chat \
     -H "Content-Type: application/json" \
     -d '{"workspace_id":"1","chat_id":"test","message":"Hello"}'
   ```

## Next Steps

1. ✅ Test basic loop with curl (see SMOKE_TEST.md)
2. ✅ Test web app creates chat
3. ✅ Test web app dispatches task
4. ✅ Test extension receives task (SSE)
5. ✅ Test extension records completion
6. ✅ Test web app polls status
7. Add UI polish (optional)
8. Add RAG integration (optional)
