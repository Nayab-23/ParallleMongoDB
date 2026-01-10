# Debug Guide - MongoDBHack Observability

This guide helps you diagnose issues using the comprehensive logging added for hackathon observability.

## Table of Contents
- [Where to View Logs](#where-to-view-logs)
- [Log Format](#log-format)
- [Common Failures & What to Check](#common-failures--what-to-check)
- [Test Failure Scenarios](#test-failure-scenarios)

---

## Where to View Logs

### Backend Logs (FastAPI)

**Location:** Terminal/stdout where `uvicorn` is running

**Start backend with logging:**
```bash
cd apps/api
python -m uvicorn hack_main:app --reload --port 8000
```

**Log types:**
- **Structured JSON logs** (stdout) - All events, requests, external API calls
- **Error logs** (stderr) - Errors with full stacktraces

**Key log tags to watch:**
- `REQUEST_START` / `REQUEST_END` - Every HTTP request with timing
- `MONGO_CONNECT` / `MONGO_QUERY` / `VECTOR_SEARCH` - MongoDB operations
- `FIREWORKS_CHAT` - Fireworks AI API calls
- `VOYAGE_EMBED` - Voyage AI embedding calls
- `SSE_CONNECT` / `SSE_DISCONNECT` / `SSE_EVENT` - Server-Sent Events
- `API_ERROR` / `INTERNAL_ERROR` - Error responses

**Example log entry:**
```json
{"ts": "2025-01-10T20:30:45.123Z", "tag": "REQUEST_END", "request_id": "abc-123", "method": "POST", "path": "/api/demo/ask", "status": 200, "duration_ms": 1250, "client_ip": "127.0.0.1"}
```

**Filter logs by tag:**
```bash
# All requests
python -m uvicorn hack_main:app --reload | grep REQUEST

# Only errors
python -m uvicorn hack_main:app --reload 2>&1 | grep -E "(ERROR|INTERNAL_ERROR)"

# MongoDB operations
python -m uvicorn hack_main:app --reload | grep -E "(MONGO_|VECTOR_SEARCH)"

# SSE activity
python -m uvicorn hack_main:app --reload | grep SSE
```

---

### Web App Logs (React/Vite)

**Location:** Browser DevTools Console

**Open DevTools:**
- Chrome/Edge: `F12` or `Cmd+Option+I` (Mac) / `Ctrl+Shift+I` (Windows)
- Firefox: `F12` or `Cmd+Option+K` (Mac) / `Ctrl+Shift+K` (Windows)

**Log format:**
```
[API] GET /api/chats 200 45ms
[API] Request ID: abc-123
[API] POST /api/demo/ask 500 1200ms [req:def-456]
[API] Error body: {ok: false, error_code: "FIREWORKS_ERROR", message: "...", request_id: "def-456"}
```

**Error notifications:**
- Red banner appears in top-right corner for all API errors
- Shows: HTTP status, error code, message, request ID
- Auto-dismisses after 10 seconds
- Click × to dismiss manually

**Filter console logs:**
```javascript
// In browser console
// Show only API logs
$$('[data-tag="API"]') // or just look for [API] prefix

// Clear console
console.clear()
```

---

### Extension Logs (VS Code)

**Location:** VS Code Output Panel

**View logs:**
1. Open Command Palette: `Cmd+Shift+P` (Mac) / `Ctrl+Shift+P` (Windows)
2. Type: `Output: Show Output`
3. Select channel: **"Parallel Hackathon"** (or the extension's output channel name)

**Alternative:**
- Menu: `View` → `Output` → Select channel from dropdown

**Log format:**
```
[info] [HTTP] POST /api/v1/vscode/chat
[info] [HTTP] POST /api/v1/vscode/chat 200 850ms [req:abc-123]
[error] [HTTP] POST /api/chats/dispatch 500 1200ms [req:def-456]
[error] [HTTP] Error: INTERNAL_ERROR - Database connection failed [req:def-456]
[info] [SSE] Opening connection: http://localhost:8000/api/v1/events?workspace_id=1
[info] [SSE] Connected to workspace:1
[info] [SSE] Event received [id:evt-789]
[error] [SSE] Connection error [lastEventId:evt-789]
```

**Key log prefixes:**
- `[HTTP]` - All HTTP requests to backend
- `[SSE]` - Server-Sent Events connection status
- `[info]` - Normal operations
- `[error]` - Failures with error details
- `[debug]` - Verbose debugging (if enabled)

---

## Log Format

### Structured JSON Logs (Backend)

All backend events are logged as single-line JSON:

```json
{
  "ts": "2025-01-10T20:30:45.123456Z",
  "tag": "FIREWORKS_CHAT",
  "request_id": "abc-123-def",
  "model": "accounts/fireworks/models/llama-v3p1-70b-instruct",
  "purpose": "demo_ask",
  "num_sources": 3
}
```

**Common fields:**
- `ts` - ISO 8601 timestamp
- `tag` - Event type (e.g., REQUEST_START, MONGO_QUERY, FIREWORKS_CHAT)
- `request_id` - Unique request identifier for correlation
- Additional fields vary by event type

**Error logs include:**
- `error_type` - Exception class name
- `error_message` - Error description
- `traceback` - Full Python stacktrace

### Request IDs

Every request gets a unique `request_id` that appears in:
- Backend logs (all events for that request)
- HTTP response header: `X-Request-Id`
- Error response body: `request_id` field
- Web console logs: `[req:abc-123]`
- Extension output: `[req:abc-123]`

**Use request_id to:**
1. Trace a single request across all components
2. Correlate errors with specific API calls
3. Debug timing issues

---

## Common Failures & What to Check

### 1. MongoDB Connection Failed

**Symptoms:**
- Backend startup fails
- Error: `MONGO_CONNECT` with connection timeout
- HTTP 503: "MongoDB unavailable"

**Check:**
```bash
# Backend logs
grep "MONGO_CONNECT" backend.log

# Test connection manually
mongosh "YOUR_MONGODB_URI"
```

**Common causes:**
- Invalid `MONGODB_URI` in `.env`
- IP not whitelisted in MongoDB Atlas
- Network/firewall blocking connection
- MongoDB cluster paused/stopped

**Fix:**
1. Verify `.env` has correct `MONGODB_URI`
2. Check MongoDB Atlas Network Access whitelist
3. Test connection with `mongosh`
4. Restart backend after fixing `.env`

---

### 2. Vector Search Fails

**Symptoms:**
- Error: `VECTOR_SEARCH` with index not found
- HTTP 500: "Vector search failed"
- Empty search results

**Check:**
```bash
# Backend logs
grep "VECTOR_SEARCH" backend.log
```

**Common causes:**
- Vector search index not created in MongoDB
- Wrong index name in `MONGODB_VECTOR_INDEX` env var
- No documents with embeddings in collection

**Fix:**
1. Create vector search index in MongoDB Atlas (see INTEGRATION_PLAN.md)
2. Verify index name matches `MONGODB_VECTOR_INDEX` in `.env`
3. Inject test memory documents: `POST /api/demo/inject_memory`

---

### 3. Fireworks AI API Error

**Symptoms:**
- Error: `FIREWORKS_CHAT` with 401/403/429/500
- HTTP 503: "LLM synthesis failed"
- Chat returns error message

**Check:**
```bash
# Backend logs
grep "FIREWORKS_CHAT" backend.log

# Test API key manually
curl -H "Authorization: Bearer $FIREWORKS_API_KEY" \
  https://api.fireworks.ai/inference/v1/chat/completions
```

**Common causes:**
- Invalid/expired `FIREWORKS_API_KEY`
- Rate limit exceeded
- Model not available
- Network timeout

**Fix:**
1. Verify API key in `.env`
2. Check Fireworks dashboard for quota/limits
3. Try health check: `GET /api/llm_health`

---

### 4. Voyage Embeddings Failed

**Symptoms:**
- Error: `VOYAGE_EMBED` with 401/429/500
- HTTP 503: "Failed to embed question"
- Memory injection fails

**Check:**
```bash
# Backend logs
grep "VOYAGE_EMBED" backend.log
```

**Common causes:**
- Invalid `VOYAGE_API_KEY`
- Rate limit exceeded
- Text too long (>8000 chars)
- Network timeout

**Fix:**
1. Verify API key in `.env`
2. Check text length (automatically truncated at 8000 chars)
3. Retry with backoff

---

### 5. SSE Connection Drops

**Symptoms:**
- Extension logs: `SSE error` or `Reconnecting SSE`
- Web app shows stale data
- Tasks not received in real-time

**Check:**
```bash
# Backend logs
grep "SSE_" backend.log

# Extension output
# View Output panel → "Parallel Hackathon"

# Test SSE manually
curl -N http://localhost:8000/api/v1/events?workspace_id=1
```

**Common causes:**
- Backend restarted/crashed
- Network interruption
- Long-running request timeout
- Browser/extension closed connection

**Fix:**
1. Check backend is running
2. Extension auto-reconnects with exponential backoff
3. Look for `SSE_DISCONNECT` followed by `SSE_CONNECT`
4. Check heartbeat logs (every ~50 seconds)

---

### 6. Request Timeout

**Symptoms:**
- HTTP request hangs
- Error after 30 seconds
- `NETWORK_ERROR` in web console

**Check:**
```bash
# Backend logs - look for REQUEST_START without REQUEST_END
grep "REQUEST_START" backend.log | grep "abc-123"
grep "REQUEST_END" backend.log | grep "abc-123"
```

**Common causes:**
- Slow MongoDB query
- Fireworks API slow response
- Vector search on large collection
- Network latency

**Fix:**
1. Check `duration_ms` in logs to identify slow operations
2. Add indexes to MongoDB collections
3. Reduce `top_k` for vector search
4. Increase timeout in client code if needed

---

### 7. CORS / CSRF Errors

**Symptoms:**
- Browser console: "CORS policy blocked"
- HTTP OPTIONS requests fail
- Cookies not sent

**Check:**
```bash
# Backend logs
grep "OPTIONS" backend.log

# Browser DevTools → Network tab
# Look for failed OPTIONS requests
```

**Common causes:**
- Frontend origin not allowed
- Missing CORS middleware
- Credentials mode mismatch

**Fix:**
1. Backend runs on `http://localhost:8000`
2. Frontend runs on `http://localhost:5173`
3. Vite proxy handles CORS for `/api/*`
4. Direct API calls need CORS headers (already configured)

---

### 8. Extension Not Receiving Tasks

**Symptoms:**
- Task dispatched from web but not in extension
- Extension shows no notifications
- SSE connected but no events

**Check:**
```bash
# Backend logs
grep "SSE_EVENT" backend.log
grep "workspace_id.*1" backend.log

# Extension output
# Look for [SSE] Event received
```

**Common causes:**
- Wrong `workspace_id` (must be "1")
- Event not emitted after task creation
- SSE connection dropped before event sent
- Extension not listening

**Fix:**
1. Verify workspace_id is "1" in both web and extension
2. Check backend emits event: `_emit_event("task", task_id, ...)`
3. Restart SSE connection in extension
4. Check MongoDB `events` collection has the event

---

## Test Failure Scenarios

Use these curl commands to intentionally trigger failures and verify error handling:

### 1. Invalid MongoDB URI (Backend Startup)

**Setup:**
```bash
# Edit apps/api/.env
MONGODB_URI=mongodb+srv://invalid:invalid@invalid.mongodb.net/
```

**Start backend:**
```bash
cd apps/api
python -m uvicorn hack_main:app --reload
```

**Expected logs:**
```json
{"tag": "MONGO_CONNECT", ...}
{"tag": "MONGO_CONNECT", "error_type": "ServerSelectionTimeoutError", "error_message": "...", "traceback": "..."}
```

**Expected result:** Backend crashes on startup with connection error

---

### 2. Missing Fireworks API Key

**Setup:**
```bash
# Edit apps/api/.env
FIREWORKS_API_KEY=
```

**Test:**
```bash
curl http://localhost:8000/api/llm_health
```

**Expected response:**
```json
{
  "detail": "LLM health check failed: ..."
}
```

**Expected logs:**
```json
{"tag": "FIREWORKS_CHAT", "model": "...", "purpose": "health_check"}
{"tag": "FIREWORKS_CHAT", "error_type": "AuthenticationError", ...}
```

---

### 3. Invalid Voyage API Key

**Setup:**
```bash
# Edit apps/api/.env
VOYAGE_API_KEY=invalid_key_here
```

**Test:**
```bash
curl -X POST http://localhost:8000/api/demo/inject_memory \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"test","title":"Test","text":"This is a test"}'
```

**Expected response:**
```json
{
  "ok": false,
  "error_code": "INTERNAL_ERROR",
  "message": "An unexpected error occurred: ...",
  "request_id": "abc-123-def"
}
```

**Expected logs:**
```json
{"tag": "VOYAGE_EMBED", "model": "voyage-3", "num_texts": 1}
{"tag": "VOYAGE_EMBED", "error_type": "HTTPStatusError", "error_message": "401 Unauthorized"}
```

---

### 4. Vector Search Index Missing

**Setup:**
```bash
# Don't create the vector search index in MongoDB
# Or use wrong index name in .env
MONGODB_VECTOR_INDEX=nonexistent_index
```

**Test:**
```bash
curl -X POST http://localhost:8000/api/demo/ask \
  -H "Content-Type: application/json" \
  -d '{"target_agent_id":"test","question":"What is test?"}'
```

**Expected response:**
```json
{
  "detail": "Vector search failed: ..."
}
```

**Expected logs:**
```json
{"tag": "VECTOR_SEARCH", "agent_id": "test", "top_k": 5, "index": "nonexistent_index"}
{"tag": "VECTOR_SEARCH", "error_type": "OperationFailure", ...}
```

---

### 5. Malformed Request Body

**Test:**
```bash
curl -X POST http://localhost:8000/api/demo/inject_memory \
  -H "Content-Type: application/json" \
  -d '{"invalid": "data"}'
```

**Expected response:**
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "agent_id"],
      "msg": "Field required"
    },
    ...
  ]
}
```

**Expected logs:**
```json
{"tag": "REQUEST_START", "request_id": "...", "method": "POST", "path": "/api/demo/inject_memory"}
{"tag": "REQUEST_END", "request_id": "...", "status": 422, "duration_ms": 5}
```

---

### 6. Network Timeout (Long Request)

**Test:**
```bash
# This will timeout if MongoDB is slow or unreachable
curl --max-time 5 -X POST http://localhost:8000/api/demo/ask \
  -H "Content-Type: application/json" \
  -d '{"target_agent_id":"test","question":"Test question"}'
```

**Expected behavior:**
- Curl times out after 5 seconds
- Backend logs show REQUEST_START but delayed REQUEST_END
- If backend operation takes >30s, backend also times out

**Expected logs:**
```json
{"tag": "REQUEST_START", ...}
{"tag": "VOYAGE_EMBED", ...}
// Long delay
{"tag": "REQUEST_END", "duration_ms": 30000}
```

---

### 7. SSE Connection Error

**Test:**
```bash
# Connect with invalid workspace_id
curl -N 'http://localhost:8000/api/v1/events?workspace_id=invalid'
```

**Expected behavior:**
- SSE connects but receives no events (wrong workspace)
- Only heartbeats every 5 seconds

**Expected logs:**
```json
{"tag": "SSE_CONNECT", "workspace_id": "invalid", "last_event_id": null}
{"tag": "SSE_HEARTBEAT", "workspace_id": "invalid", "count": 10}
```

---

### 8. Missing Environment Variables

**Setup:**
```bash
# Edit apps/api/.env - remove required variables
# MONGODB_URI=
# FIREWORKS_API_KEY=
```

**Start backend:**
```bash
cd apps/api
python -m uvicorn hack_main:app --reload
```

**Expected result:**
```
RuntimeError: Missing required env vars for hackathon runtime: FIREWORKS_API_KEY, MONGODB_URI
```

**Expected logs:** None (fails before app starts)

---

## Quick Debug Commands

### Check if all services are running

```bash
# Backend health
curl http://localhost:8000/api/health

# MongoDB health
curl http://localhost:8000/api/demo/health

# LLM health
curl http://localhost:8000/api/llm_health

# Frontend (browser)
open http://localhost:5173
```

### Monitor all backend activity

```bash
# Follow all logs
cd apps/api
python -m uvicorn hack_main:app --reload 2>&1 | tee backend.log

# In another terminal - filter by tag
tail -f backend.log | grep -E "(REQUEST|ERROR)"
```

### Test full demo loop

```bash
# 1. Create chat
curl -X POST http://localhost:8000/api/chats \
  -H "Content-Type: application/json" \
  -d '{"name":"Debug Test"}'

# 2. Dispatch task (use chat_id from step 1)
curl -X POST http://localhost:8000/api/chats/CHAT_ID/dispatch \
  -H "Content-Type: application/json" \
  -d '{"mode":"vscode","content":"Test task"}'

# 3. Check task status (use task_id from step 2)
curl http://localhost:8000/api/v1/extension/tasks/TASK_ID

# 4. Monitor SSE (in separate terminal)
curl -N 'http://localhost:8000/api/v1/events?workspace_id=1'
```

### Extract request trace

```bash
# Get all logs for specific request_id
grep "abc-123-def" backend.log | jq .

# Count requests per endpoint
grep REQUEST_END backend.log | jq -r .path | sort | uniq -c

# Average response time per endpoint
grep REQUEST_END backend.log | jq -r '"\(.path) \(.duration_ms)"' | \
  awk '{sum[$1]+=$2; count[$1]++} END {for (path in sum) print path, sum[path]/count[path]}'
```

---

## Support

### Still stuck?

1. **Collect logs:**
   - Backend: Save full terminal output
   - Web: Export browser console logs (right-click → Save as...)
   - Extension: Copy from Output panel

2. **Include:**
   - Request ID(s) from error
   - Exact curl command or user action
   - Relevant log excerpts with timestamps
   - Environment (.env values without secrets)

3. **Check:**
   - INTEGRATION_SUMMARY.md - Setup checklist
   - SMOKE_TEST.md - Test suite
   - MongoDB Compass - Verify data
   - Browser Network tab - HTTP traffic

---

**Last updated:** 2026-01-10
