# Smoke Test Checklist - Web ↔ Extension Integration

## Prerequisites

1. ✅ MongoDB Atlas cluster running
2. ✅ `.env` configured with MONGODB_URI, FIREWORKS_API_KEY, VOYAGE_API_KEY
3. ✅ Backend running: `python -m uvicorn hack_main:app --reload --port 8000`
4. ✅ MongoDB indexes created (see INTEGRATION_PLAN.md)

## Test Suite

### 1. Health Check

```bash
curl http://localhost:8000/api/health
```

**Expected:**
```json
{
  "status": "ok",
  "mode": "hackathon",
  "provider": "fireworks+voyage+mongodb"
}
```

---

### 2. Get Current User

```bash
curl http://localhost:8000/api/me
```

**Expected:**
```json
{
  "id": "demo-user-1",
  "name": "Demo User",
  "email": "demo@parallel.ai",
  "workspace_id": "1"
}
```

---

### 3. Create Chat

```bash
curl -X POST http://localhost:8000/api/chats \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Chat 1"}'
```

**Expected:**
```json
{
  "id": "UUID-HERE",
  "chat_id": "UUID-HERE",
  "name": "Test Chat 1",
  "workspace_id": "1",
  "created_at": "2026-01-10T...",
  "updated_at": "2026-01-10T...",
  "last_message_at": null
}
```

**Save the `chat_id` for next steps!**

---

### 4. List Chats

```bash
curl http://localhost:8000/api/chats
```

**Expected:**
```json
{
  "items": [
    {
      "id": "UUID",
      "chat_id": "UUID",
      "name": "Test Chat 1",
      "last_message_at": null,
      "updated_at": "2026-01-10T..."
    }
  ],
  "next_cursor": null
}
```

---

### 5. Get Chat Messages (empty initially)

```bash
# Replace CHAT_ID with actual chat_id from step 3
curl http://localhost:8000/api/chats/CHAT_ID/messages
```

**Expected:**
```json
[]
```

---

### 6. Dispatch Task to Extension

```bash
# Replace CHAT_ID
curl -X POST http://localhost:8000/api/chats/CHAT_ID/dispatch \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "vscode",
    "content": "Refactor the authentication module",
    "repo_id": "test-repo",
    "task_type": "EXECUTE"
  }'
```

**Expected:**
```json
{
  "task_id": "UUID-TASK",
  "status": "pending",
  "message": "Task UUID-TASK created and sent to extension"
}
```

**Save the `task_id` for next steps!**

---

### 7. Check Task Status

```bash
# Replace TASK_ID
curl http://localhost:8000/api/v1/extension/tasks/TASK_ID
```

**Expected:**
```json
{
  "task_id": "UUID-TASK",
  "status": "pending",
  "result": null,
  "error": null,
  "created_at": "2026-01-10T...",
  "updated_at": "2026-01-10T..."
}
```

---

### 8. Sync Endpoint (Polling)

```bash
curl http://localhost:8000/api/v1/workspaces/1/sync
```

**Expected:**
```json
{
  "items": [
    {
      "entity_type": "task",
      "id": "UUID-TASK",
      "payload": {
        "task_id": "UUID-TASK",
        "workspace_id": "1",
        "chat_id": "CHAT_ID",
        "repo_id": "test-repo",
        "task_type": "EXECUTE",
        "status": "pending",
        "payload": {
          "content": "Refactor the authentication module",
          "mode": "vscode",
          "patch": null
        },
        ...
      },
      "created_at": "2026-01-10T...",
      "updated_at": "2026-01-10T...",
      "deleted": false
    }
  ],
  "next_cursor": null,
  "done": true
}
```

---

### 9. SSE Stream (Manual Test)

Open in browser or use curl:

```bash
curl -N http://localhost:8000/api/v1/events?workspace_id=1
```

**Expected (stream output):**
```
data: heartbeat

id: UUID-EVENT
data: {"entity_type": "task", "id": "UUID-TASK", "payload": {...}, "created_at": "..."}

:heartbeat
```

