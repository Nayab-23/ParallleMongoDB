# Demo Killer Verification Checklist

These are the 3 most likely causes of demo failure. Verify each before demo day.

---

## ❌ Demo Killer #1: Endpoint Path Mismatch

**Risk:** Web UI calls `/api/api/chats` (double prefix) or wrong path, causing silent 404s.

### How It Works (Current Setup)

**Config:**
- `API_BASE_URL` in dev: `/api` (proxied by Vite)
- Line 25 of config.js strips `/api` → becomes `""`
- Path construction: `"" + "/api/chats"` = `/api/chats` ✅

**Vite Proxy:**
```javascript
'/api': {
  target: 'http://localhost:8000',
  changeOrigin: true,
}
```

**Flow:**
1. Browser: `fetch('/api/chats')`
2. Vite proxy: Forwards to `http://localhost:8000/api/chats`
3. Backend: Receives `/api/chats`

### ✅ Verification Test (CRITICAL - Run This!)

**Step 1: Start backend and frontend**
```bash
# Terminal 1: Backend
cd apps/api
python -m uvicorn hack_main:app --reload --port 8000

# Terminal 2: Frontend
cd apps/web
npm run dev
```

**Step 2: Open DevTools and test**
```bash
# Open browser to http://localhost:5173
# Open DevTools (F12) → Network tab
# Clear network log
# In Console, run:
fetch('/api/health').then(r => r.json()).then(console.log)
```

**Expected:**
- **Network tab shows:** `GET /api/health` → Status 200
- **Console shows:** `{ok: true}`
- **Request URL:** `http://localhost:5173/api/health` (proxied)

**NOT expected:**
- `/api/api/health` (double prefix)
- `404 Not Found`
- CORS error

---

**Step 3: Test dispatch endpoint**
```javascript
// In browser console:
fetch('/api/chats', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({name: 'Test Chat'})
}).then(r => r.json()).then(console.log)
```

**Expected:**
- Network tab: `POST /api/chats` → Status 200
- Response: `{id: "...", chat_id: "...", name: "Test Chat", ...}`

---

**Step 4: Test task status endpoint**
```javascript
// In browser console (use chat_id from previous test):
fetch('/api/v1/extension/tasks/test-task-id')
  .then(r => r.text())
  .then(console.log)
```

