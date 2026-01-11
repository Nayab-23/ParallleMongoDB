# Admin VSCode & Collaboration Debug API Documentation

**Date**: 2026-01-02
**Status**: ✅ **IMPLEMENTED**

---

## Summary

Backend API endpoints for VSCode integration monitoring and collaboration/notification tracking. These endpoints power the VSCode Debug and Collaboration Debug dashboard tabs in the admin panel.

---

## 🎯 New Endpoints

### 1. GET /api/admin/vscode-debug/{user_email}

**Purpose**: Get VSCode activity debug information for a specific user

**Authentication**: Required (platform admin only)

**Path Parameters**:
- `user_email` (string): Email address of the user to debug

**Query Parameters**:
- `start_date` (optional, string): Start date in ISO format (e.g., "2026-01-01T00:00:00Z")
- `end_date` (optional, string): End date in ISO format (defaults to now)
- Defaults to last 7 days if not specified

**Response**:
```json
{
  "user": "user@example.com",
  "date_range": {
    "start": "2025-12-26T00:00:00Z",
    "end": "2026-01-02T00:00:00Z"
  },
  "vscode_linked": true,
  "last_activity": "2026-01-02T10:30:00Z",

  "activity_summary": {
    "total_actions": 245,
    "total_edits": 120,
    "total_commits": 15,
    "total_debug_sessions": 8,
    "files_edited": ["src/app.py", "src/utils.py", "README.md"],
    "files_count": 3,
    "projects": ["parallel-backend"],
    "action_types": {
      "code_edit": 100,
      "file_save": 20,
      "git_commit": 15,
      "debug_session": 8
    }
  },

  "recent_activity": [
    {
      "id": "action-123",
      "timestamp": "2026-01-02T10:30:00Z",
      "event_type": "code_edit",
      "action_data": {
        "file_path": "src/app.py",
        "lines_changed": 5
      },
      "session_id": "session-abc"
    }
  ],

  "context_requests": [
    {
      "timestamp": "2026-01-02T10:00:00Z",
      "type": "chat",
      "content": "How do I fix this code...",
      "role": "user"
    }
  ],

  "conflicts_detected": [
    {
      "id": "notif-456",
      "timestamp": "2026-01-01T15:00:00Z",
      "conflict_type": "file",
      "title": "File Conflict with Alice",
      "message": "Alice is also editing src/app.py",
      "notification_sent": true,
      "read": false,
      "data": {
        "file": "src/app.py",
        "other_user_id": "user-789"
      }
    }
  ],

  "notifications": {
    "smart_team_updates": 12,
    "conflict_notifications": 3,
    "last_conflict_at": "2026-01-01T15:00:00Z"
  }
}
```

**Example Request**:
```bash
curl "http://localhost:8000/api/admin/vscode-debug/user@example.com?start_date=2025-12-26T00:00:00Z" \
  -H "Cookie: access_token=ADMIN_TOKEN"
```

**Logs Generated**:
```
[VSCode Debug] 🔍 GET /vscode-debug/user@example.com called by admin@example.com
[VSCode Debug] ✅ Admin access verified for admin@example.com
[VSCode Debug] ✅ Found user: user@example.com (ID: abc-123)
[VSCode Debug] Date range: 2025-12-26 to 2026-01-02 (7 days)
[VSCode Debug] Found 245 VSCode actions
[VSCode Debug] Found 15 VSCode-related chat messages
[VSCode Debug] Found 3 conflict notifications
[VSCode Debug] Statistics: 245 actions, 3 files, 1 projects
[VSCode Debug] ✅ Returning VSCode debug data for user@example.com (vscode_linked: True, actions: 245)
```

---

### 2. GET /api/admin/collaboration-debug

**Purpose**: Get collaboration debug info for multiple users (1-4 users)

**Authentication**: Required (platform admin only)

**Query Parameters**:
- `users` (required, list of strings): User emails to analyze (1-4 users)
  - Example: `?users=user1@example.com&users=user2@example.com`
- `days` (optional, int): Number of days to look back (default: 7)