**Note:** This is a streaming endpoint. It will keep the connection open and send events as they occur.

To test in browser:
1. Open DevTools → Network tab
2. Visit: `http://localhost:8000/api/v1/events?workspace_id=1`
3. Look for `text/event-stream` content type
4. Should see heartbeat messages every 5s

---

### 10. Record Edit Completion (Extension → Backend)

```bash
curl -X POST http://localhost:8000/api/v1/workspaces/1/vscode/agent/edits/record \
  -H "Content-Type: application/json" \
  -d '{
    "edit_id": "edit-123",
    "description": "Refactored authentication module",
    "source": "vscode-extension",
    "files_modified": ["src/auth.py", "src/utils.py"]
  }'
```

**Expected:**
```json
{
  "ok": true,
  "edit_id": "edit-123"
}
```

---

### 11. Extension Chat (with Fireworks AI)

```bash
# Replace CHAT_ID
curl -X POST http://localhost:8000/api/v1/vscode/chat \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "1",
    "chat_id": "CHAT_ID",
    "message": "Explain how to set up MongoDB indexes"
  }'
```

**Expected:**
```json
{
  "request_id": "UUID",
  "workspace_id": "1",
  "chat_id": "CHAT_ID",
  "user_message_id": "UUID",
  "assistant_message_id": "UUID",
  "reply": "To set up MongoDB indexes, you can use the createIndex() method...",
  "model": "accounts/fireworks/models/llama-v3p1-70b-instruct",
  "created_at": "2026-01-10T...",
  "duration_ms": 1234
}
```

---

### 12. Get Chat Messages (after chat)

```bash
# Replace CHAT_ID
curl http://localhost:8000/api/chats/CHAT_ID/messages
```

**Expected:**
```json
[
  {
    "id": "UUID",
    "message_id": "UUID",
    "chat_id": "CHAT_ID",
    "role": "user",
    "content": "Refactor the authentication module",
    "sender_id": "demo-user-1",
    "sender_name": "Demo User",
    "created_at": "2026-01-10T...",
    "metadata": {"mode": "vscode", "repo_id": "test-repo"}
  },
  {
    "id": "UUID",
    "message_id": "UUID",
    "chat_id": "CHAT_ID",
    "role": "user",
    "content": "Explain how to set up MongoDB indexes",
    "sender_id": "demo-user-1",
    "sender_name": "VS Code User",
    "created_at": "2026-01-10T...",
    "metadata": {"source": "vscode", "repo": null}
  },
  {
    "id": "UUID",
    "message_id": "UUID",
    "chat_id": "CHAT_ID",
    "role": "assistant",
    "content": "To set up MongoDB indexes, you can use...",
    "sender_id": null,
    "sender_name": "AI Assistant",
    "created_at": "2026-01-10T...",
    "metadata": {"model": "accounts/fireworks/models/llama-v3p1-70b-instruct", "source": "vscode"}
  }
]
```

---

## MongoDB Verification

### Check Collections

```javascript
// Connect to MongoDB Atlas using mongosh or Compass
use parallel_demo

// Count documents
db.chats.countDocuments()        // Should be > 0
db.messages.countDocuments()     // Should be > 0
db.tasks.countDocuments()        // Should be > 0
db.events.countDocuments()       // Should be > 0
db.edits.countDocuments()        // Should be > 0

// View latest chat
db.chats.find().sort({created_at: -1}).limit(1).pretty()

// View latest task
db.tasks.find().sort({created_at: -1}).limit(1).pretty()

// View latest event
db.events.find().sort({created_at: -1}).limit(1).pretty()
```

---

## Integration Test (Manual)

### Full Loop Test

1. **Start Backend**
   ```bash
   cd /Users/severinspagnola/Desktop/MongoDBHack/apps/api
   source .venv/bin/activate
   python -m uvicorn hack_main:app --reload --port 8000
   ```

