# Observability Verification Checklist

Run these tests to verify observability is working correctly before the demo.

## ✅ Verification Tests (10 minutes)

### 1. Request ID Propagation

**Test:**
```bash
curl -i http://localhost:8000/api/health
```

**Expected:**
- Response header: `X-Request-Id: <uuid>`
- Backend logs show same request_id in REQUEST_START and REQUEST_END

**Verify:**
```bash
# Watch backend logs and note the request_id
python -m uvicorn hack_main:app --reload 2>&1 | grep REQUEST
```

---

### 2. Validation Errors Still Work (422)

**Test:**
```bash
curl -X POST http://localhost:8000/api/chats \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Expected:**
- HTTP 422 (NOT 500)
- JSON response with FastAPI validation details:
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "name"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

**NOT expected:**
```json
{
  "ok": false,
  "error_code": "INTERNAL_ERROR",
  ...
}
```

---

### 3. SSE Logging Works

**Test:**
```bash
# Terminal 1: Watch backend logs
cd apps/api
python -m uvicorn hack_main:app --reload 2>&1 | grep SSE

# Terminal 2: Connect SSE client
curl -N 'http://localhost:8000/api/v1/events?workspace_id=1'
```

**Expected backend logs:**
```json
{"tag": "SSE_CONNECT", "workspace_id": "1", "last_event_id": null, ...}
{"tag": "SSE_HEARTBEAT", "workspace_id": "1", "count": 10, ...}
# (after ~50 seconds of no events)
```

**When you Ctrl+C the curl:**
```json
{"tag": "SSE_DISCONNECT", "workspace_id": "1", ...}
```

---

### 4. Web App Uses Logged Wrapper

**Test:**
```bash
# Start backend and frontend
cd apps/api && python -m uvicorn hack_main:app --reload &
cd apps/web && npm run dev &

# Open browser to http://localhost:5173
# Open DevTools Console (F12)
# Navigate to any page that makes API calls
```

**Expected in browser console:**
```
[API] GET /api/me - Starting...
[API] GET /api/me 200 45ms
[API] Request ID: <uuid>
```

**Verify coverage:**
```bash
# Check that demoApi.js imports loggedFetch
grep "loggedFetch" apps/web/src/api/demoApi.js
# Should see: import { loggedFetch } from "../lib/apiLogger";
```

---

### 5. Error Banner Appears

**Test:**
```bash
# Trigger an API error (invalid endpoint)
curl http://localhost:5173  # Open browser
# In browser console:
fetch('/api/invalid-endpoint').catch(() => {})
```

**Expected:**
- Red error banner appears in top-right
- Shows HTTP status, error code, message
- Shows request_id if available
- Auto-dismisses after 10 seconds

---

### 6. Extension Logs HTTP Calls

**Setup:**
1. Open VS Code with the extension
2. View → Output
3. Select "Parallel Hackathon" (or your channel name)

**Test:**
Make any API call from the extension (connect to workspace, send chat, etc.)

**Expected in Output panel:**
```
[info] [HTTP] POST /api/v1/vscode/chat
[info] [HTTP] POST /api/v1/vscode/chat 200 850ms [req:abc-123]
```

**On error:**
```
[error] [HTTP] POST /api/chats/dispatch 500 1200ms [req:def-456]
[error] [HTTP] Error: INTERNAL_ERROR - Database connection failed [req:def-456]
```

---

### 7. Request Correlation Works

**Test:**
```bash
# Make a request that will fail (no MongoDB connection)
# Edit apps/api/.env temporarily:
MONGODB_URI=mongodb+srv://invalid:invalid@invalid.mongodb.net/

# Restart backend and make request:
curl -X POST http://localhost:8000/api/demo/inject_memory \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"test","title":"Test","text":"Test"}'
```

**Expected response:**
```json
{
  "ok": false,
  "error_code": "INTERNAL_ERROR",
  "message": "...",
  "request_id": "abc-123-def-456"
}
```

**Verify correlation:**
```bash
# Search backend logs for the request_id
grep "abc-123-def-456" backend.log | jq .
```

**Expected output:**
```json
{"tag":"REQUEST_START","request_id":"abc-123-def-456",...}
{"tag":"MONGO_CONNECT","request_id":"abc-123-def-456",...}
{"tag":"MONGO_CONNECT","error_type":"ServerSelectionTimeoutError",...}
{"tag":"INTERNAL_ERROR","request_id":"abc-123-def-456",...}
{"tag":"REQUEST_END","request_id":"abc-123-def-456","status":500,...}
```

---

### 8. External API Logging

**Test:**
```bash
# Make a request that uses Voyage + Fireworks
curl -X POST http://localhost:8000/api/demo/ask \
  -H "Content-Type: application/json" \
  -d '{"target_agent_id":"test","question":"What is test?"}'
