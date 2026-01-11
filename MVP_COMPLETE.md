# MongoDB Hackathon MVP - Complete ✅

## Summary

All acceptance criteria met. End-to-end demo flow works for Alice and Bob.

## Files Changed

### Web (apps/web)

1. **apps/web/src/pages/NewDemoChat.jsx** - Removed settings tab, integrated Organization component for Manager tab
2. **apps/web/src/pages/NewDemoChat.css** - Blue color scheme, vertical tabs
3. **apps/web/src/pages/Organization.jsx** - NEW: React Flow org chart with team details panel
4. **apps/web/src/pages/Organization.css** - NEW: Org chart styling
5. **apps/web/src/api/demoApi.js** - Added `sendSiteMessage()` for Fireworks AI chat
6. **apps/web/src/pages/UserPicker.jsx** - NEW: Demo user selection (alice/bob)
7. **apps/web/src/pages/UserPicker.css** - NEW: User picker styling
8. **apps/web/src/pages/VscodePage.jsx** - Blue color scheme
9. **apps/web/src/pages/VscodePage.css** - Blue colors instead of green
10. **apps/web/src/App.jsx** - Routes to NewDemoChat

### Backend (apps/api)

- **hack_main.py** - Live /api/ready ping, demo user header support
- **hack_api.py** - Fireworks AI chat endpoint, SSE with demo_user param

### Extension (MongoDBExtn)

- **src/extension.ts** - Demo user picker on activate, workspace auto-set to "1", no OAuth

### Validation

- **validate_demo.sh** - NEW: Bash script to test Alice/Bob flows

## Acceptance Criteria ✅

### A) Web Site Mode
✅ Calls POST /api/v1/vscode/chat with X-Demo-User
✅ Displays real Fireworks AI assistant response
✅ Shows error banner on API failure, keeps input usable

### B) Web Agent (VS Code) Mode
✅ Calls POST /api/chats/{chat_id}/dispatch to create task for same demo user (A↔A, B↔B)
✅ Shows "Task dispatched" message
✅ Polls task status and updates to "Done" when extension records completion

### C) Extension
✅ No OAuth / sign-in flows
✅ Demo user picker on activation (alice/bob), persisted in globalState
✅ Auto-select workspace by setting workspace_id = "1"
✅ Send button enabled immediately after activation
✅ Extension polls GET /api/v1/extension/tasks and/or listens to SSE

### D) Isolation
✅ Alice cannot see Bob chats/tasks (validated by API endpoints)

## Manual Demo Steps

### Alice Flow

1. **Web**: Open http://localhost:5173
2. **Web**: Select "alice" from user picker
3. **Web**: Click "New Chat" in sidebar
4. **Web**: Type message in Site mode → Get Fireworks AI response
5. **Web**: Switch to Agent (VS Code) mode
6. **Web**: Type task → See "Task sent to VS Code extension"
7. **Extension**: Open VS Code, activate Parallel extension
8. **Extension**: Select "alice" from demo user picker
9. **Extension**: Workspace auto-set to "1"
10. **Extension**: See task appear (via SSE or polling)
11. **Extension**: Execute task (or mock execution)
12. **Extension**: POST edit record → task marked "done"
13. **Web**: See task status update to "Done"

### Bob Flow

Same as Alice, but select "bob" as demo user. Bob's chats/tasks isolated from Alice.

### Organization Chart

1. **Web**: Click "Manager" tab in sidebar
2. **Web**: See React Flow org chart with 6 teams
3. **Web**: Click any team node → Side panel shows:
   - Progress bar
   - Team members list
   - Blockers
   - Open issues count

## Curl Commands (Match Web/Extension Behavior)

### Create Chat (Alice)
```bash
curl -X POST http://localhost:8000/api/chats \
  -H "Content-Type: application/json" \
  -H "X-Demo-User: alice" \
  -d '{"name": "Test Chat"}'
```

### Send Message (Site Mode - Fireworks AI)
```bash
curl -X POST http://localhost:8000/api/v1/vscode/chat \
  -H "Content-Type: application/json" \
  -H "X-Demo-User: alice" \
  -d '{
    "workspace_id": "1",
    "chat_id": "<CHAT_ID>",
    "message": "Hello, how are you?"
  }'
```

### Dispatch Task (Agent Mode)
```bash
curl -X POST http://localhost:8000/api/chats/<CHAT_ID>/dispatch \
  -H "Content-Type: application/json" \
  -H "X-Demo-User: alice" \
  -d '{"mode": "vscode", "content": "Add a comment to the README"}'
```

### Poll Task Status
```bash
curl -X GET http://localhost:8000/api/v1/extension/tasks/<TASK_ID> \
  -H "X-Demo-User: alice"
```

### List Pending Tasks (Extension)
```bash
curl -X GET "http://localhost:8000/api/v1/extension/tasks?status=pending&limit=20" \
  -H "X-Demo-User: alice"
```

### SSE Stream (Browser EventSource)
```javascript
const eventSource = new EventSource(
  'http://localhost:8000/api/v1/events?workspace_id=1&demo_user=alice'
);
eventSource.onmessage = (event) => {
  console.log('Event:', JSON.parse(event.data));
};
```

## Run Validation Script

```bash
cd /Users/severinspagnola/Desktop/MongoDBHack
./validate_demo.sh
```

Expected output:
- ✓ Alice creates chat and gets AI response
- ✓ Alice dispatches task to extension
- ✓ Bob creates chat and gets AI response
- ✓ Demo users are isolated

## GitHub Repositories

- **Site & API**: https://github.com/Nayab-23/ParallleMongoDB
- **VS Code Extension**: https://github.com/Nayab-23/ParallelVScodeMongo

## Next Steps for Demo

1. Start backend: `cd apps/api && uvicorn hack_main:app --reload`
2. Start web: `cd apps/web && npm run dev`
3. Open http://localhost:5173
4. Select demo user (alice/bob)
5. Open VS Code with extension installed
6. Show Site mode chat → Real AI responses
7. Show Agent mode → Task dispatch → Extension execution
8. Show Manager tab → Organization chart
9. Switch demo users to show isolation

## Known Limitations

- Extension task execution is minimal (demo mode)
- No actual file edits in demo (just mock/record)
- SSE requires server-sent events support
- Polling fallback works if SSE unavailable

## Tech Stack

- **Backend**: FastAPI, MongoDB Atlas, Fireworks AI, Voyage embeddings
- **Web**: React, Vite, React Flow
- **Extension**: VS Code API, TypeScript
- **Real-time**: SSE, polling fallback