2. **Start Frontend**
   ```bash
   cd /Users/severinspagnola/Desktop/MongoDBHack/apps/web
   npm run dev
   # Open http://localhost:5173
   ```

3. **Start Extension** (in VS Code)
   ```bash
   # Open MongoDBExtn folder
   code /Users/severinspagnola/Desktop/MongoDBExtn
   # Press F5 to launch Extension Development Host
   ```

4. **Test Flow:**
   - [ ] Frontend: Create a chat
   - [ ] Frontend: Send a message with "dispatch to VS Code" mode
   - [ ] Extension: Should receive notification (check sidebar or notifications)
   - [ ] Extension: Accept task
   - [ ] Extension: Record completion
   - [ ] Frontend: Poll task status → should show "done"

---

## Troubleshooting

### Backend Won't Start

**Error:** `Missing required env vars`
**Fix:** Check `.env` file has all required keys:
```bash
cd /Users/severinspagnola/Desktop/MongoDBHack/apps/api
cat .env | grep -E '(MONGODB_URI|FIREWORKS_API_KEY|VOYAGE_API_KEY)'
```

---

### MongoDB Connection Failed

**Error:** `ServerSelectionTimeoutError`
**Fix:**
1. Check `MONGODB_URI` is correct
2. Verify IP whitelist in MongoDB Atlas (add 0.0.0.0/0 for testing)
3. Test connection: `mongosh "YOUR_MONGODB_URI"`

---

### Fireworks AI 401 Unauthorized

**Error:** `401 Client Error: Unauthorized`
**Fix:**
1. Verify `FIREWORKS_API_KEY` in .env
2. Test API key manually:
   ```bash
   curl https://api.fireworks.ai/inference/v1/models \
     -H "Authorization: Bearer YOUR_KEY"
   ```

---

### SSE Not Working

**Error:** `EventSource failed` or no events received
**Fix:**
1. Check browser console for CORS errors
2. Verify backend is running on port 8000
3. Test SSE endpoint:
   ```bash
   curl -N http://localhost:8000/api/v1/events?workspace_id=1
   # Should print "data: heartbeat" every 5s
   ```

---

### Extension Not Receiving Tasks

**Fix:**
1. Check extension config points to `http://localhost:8000`
2. Verify SSE connection in extension logs
3. Test sync endpoint: `curl http://localhost:8000/api/v1/workspaces/1/sync`
4. Check MongoDB `events` collection has documents

---

## Success Criteria

✅ All curl commands return expected responses
✅ MongoDB collections populated with data
✅ SSE stream sends heartbeats
✅ Fireworks AI returns chat responses
✅ Full loop: Web → Task → Extension → Completion → Status works

---

## Demo Script

For live demo, use this sequence:

1. **Show Health:** `curl http://localhost:8000/api/health`
2. **Create Chat:** `curl -X POST http://localhost:8000/api/chats -H "Content-Type: application/json" -d '{"name":"Live Demo"}'`
3. **Dispatch Task:** `curl -X POST http://localhost:8000/api/chats/CHAT_ID/dispatch -H "Content-Type: application/json" -d '{"mode":"vscode","content":"Add error handling","repo_id":"demo"}'`
4. **Show SSE:** Open browser to `http://localhost:8000/api/v1/events?workspace_id=1`
5. **Extension:** Show task notification in VS Code
6. **Record Edit:** Extension automatically posts completion
7. **Check Status:** `curl http://localhost:8000/api/v1/extension/tasks/TASK_ID`

**Time:** ~3 minutes

**Talking Points:**
- Sponsor stack: Fireworks AI for LLM, Voyage for embeddings, MongoDB Atlas for storage
- Real-time: SSE stream pushes tasks to extension instantly
- Bidirectional: Web→Extension for tasks, Extension→Web for completions
- Scalable: MongoDB Atlas handles concurrent users, Fireworks handles LLM load