**Response**:
```json
{
  "users": ["user1@example.com", "user2@example.com"],
  "date_range": {
    "start": "2025-12-26T00:00:00Z",
    "end": "2026-01-02T00:00:00Z",
    "days": 7
  },

  "chat_interactions": [
    {
      "chat_id": "chat-123",
      "participants": ["user1@example.com", "user2@example.com"],
      "message_count": 25,
      "last_activity": "2026-01-02T10:00:00Z",
      "first_activity": "2026-01-01T09:00:00Z"
    }
  ],

  "notifications": [
    {
      "id": "notif-456",
      "timestamp": "2026-01-01T15:00:00Z",
      "from_user": "user1@example.com",
      "to_user": "user2@example.com",
      "type": "smart_team_update",
      "severity": "normal",
      "source_type": "conflict_file",
      "title": "File Conflict",
      "message": "User1 is editing the same file",
      "read": false
    }
  ],

  "conflicts_detected": [
    {
      "timestamp": "2026-01-01T15:00:00Z",
      "type": "file",
      "users": ["user1@example.com", "user2@example.com"],
      "notification_sent": true,
      "title": "File Conflict",
      "message": "Both editing src/app.py",
      "file": "src/app.py"
    }
  ],

  "collaboration_opportunities": [
    {
      "timestamp": "2026-01-02T12:00:00Z",
      "type": "common_files",
      "similarity_score": 0.67,
      "user1": "user1@example.com",
      "user2": "user2@example.com",
      "user1_activity": "Working on 3 files",
      "user2_activity": "Working on 5 files",
      "suggestion": "Both working on: src/app.py, src/utils.py",
      "common_files": ["src/app.py", "src/utils.py"]
    }
  ],

  "interaction_graph": {
    "nodes": [
      {
        "id": "user1@example.com",
        "label": "User One",
        "activity_count": 15
      },
      {
        "id": "user2@example.com",
        "label": "User Two",
        "activity_count": 20
      }
    ],
    "edges": [
      {
        "source": "user1@example.com",
        "target": "user2@example.com",
        "weight": 28,
        "types": ["chat", "notification", "conflict"],
        "chat_count": 25,
        "notification_count": 2,
        "conflict_count": 1
      }
    ]
  },

  "summary": {
    "total_chats": 1,
    "total_messages": 25,
    "total_notifications": 2,
    "total_conflicts": 1,
    "total_opportunities": 1
  }
}
```

**Example Request**:
```bash
curl "http://localhost:8000/api/admin/collaboration-debug?users=user1@example.com&users=user2@example.com&days=7" \
  -H "Cookie: access_token=ADMIN_TOKEN"
```

**Logs Generated**:
```
[Collab Debug] 🔍 GET /collaboration-debug called by admin@example.com
[Collab Debug] Analyzing 2 users: ['user1@example.com', 'user2@example.com']
[Collab Debug] ✅ Admin access verified for admin@example.com
[Collab Debug] ✅ Found all 2 users
[Collab Debug] Date range: 2025-12-26 to 2026-01-02 (7 days)
[Collab Debug] Found 5 total chats in date range
[Collab Debug] Found 1 chat interactions with 2+ selected users
[Collab Debug] Found 2 notifications
[Collab Debug] Found 1 conflict notifications
[Collab Debug] Found 50 user actions
[Collab Debug] Collaboration opportunity: user1@example.com & user2@example.com - 2 common files
[Collab Debug] Found 1 collaboration opportunities
[Collab Debug] Building interaction graph for 2 users
[Collab Debug] Graph built: 2 nodes, 1 edges
[Collab Debug] ✅ Returning collaboration debug data: {'total_chats': 1, 'total_messages': 25, ...}
```

---

## 🔐 Authentication & Authorization

All admin endpoints require:
1. **Authentication**: Valid JWT token in `access_token` cookie
2. **Authorization**: User must have `is_platform_admin = true`

**Error Responses**:

**401 Unauthorized**:
```json
{"detail": "Not authenticated"}
```

**403 Forbidden**:
```json
{"detail": "Admin access required"}
```