```

**Expected backend logs:**
```json
{"tag":"REQUEST_START",...}
{"tag":"VOYAGE_EMBED","model":"voyage-3","num_texts":1,...}
{"tag":"VOYAGE_EMBED_SUCCESS","num_embeddings":1,...}
{"tag":"VECTOR_SEARCH","agent_id":"test","top_k":5,...}
{"tag":"VECTOR_SEARCH_SUCCESS","num_results":5,...}
{"tag":"FIREWORKS_CHAT","model":"llama-v3p1-70b","purpose":"demo_ask",...}
{"tag":"FIREWORKS_CHAT_SUCCESS","answer_length":123,...}
{"tag":"REQUEST_END","status":200,"duration_ms":1250,...}
```

---

## 🔍 Quick Smoke Tests

### All services healthy:
```bash
curl http://localhost:8000/api/health
# → {"ok": true}

curl http://localhost:8000/api/demo/health
# → {"ok": true, "mongodb": "ok"}

curl http://localhost:8000/api/llm_health
# → {"provider": "fireworks", "model": "...", "ok": true, "sample": "ok"}
```

### Web app loads:
```bash
open http://localhost:5173
# → Landing page loads without errors
# → Check browser console for [API] logs
```

### Extension connects:
- Open VS Code
- Extension status shows "Connected"
- Output panel shows [SSE] Connected message

---

## ❌ What Should NOT Happen

### 1. Validation errors should NOT be 500s:
```bash
# This should return 422, NOT 500:
curl -X POST http://localhost:8000/api/chats \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 2. No request_id in logs:
```bash
# Every log entry should have request_id (except heartbeats)
python -m uvicorn hack_main:app --reload 2>&1 | grep -v request_id | grep REQUEST
# Should be empty (all REQUEST logs have request_id)
```

### 3. Direct fetch calls in web:
```bash
# This should return only demoApi.js (already uses wrapper):
grep -r "fetch(" apps/web/src/api/*.js | grep -v loggedFetch
```

---

## 🎯 Success Criteria

All of these should be true:

- ✅ Request IDs appear in backend logs
- ✅ Request IDs returned in response headers
- ✅ Request IDs shown in error responses
- ✅ 422 validation errors work correctly (not turned into 500s)
- ✅ SSE connects/disconnects logged
- ✅ External API calls logged (Mongo, Fireworks, Voyage)
- ✅ Web console shows [API] logs
- ✅ Error banner appears on API failures
- ✅ Extension Output shows [HTTP] logs
- ✅ Request correlation works across all components

---

## 🐛 If Something Fails

### Request IDs not appearing:
- Check middleware is registered: `app.add_middleware(RequestLoggerMiddleware)` in hack_main.py
- Restart backend

### 422s turning into 500s:
- This should NOT happen - middleware uses `call_next()` which preserves FastAPI exception handling
- If it does, the middleware is catching too broadly
- Check for any changes to the exception handler

### SSE logs missing:
- Check imports in hack_api.py: `from logutil import log_event, log_error`
- Check logs are inside the event_generator function

### Web logs missing:
- Check demoApi.js imports: `import { loggedFetch } from "../lib/apiLogger"`
- Check ErrorBanner is rendered in App.jsx

### Extension logs missing:
- Extension already has logging infrastructure
- Check Output panel is set to correct channel name

---

## 📊 Performance Check

After verification, check that logging doesn't slow things down:

```bash
# Without logging overhead, baseline:
time curl http://localhost:8000/api/health

# Compare with logs:
python -m uvicorn hack_main:app --reload 2>&1 > /dev/null &
time curl http://localhost:8000/api/health
```

**Expected:** Logging adds < 5ms overhead per request

---

**Status:** Run this checklist before demo day to ensure observability is working!