**Expected:**
- Network tab: `GET /api/v1/extension/tasks/test-task-id`
- Response: 404 (task doesn't exist) or task data

**Critical:** Path should be exactly `/api/v1/extension/tasks/...`, NOT `/api/api/v1/...`

---

### 🔍 If You See Double `/api/api/...`

**Fix:**
```javascript
// In apps/web/src/config.js, line 25:
// REMOVE this line:
const apiBaseUrl = normalizedBaseUrl.replace(/\/api(?:\/v1)?$/, "");

// REPLACE with:
const apiBaseUrl = normalizedBaseUrl;
```

Then in demoApi.js, paths should NOT include `/api`:
```javascript
// BEFORE (correct as-is):
return request("/api/chats");

// Would become (if you remove the strip):
return request("/chats");
```

**Current setup is CORRECT** - don't change unless you see double prefix.

---

## ❌ Demo Killer #2: SSE Connected But No Events

**Risk:** Extension shows "Connected" but never receives tasks. Demo falls back to slow polling.

### Root Causes

1. **workspace_id mismatch:** Web sends `"1"` (string), backend expects `1` (number), or vice versa
2. **Event not emitted:** Task created but `_emit_event()` not called
3. **Wrong SSE URL:** Extension listening to `/api/events`, backend at `/api/v1/events`
4. **Event filter bug:** Events created but filtered out in query

### ✅ Verification Test (CRITICAL - Run This!)

**Step 1: Start backend with logging**
```bash
cd apps/api
python -m uvicorn hack_main:app --reload 2>&1 | tee backend.log
```

**Step 2: Monitor SSE in separate terminal**
```bash
# This simulates the extension listening
curl -N 'http://localhost:8000/api/v1/events?workspace_id=1'
```

**Expected output:**
```
data: heartbeat

:heartbeat

:heartbeat
```

**Step 3: Dispatch a task from web UI or curl**
```bash
# First create a chat
curl -X POST http://localhost:8000/api/chats \
  -H "Content-Type: application/json" \
  -d '{"name":"Test Chat"}'
# Note the chat_id from response

# Then dispatch a task
curl -X POST http://localhost:8000/api/chats/CHAT_ID/dispatch \
  -H "Content-Type: application/json" \
  -d '{"mode":"vscode","content":"Test task"}'
```

**Expected in SSE terminal (IMMEDIATELY):**
```
id: evt-abc-123
data: {"entity_type":"task","id":"task-xyz-456","payload":{...}}
```

**Backend logs should show:**
```json
{"tag":"SSE_EVENT","workspace_id":"1","event_id":"evt-abc-123","entity_type":"task"}
```

---

### 🚨 If No Event Appears

**Check 1: Event was created?**
```bash
# Check MongoDB events collection
mongosh "YOUR_MONGODB_URI"
> use parallel_demo  // or your DB name
> db.events.find().sort({created_at:-1}).limit(5).pretty()
```

**Expected:** Recent event with `entity_type: "task"`

**If missing:** `_emit_event()` not called in dispatch endpoint

---

**Check 2: workspace_id matches?**
```bash
# Check event workspace_id
> db.events.find({}, {workspace_id:1, entity_type:1}).limit(5)
```

**Expected:** `workspace_id: "1"` (string)

**If different:** Check `DEMO_WORKSPACE_ID` constant in hack_api.py (line 40)

---

**Check 3: SSE query working?**
```bash
# In backend logs, search for SSE queries
grep "SSE_CONNECT" backend.log
grep "SSE_EVENT" backend.log
```

**Expected:**
- `SSE_CONNECT` when curl connects
- `SSE_EVENT` immediately after task dispatch

**If SSE_CONNECT missing:** SSE endpoint not hit (wrong URL?)

**If SSE_EVENT missing but event exists in DB:** Query filter broken

---

### 🔧 Fix for Common Issues

**Issue:** Events created with `workspace_id: 1` (number), query expects `"1"` (string)

**Fix in hack_api.py:**
```python
# Line 40 - ensure it's a string:
DEMO_WORKSPACE_ID = "1"  # String, not int

# Line 176 in _emit_event:
"workspace_id": DEMO_WORKSPACE_ID,  # Should be "1" string
```

---

**Issue:** Event query uses wrong comparison

**Fix in hack_api.py (line 440):**
```python
# CORRECT:
query = {"workspace_id": workspace_id}  # String comparison
if last_id:
    query["event_id"] = {"$gt": last_id}  # Lexicographic comparison for UUIDs

# WRONG:
query = {"workspace_id": int(workspace_id)}  # Type mismatch
```

---

## ❌ Demo Killer #3: MongoDB Atlas Index/Health Issues

**Risk:** Demo crashes on `/api/demo/health` or vector search fails during live demo.

### Root Causes

1. **Vector search index not created** in MongoDB Atlas
2. **Index name mismatch:** `.env` says `memory_docs_embedding`, Atlas has `memory_index`
3. **Dimension mismatch:** Voyage 3 = 1024 dims, but index configured for 768
4. **IP not whitelisted** in Atlas Network Access
5. **Cluster paused** or sleeping (free tier)

### ✅ Verification Test (CRITICAL - Run This!)

**Step 1: Test basic MongoDB connection**
```bash
curl http://localhost:8000/api/demo/health
```

**Expected:**
```json
{"ok": true, "mongodb": "ok"}
```

**If fails:** Check `MONGODB_URI` in `.env` and Atlas IP whitelist

---

**Step 2: Test vector search (if using RAG)**
```bash
# First inject a test memory
curl -X POST http://localhost:8000/api/demo/inject_memory \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"test","title":"Test Doc","text":"This is a test document for vector search."}'
```

**Expected:**
```json
{"inserted": 1, "chunks": 1, "doc_ids": ["..."]}
```

**Backend logs should show:**
```json
{"tag":"VOYAGE_EMBED","model":"voyage-3","num_texts":1}
{"tag":"VOYAGE_EMBED_SUCCESS","num_embeddings":1}
```

---

**Step 3: Test vector search query**
```bash
curl -X POST http://localhost:8000/api/demo/ask \
  -H "Content-Type: application/json" \
  -d '{"target_agent_id":"test","question":"What is this about?"}'
```

**Expected:**
```json
{
  "answer": "...",
  "sources": [...],
  "trace_id": "..."
}
```

**Backend logs should show:**
```json
{"tag":"VECTOR_SEARCH","agent_id":"test","top_k":5,"index":"memory_docs_embedding"}
{"tag":"VECTOR_SEARCH_SUCCESS","num_results":1}
{"tag":"FIREWORKS_CHAT","purpose":"demo_ask"}
{"tag":"FIREWORKS_CHAT_SUCCESS"}
```

---

### 🚨 If Vector Search Fails

**Error:** `index not found` or `OperationFailure`

**Check 1: Index exists in Atlas?**
1. Log into MongoDB Atlas
2. Go to your cluster → Collections
3. Database: `parallel_demo` (or your DB name)
4. Collection: `memory_docs`
5. Search Indexes tab → Should see `memory_docs_embedding`

**If missing:** Create the index (see INTEGRATION_PLAN.md)

---

**Check 2: Index name matches?**
```bash
# Check .env
grep MONGODB_VECTOR_INDEX apps/api/.env
# Should show: MONGODB_VECTOR_INDEX=memory_docs_embedding

# Check what's actually in Atlas:
# Atlas → Collections → memory_docs → Search Indexes
# Name should match exactly
```

---

**Check 3: Dimensions match?**

**Voyage 3 uses 1024 dimensions**

Atlas index definition should have:
```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 1024,  // MUST be 1024 for Voyage 3
      "similarity": "cosine"
    }
  ]
}
```

**If mismatch:** Delete and recreate index with correct dimensions

---

### 🎯 Demo Strategy: Avoid Vector Search

If vector search is not critical for your demo:

**Option 1: Skip `/api/demo/ask` entirely**
- Focus on chat dispatch → extension loop
- Don't show RAG features

**Option 2: Ensure `/api/demo/health` works**
- This only tests MongoDB connection (no vector search)
- Safe to show during demo

**Option 3: Pre-test before demo**
- Run inject + ask before demo starts
- Verify it works
- Then use same queries during demo (pre-warmed)

---

## 🎯 Pre-Demo Checklist

Run all three killer checks **5 minutes before demo:**

### ✅ Killer #1: Path Mismatch
```bash
# In browser console:
fetch('/api/health').then(r => r.json()).then(console.log)
# Should see: {ok: true}
# Network tab: GET /api/health (NOT /api/api/health)
```

### ✅ Killer #2: SSE Events
```bash
# Terminal 1: Monitor SSE
curl -N 'http://localhost:8000/api/v1/events?workspace_id=1'

# Terminal 2: Dispatch task
curl -X POST http://localhost:8000/api/chats/CHAT_ID/dispatch \
  -H "Content-Type: application/json" \
  -d '{"mode":"vscode","content":"Test"}'

# Terminal 1 should show event IMMEDIATELY (< 1 second)
```

### ✅ Killer #3: MongoDB Health
```bash
curl http://localhost:8000/api/demo/health
# Should see: {"ok": true, "mongodb": "ok"}
```

---

## 🚨 Emergency Fixes During Demo

### If SSE fails during demo:
**Fallback:** Extension uses polling (`GET /api/v1/workspaces/1/sync`)
- Still works, just slower (5-second delay)
- Less impressive but functional

### If MongoDB fails during demo:
**Fallback:** Skip RAG demo entirely
- Focus on chat → dispatch → extension loop
- Say "we also have semantic search but let's focus on the core loop"

### If paths 404 during demo:
**Fallback:** Use curl commands instead of UI
- Have pre-written curl commands ready
- Show backend logs instead of UI
- Focus on observability ("look at these beautiful logs")

---

## 📊 Success Criteria

All three of these must pass:

- ✅ Browser `fetch('/api/health')` returns `{ok: true}` (no 404)
- ✅ SSE curl shows event within 1 second of dispatch
- ✅ `/api/demo/health` returns `{ok: true, mongodb: "ok"}`

**If all pass:** Demo will work! 🎉

**If any fail:** See emergency fixes above

---

**Last updated:** 2026-01-10