**404 Not Found** (user doesn't exist):
```json
{"detail": "User user@example.com not found"}
```

**400 Bad Request** (invalid parameters):
```json
{"detail": "Must select 1-4 users"}
```

---

## 📊 Data Sources

### VSCode Debug Endpoint

**Data Collected From**:
1. `UserAction` table (tool='vscode')
   - Code edits, file saves, git commits, debug sessions
   - Action types and action_data (files, projects)

2. `Message` table
   - Chat messages containing VSCode-related keywords
   - Context requests about code/files

3. `Notification` table
   - Conflict notifications (file and semantic)
   - Source type: 'conflict_file', 'conflict_semantic'

**Metrics Calculated**:
- Total actions by type
- Files edited (unique file paths)
- Projects (from action_data)
- Recent activity timeline
- Conflict detection history

---

### Collaboration Debug Endpoint

**Data Collected From**:
1. `ChatInstance` and `Message` tables
   - Multi-user chat interactions
   - Message counts per chat

2. `Notification` table
   - Notifications between selected users
   - Conflict notifications

3. `UserAction` table (is_status_change=True)
   - Recent activity for similarity detection
   - Common files/projects analysis

**Metrics Calculated**:
- Chat interactions (2+ selected users)
- Notification flow (from_user → to_user)
- File and semantic conflicts
- Collaboration opportunities (common files)
- Interaction graph (nodes and edges)

---

## 🎨 Frontend Integration

### VSCode Debug Dashboard

**Initial Load**:
1. Select user from dropdown (calls `GET /api/admin/users`)
2. Optionally set date range
3. Call `GET /api/admin/vscode-debug/{email}?start_date=...&end_date=...`
4. Display:
   - VSCode link status indicator
   - Activity summary cards (edits, commits, debug sessions)
   - Files edited list
   - Recent activity timeline
   - Context requests list
   - Conflicts detected

**Auto-Refresh**:
- Poll endpoint every 30-60 seconds for real-time updates
- Update activity counts and recent activity

---

### Collaboration Debug Dashboard

**Initial Load**:
1. Select 1-4 users from multi-select dropdown
2. Set number of days (default 7)
3. Call `GET /api/admin/collaboration-debug?users=...&users=...&days=7`
4. Display:
   - Chat interactions table
   - Notifications timeline
   - Conflicts detected
   - Collaboration opportunities
   - Interaction graph (D3.js force layout)

**Graph Visualization**:
- Nodes: Users (sized by activity count)
- Edges: Interactions (colored by type: chat/notification/conflict)
- Edge thickness: Weight (total interactions)

---

## 🧪 Testing

### Test 1: VSCode Debug - User with Activity ✅

```bash
curl "http://localhost:8000/api/admin/vscode-debug/active_user@example.com" \
  -H "Cookie: access_token=ADMIN_TOKEN" | jq
```

**Expected**:
- `vscode_linked: true`
- `total_actions > 0`
- `files_edited` array populated
- `recent_activity` array populated

---

### Test 2: VSCode Debug - User without VSCode ✅

```bash
curl "http://localhost:8000/api/admin/vscode-debug/inactive_user@example.com" \
  -H "Cookie: access_token=ADMIN_TOKEN" | jq
```

**Expected**:
- `vscode_linked: false`
- `total_actions: 0`
- `files_edited: []`
- `last_activity: null`

---

### Test 3: Collaboration Debug - 2 Users ✅

```bash
curl "http://localhost:8000/api/admin/collaboration-debug?users=user1@example.com&users=user2@example.com&days=7" \
  -H "Cookie: access_token=ADMIN_TOKEN" | jq
```

**Expected**:
- `chat_interactions` array with shared chats
- `notifications` showing interactions
- `interaction_graph` with 2 nodes and edges
- `collaboration_opportunities` if common files exist

---

### Test 4: Collaboration Debug - Too Many Users ❌

```bash
curl "http://localhost:8000/api/admin/collaboration-debug?users=user1@example.com&users=user2@example.com&users=user3@example.com&users=user4@example.com&users=user5@example.com" \
  -H "Cookie: access_token=ADMIN_TOKEN"
```

**Expected**:
- 400 Bad Request
- `{"detail": "Must select 1-4 users"}`

---

### Test 5: Non-Admin Access ❌

```bash
curl "http://localhost:8000/api/admin/vscode-debug/user@example.com" \
  -H "Cookie: access_token=NON_ADMIN_TOKEN"
```

**Expected**:
- 403 Forbidden
- `{"detail": "Admin access required"}`

---

## 📁 Files Created/Modified

### New Files:
1. ✅ [app/api/admin/vscode.py](app/api/admin/vscode.py:1) - VSCode debug endpoint (206 lines)
2. ✅ [app/api/admin/collaboration.py](app/api/admin/collaboration.py:1) - Collaboration debug endpoint (408 lines)
3. ✅ [ADMIN_VSCODE_COLLAB_API.md](ADMIN_VSCODE_COLLAB_API.md:1) - This documentation

### Modified Files:
1. ✅ [app/api/admin/__init__.py](app/api/admin/__init__.py:79) - Registered VSCode and Collaboration routers
2. ✅ [main.py](main.py:8999) - Injected get_current_user into new modules

---

## 🚀 Deployment Status

**Current State**: ✅ **READY FOR TESTING**

**Implementation Checklist**:
- [x] Create VSCode debug endpoint
- [x] Create Collaboration debug endpoint
- [x] Add comprehensive logging to both endpoints
- [x] Register routers in admin __init__.py
- [x] Inject get_current_user dependencies
- [x] Syntax validation (no errors)
- [x] Documentation complete
- [ ] **NEXT**: Manual testing with production data
- [ ] **NEXT**: Frontend integration

**Deployment Notes**:
- No database migrations required (uses existing tables)
- No environment variables needed
- Endpoints immediately available after restart
- Comprehensive logging for debugging

---

## 🎯 Endpoint Summary

| Endpoint | Method | Path | Purpose | Status |
|----------|--------|------|---------|--------|
| VSCode Debug | GET | `/api/admin/vscode-debug/{email}` | VSCode activity monitoring | ✅ Ready |
| Collaboration Debug | GET | `/api/admin/collaboration-debug` | Multi-user collaboration analysis | ✅ Ready |

---

## 📈 Use Cases

### VSCode Debug Dashboard

**Use Case 1: Check if User has VSCode Linked**
- Admin views user's VSCode debug page
- Sees `vscode_linked: false`
- Action: Remind user to install VSCode extension

**Use Case 2: Debug Conflict Notifications**
- User reports not receiving conflict alerts
- Admin checks VSCode debug page
- Sees `conflicts_detected: 0` despite file edits
- Action: Check conflict detector worker logs

**Use Case 3: Monitor User Activity**
- Admin checks daily VSCode usage
- Views activity summary: 50 edits, 5 commits
- Sees files edited: API endpoints and tests
- Action: Understand user's work patterns

---

### Collaboration Debug Dashboard

**Use Case 1: Find Collaboration Opportunities**
- Admin selects 3 developers
- Sees `collaboration_opportunities` with 2 pairs having 60% similarity
- Both working on authentication module
- Action: Suggest pairing session

**Use Case 2: Debug Missing Notifications**
- User1 reports not seeing User2's updates
- Admin checks collaboration debug for both users
- Sees `chat_interactions: 0`, `notifications: 0`
- Action: Check notification worker configuration

**Use Case 3: Visualize Team Dynamics**
- Admin selects 4 team members
- Views interaction graph
- User A has strong connections to all
- User D has weak connections
- Action: Identify knowledge silos

---

## 🐛 Troubleshooting

### Error: "vscode_linked: false" but user has extension installed

**Diagnosis**:
```sql
-- Check for VSCode actions
SELECT COUNT(*) FROM user_actions
WHERE user_id = 'USER_ID' AND tool = 'vscode';
```

**If count = 0**: VSCode extension not sending activities
**Fix**: Check extension authentication and API endpoint configuration

---

### Error: "No chat interactions" but users are chatting

**Diagnosis**:
```sql
-- Check chat messages
SELECT COUNT(*) FROM messages
WHERE chat_id IN (
  SELECT DISTINCT chat_id FROM messages
  WHERE user_id IN ('USER1_ID', 'USER2_ID')
);
```

**If count > 0**: Date range issue or chat not shared
**Fix**: Expand date range or check if both users messaged in same chat

---

### Error: Collaboration opportunities show 0 despite common work

**Diagnosis**:
- Check if UserActions have `action_data` with `file_path` or `files`
- Check if `is_status_change = true` for recent actions

**Fix**: Ensure VSCode extension sends file metadata in action_data

---

## ✅ Summary

**Status**: ✅ VSCode and Collaboration Debug endpoints implemented and ready for testing

**What's Working**:
- GET /vscode-debug/{email} with comprehensive activity data
- GET /collaboration-debug with multi-user analysis
- Comprehensive logging throughout
- Admin authentication/authorization
- Interaction graph generation
- Collaboration opportunity detection

**What's Next**:
1. Manual testing with real user data
2. Frontend dashboard implementation
3. Deploy to production
4. Monitor endpoint performance
5. Gather admin feedback for improvements

---

**Implementation Date**: 2026-01-02
**Implemented By**: Claude Sonnet 4.5
**Status**: Ready for Testing
