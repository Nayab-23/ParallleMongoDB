# Notification Detection System - Implementation Complete

**Date**: 2026-01-01
**Status**: ✅ Backend Complete - Ready for Testing

---

## Summary

The notification detection system backend has been fully implemented to support the existing frontend notification panel. The system automatically detects file-based and semantic conflicts between team members and creates notifications with proper severity levels.

---

## 🎯 Components Implemented

### 1. Conflict Detection Service

**File**: `/app/services/conflict_detector.py`

**Functions**:

#### `find_conflicts(db, activity, ...)`
Detects conflicts for a single user activity.

**Parameters**:
- `db`: Database session
- `activity`: UserAction to check for conflicts
- `file_conflict_window_hours`: Time window for file conflicts (default: 24h)
- `semantic_similarity_threshold`: Threshold for semantic conflicts (default: 0.85)
- `semantic_window_days`: Time window for semantic conflicts (default: 7 days)

**Returns**: List of conflict dictionaries containing:
```python
{
    'affected_user_id': str,
    'affected_user_name': str,
    'is_file_conflict': bool,
    'conflict_type': 'file' | 'semantic',
    'file_name': str,
    'files': List[str],
    'similarity': float,
    'other_activity': UserAction,
    'timestamp': datetime
}
```

**Conflict Detection Methods**:

1. **File-Based Conflicts**:
   - Checks `action_data['files']` or `action_data['file_path']`
   - Finds other users editing same files within 24-hour window
   - Uses JSONB queries on action_data field
   - Returns 100% similarity (exact file match)

2. **Semantic Conflicts**:
   - Uses pgvector similarity search on activity embeddings
   - SQL query with vector cosine distance operator `<=>`
   - Filters by similarity threshold (>85%)
   - Returns actual embedding similarity score

**SQL Query Pattern**:
```sql
SELECT id, user_id, activity_summary, timestamp,
       1 - (activity_embedding <=> CAST(:query_embedding AS vector)) as similarity
FROM user_actions
WHERE user_id != :user_id
  AND activity_embedding IS NOT NULL
  AND timestamp >= :cutoff
  AND 1 - (activity_embedding <=> CAST(:query_embedding AS vector)) > :threshold
ORDER BY similarity DESC
LIMIT 10
```

#### `detect_file_conflicts(db, time_window_hours=24)`
Scans recent activities for file-based conflicts across all users.

**Returns**: List of conflict summaries:
```python
{
    'file': str,
    'file_name': str,
    'users': List[str],
    'user_ids': List[str],
    'activities': List[UserAction],
    'activity_count': int
}
```

#### `detect_semantic_conflicts(db, threshold=0.85)`
Scans for semantic conflicts using pgvector self-join.

**Returns**: List of conflict pairs:
```python
{
    'users': List[str],
    'user_ids': List[str],
    'similarity': float,
    'summaries': List[str],
    'type': 'semantic_overlap',
    'activity_ids': List[int]
}
```

---

### 2. Notification Worker

**File**: `/app/workers/notification_worker.py`

**Background Job**: Runs every 15 minutes (configurable via `NOTIFICATION_CHECK_INTERVAL_MINUTES` env var)

**Function**: `detect_and_create_notifications()`

**Process Flow**:

1. **Scan Recent Activities**:
   - Queries `user_actions` table for activities in last 15 minutes
   - Filters for `is_status_change = True` (significant activities only)
   - Ensures `activity_summary IS NOT NULL`

2. **Conflict Detection**:
   - Calls `find_conflicts()` for each activity
   - Detects both file-based and semantic conflicts
   - Gets affected user details from database

3. **Notification Creation**:
   - **File Conflicts** → `severity='urgent'`, `source_type='conflict_file'`
   - **Semantic Conflicts** → `severity='normal'`, `source_type='conflict_semantic'`
   - Includes affected user name, file names, similarity scores
   - Stores conflict metadata in `data` JSONB field

4. **Duplicate Prevention**:
   - Checks for similar notifications in last hour
   - Prevents spam from repeated conflicts
   - Uses source_type and related_user_id for deduplication

**Notification Data Structure**:
```python
{
    'conflict_type': 'file' | 'semantic',
    'related_user_id': str,
    'related_user_name': str,
    'related_activity_id': int,
    'similarity': float,
    'files': List[str],
    'activity_summary': str
}
```

**Logging**:
- Startup: Worker interval, process ID, next run time
- Cycle: Scan summary with file/semantic conflict counts
- Errors: Full stack traces for debugging

---

### 3. VSCode Activity Endpoint

**Endpoint**: `POST /api/vscode/activity`

**Purpose**: Log VSCode activity with automatic summary generation

**Payload**:
```json
{
  "action_type": "code_edit" | "file_save" | "git_commit" | "debug_session",
  "data": {
    "files": ["path/to/file1.py", "path/to/file2.js"],
    "file_path": "path/to/file.py",
    "language": "python",
    "lines_added": 10,
    "lines_deleted": 5,
    "commit_message": "Fixed bug in auth",
    "diff_preview": "...",
    "project_name": "my-project"
  },
  "session_id": "optional-session-id"
}
```

**Response**:
```json
{
  "status": "logged",
  "session_id": "uuid",
  "activity_id": 123,
  "status_updated": true,
  "activity_logged": true
}
```

**Features**:
- Automatic session ID generation (30-minute window)
- Creates `UserAction` with `tool='vscode'`
- Generates AI summary using activity_manager
- Supports multiple action types (code_edit, git_commit, file_save)
- Graceful error handling (logs activity even if summary fails)

**Summary Generation**:
- Git commits → "Committed: {commit_message}"
- Code edits → "Edited file1.py, file2.js +10/-5 lines"
- File saves → "Saved filename.py"

**Integration**:
- Calls `update_user_activity()` for semantic deduplication
- Updates user status if activity is significant
- Logs to activity history for team visibility
- Triggers conflict detection on next worker cycle

---

### 4. Enhanced Notifications Endpoint

**Endpoint**: `GET /api/notifications`

**Query Parameters**:
- `limit` (int, default 50): Max notifications to return
- `unread_only` (bool, default false): Only unread notifications
- `severity` (string): Filter by 'urgent' or 'normal'
- `source_type` (string): Filter by source ('conflict_file', 'conflict_semantic', etc.)

**Response**:
```json
{
  "notifications": [
    {
      "id": "uuid",
      "type": "conflict",
      "severity": "urgent",
      "title": "File Conflict with Alice",
      "message": "Alice is also working on auth.py. You may want to coordinate...",
      "data": {
        "conflict_type": "file",
        "related_user_id": "user-uuid",
        "related_user_name": "Alice",
        "files": ["auth.py"],
        "similarity": 1.0
      },
      "read": false,
      "source_type": "conflict_file",
      "created_at": "2026-01-01T12:00:00Z"
    }
  ],
  "total": 10,
  "urgent_count": 3
}
```

**New Fields**:
- `severity`: 'urgent' or 'normal' (for badge styling)
- `source_type`: Origin of notification (for filtering/grouping)
- `total`: Total count matching filters
- `urgent_count`: Number of unread urgent notifications (for badge)

**Filtering Examples**:
```bash
# Get only urgent notifications
GET /api/notifications?severity=urgent

# Get only unread file conflicts
GET /api/notifications?unread_only=true&source_type=conflict_file

# Get all semantic conflicts
GET /api/notifications?source_type=conflict_semantic
```

---

### 5. Additional Notification Endpoints

#### `POST /api/notifications/mark-all-read`
Mark all notifications as read for current user.

**Response**:
```json
{
  "status": "success",
  "marked_read": 5
}
```

#### `DELETE /api/notifications/{notification_id}`
Delete a specific notification.

**Response**:
```json
{
  "status": "deleted",
  "id": "notification-uuid"
}
```

---

### 6. Database Schema Updates

**File**: `models.py` (updated)

**Notification Model - New Fields**:
```python
class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String, default="task")
    severity = Column(String, default="normal")  # NEW: 'urgent' or 'normal'
    source_type = Column(String, nullable=True)  # NEW: 'conflict_file', 'conflict_semantic', etc.
    title = Column(String, nullable=False)
    message = Column(Text, default="")
    task_id = Column(String, ForeignKey("tasks.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    is_read = Column(Boolean, default=False)
    data = Column(json_field_type, nullable=True, default=dict)

    user = relationship("User")
    task = relationship("Task")
```

**Migration File**: `alembic/versions/20260101_add_notification_fields.py`

**Migration Commands**:
```sql
-- Add columns
ALTER TABLE notifications ADD COLUMN severity VARCHAR DEFAULT 'normal';
ALTER TABLE notifications ADD COLUMN source_type VARCHAR;

-- Add indexes for query performance
CREATE INDEX ix_notifications_severity ON notifications(severity);
CREATE INDEX ix_notifications_source_type ON notifications(source_type);
```

**Rollback Commands**:
```sql
DROP INDEX ix_notifications_source_type;
DROP INDEX ix_notifications_severity;
ALTER TABLE notifications DROP COLUMN source_type;
ALTER TABLE notifications DROP COLUMN severity;
```

---

### 7. Startup Configuration

**File**: `main.py` (updated)

**Worker Initialization** (lines 8751-8757):
```python
try:
    from app.workers.notification_worker import start_notification_worker

    start_notification_worker()
    logger.info("[Startup] ✅ Notification worker started successfully")
except Exception as e:
    logger.error(f"[Startup] ❌ Failed to start notification worker: {e}", exc_info=True)
```

**APScheduler Jobs** (both workers):
1. Canon Worker: Every 1 minute (canon refresh)
2. Notification Worker: Every 15 minutes (conflict detection)

**Environment Variables**:
- `NOTIFICATION_CHECK_INTERVAL_MINUTES` (default: 15)
- `CANON_WORKER_CHECK_INTERVAL_MINUTES` (default: 1)

---

## 🔄 System Flow

### End-to-End Notification Creation

1. **User Activity**:
   - User edits code in VSCode → Sends POST to `/api/vscode/activity`
   - OR user sends chat message → Activity logged via activity_manager
   - `UserAction` record created with tool, action_type, action_data

2. **Activity Summary Generation**:
   - `activity_manager.update_user_activity()` called
   - Generates AI summary using GPT-4o-mini
   - Creates embedding using OpenAI text-embedding-3-small (1536 dimensions)
   - Checks similarity to previous activities (deduplication)
   - Sets `is_status_change = True` if significant (>85% different from status)

3. **Notification Worker Cycle** (every 15 minutes):
   - Queries recent activities with `is_status_change = True`
   - For each activity:
     - Calls `find_conflicts(db, activity)`
     - Detects file conflicts (same files in last 24h)
     - Detects semantic conflicts (>85% embedding similarity in last 7 days)
   - Creates notifications for affected users

4. **Notification Creation**:
   - File conflicts → Urgent severity, clear file names
   - Semantic conflicts → Normal severity, similarity percentage
   - Stores conflict metadata in `data` JSONB field
   - Prevents duplicates (checks last hour for same user/conflict)

5. **Frontend Display**:
   - Frontend polls `/api/notifications` every minute
   - Displays urgent badge with `urgent_count`
   - Shows notifications in panel with severity styling
   - Supports filtering by severity, source type

---

## 📊 Conflict Detection Logic

### File-Based Conflicts

**Criteria**:
- Same file path in `action_data['files']` or `action_data['file_path']`
- Different users
- Within 24-hour window

**Example**:
```json
{
  "User A": {
    "timestamp": "2026-01-01 10:00:00",
    "files": ["src/auth.py", "src/utils.py"]
  },
  "User B": {
    "timestamp": "2026-01-01 11:30:00",  // Within 24h
    "files": ["src/auth.py"]  // Overlapping file
  }
}
```

**Result**: Urgent notification to User B:
> "User A is also working on auth.py. You may want to coordinate to avoid merge conflicts."

---

### Semantic Conflicts

**Criteria**:
- Embedding similarity > 85%
- Different users
- Within 7-day window

**Example**:
```json
{
  "User A": {
    "summary": "Implementing user authentication with JWT tokens",
    "embedding": [0.12, -0.45, 0.89, ...]
  },
  "User B": {
    "summary": "Adding JWT-based auth system for API endpoints",
    "embedding": [0.11, -0.43, 0.91, ...]  // 92% similar
  }
}
```

**Result**: Normal notification to User B:
> "User A is working on something similar (92% match). Their activity: 'Implementing user authentication with JWT tokens'"

---

## 🧪 Testing

### Manual Testing Steps

#### 1. Test VSCode Endpoint
```bash
curl -X POST http://localhost:8000/api/vscode/activity \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "action_type": "code_edit",
    "data": {
      "files": ["src/main.py", "src/utils.py"],
      "language": "python",
      "lines_added": 25,
      "lines_deleted": 10
    }
  }'
```

**Expected Response**:
```json
{
  "status": "logged",
  "session_id": "uuid",
  "activity_id": 123,
  "status_updated": true,
  "activity_logged": true
}
```

**Verification**:
```sql
SELECT id, tool, action_type, activity_summary, is_status_change
FROM user_actions
WHERE user_id = 'YOUR_USER_ID'
ORDER BY timestamp DESC
LIMIT 1;
```

---

#### 2. Test File Conflict Detection
```bash
# User A edits file
curl -X POST http://localhost:8000/api/vscode/activity \
  -H "Authorization: Bearer USER_A_TOKEN" \
  -d '{"action_type": "code_edit", "data": {"files": ["auth.py"]}}'

# User B edits same file
curl -X POST http://localhost:8000/api/vscode/activity \
  -H "Authorization: Bearer USER_B_TOKEN" \
  -d '{"action_type": "code_edit", "data": {"files": ["auth.py"]}}'

# Wait 15 minutes for worker cycle (or trigger manually)

# Check User B's notifications
curl http://localhost:8000/api/notifications?severity=urgent \
  -H "Authorization: Bearer USER_B_TOKEN"
```

**Expected Notification**:
```json
{
  "severity": "urgent",
  "source_type": "conflict_file",
  "title": "File Conflict with User A",
  "message": "User A is also working on auth.py. You may want to coordinate...",
  "data": {
    "conflict_type": "file",
    "files": ["auth.py"],
    "similarity": 1.0
  }
}
```

---

#### 3. Test Semantic Conflict Detection
```bash
# User A: Chat about authentication
curl -X POST http://localhost:8000/api/chat/send \
  -H "Authorization: Bearer USER_A_TOKEN" \
  -d '{"content": "I'\''m working on implementing JWT authentication for the API", "room_id": "room123"}'

# User B: Similar chat (different words, same meaning)
curl -X POST http://localhost:8000/api/chat/send \
  -H "Authorization: Bearer USER_B_TOKEN" \
  -d '{"content": "Building token-based auth system for endpoints", "room_id": "room123"}'

# Wait for worker cycle

# Check notifications
curl http://localhost:8000/api/notifications?source_type=conflict_semantic \
  -H "Authorization: Bearer USER_B_TOKEN"
```

**Expected Notification**:
```json
{
  "severity": "normal",
  "source_type": "conflict_semantic",
  "title": "Related Work: User A",
  "message": "User A is working on something similar (87% match). Their activity: 'I'm working on implementing JWT authentication for the API'",
  "data": {
    "conflict_type": "semantic",
    "similarity": 0.87
  }
}
```

---

#### 4. Test Filtering
```bash
# Get only urgent notifications
curl http://localhost:8000/api/notifications?severity=urgent

# Get only unread notifications
curl http://localhost:8000/api/notifications?unread_only=true

# Get file conflicts only
curl http://localhost:8000/api/notifications?source_type=conflict_file

# Combine filters
curl http://localhost:8000/api/notifications?severity=urgent&unread_only=true
```

---

#### 5. Test Mark All Read
```bash
curl -X POST http://localhost:8000/api/notifications/mark-all-read \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Expected Response**:
```json
{
  "status": "success",
  "marked_read": 5
}
```

---

#### 6. Test Delete Notification
```bash
curl -X DELETE http://localhost:8000/api/notifications/NOTIFICATION_ID \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Expected Response**:
```json
{
  "status": "deleted",
  "id": "NOTIFICATION_ID"
}
```

---

### Database Testing

#### Check Worker Status
```sql
-- Verify notification worker is creating notifications
SELECT COUNT(*), severity, source_type
FROM notifications
WHERE created_at >= NOW() - INTERVAL '1 hour'
GROUP BY severity, source_type;
```

#### Check Activity Summaries
```sql
-- Ensure activities have embeddings and summaries
SELECT id, tool, action_type, activity_summary,
       is_status_change,
       similarity_to_previous,
       activity_embedding IS NOT NULL as has_embedding
FROM user_actions
WHERE timestamp >= NOW() - INTERVAL '1 day'
  AND is_status_change = TRUE
ORDER BY timestamp DESC;
```

#### Check Conflict Detection
```sql
-- Find potential file conflicts
SELECT a1.user_id as user1, a2.user_id as user2,
       a1.action_data->>'files' as files,
       a1.timestamp, a2.timestamp
FROM user_actions a1, user_actions a2
WHERE a1.user_id != a2.user_id
  AND a1.action_data->>'files' = a2.action_data->>'files'
  AND a1.timestamp >= NOW() - INTERVAL '24 hours'
  AND a2.timestamp >= NOW() - INTERVAL '24 hours'
  AND a2.timestamp > a1.timestamp;
```

#### Check Semantic Conflicts
```sql
-- Find similar activities using pgvector
SELECT a1.id, a2.id,
       a1.user_id as user1, a2.user_id as user2,
       a1.activity_summary as summary1,
       a2.activity_summary as summary2,
       1 - (a1.activity_embedding <=> a2.activity_embedding) as similarity
FROM user_actions a1, user_actions a2
WHERE a1.user_id != a2.user_id
  AND a1.activity_embedding IS NOT NULL
  AND a2.activity_embedding IS NOT NULL
  AND a1.timestamp >= NOW() - INTERVAL '7 days'
  AND a2.timestamp >= NOW() - INTERVAL '7 days'
  AND a1.id < a2.id
  AND 1 - (a1.activity_embedding <=> a2.activity_embedding) > 0.85
ORDER BY similarity DESC
LIMIT 20;
```

---

## 🚀 Deployment

### 1. Run Database Migration
```bash
cd /Users/severinspagnola/Desktop/MongoDBHack/apps/api

# Apply migration
alembic upgrade head

# Verify
psql $DATABASE_URL -c "\d notifications"
```

**Expected Output**:
```
Column       | Type      | Modifiers
-------------+-----------+-----------
id           | varchar   | not null
user_id      | varchar   | not null
type         | varchar   |
severity     | varchar   | default 'normal'  ← NEW
source_type  | varchar   |                   ← NEW
title        | varchar   | not null
...
```

---

### 2. Restart Backend
```bash
# Kill existing process
pkill -f "uvicorn main:app"

# Start with new code
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Watch for Startup Logs**:
```
[Startup] ✅ Canon worker started successfully
[Startup] ✅ Notification worker started successfully
🔔 [Notification Worker] 🚀 STARTED (interval: 15 minute(s))
🔔 [Notification Worker] 📅 Next run: 2026-01-01 12:15:00
```

---

### 3. Monitor Worker Logs
```bash
# Tail logs for notification worker
tail -f logs/app.log | grep "Notification Worker"

# Or watch in real-time
watch -n 5 'psql $DATABASE_URL -c "SELECT COUNT(*), severity FROM notifications WHERE created_at >= NOW() - INTERVAL '\''1 hour'\'' GROUP BY severity"'
```

**Expected Cycle Logs** (every 15 minutes):
```
🔔 [Notification Worker] 🔍 Scanning 5 recent status changes for conflicts
🔔 [Notification Worker] 📬 Created urgent notification for Alice: file conflict with Bob
🔔 [Notification Worker] 📬 Created normal notification for Charlie: semantic conflict with Alice
🔔 [Notification Worker] ════════════════════════════════════════
🔔 [Notification Worker] ✅ Scan complete: 2 notifications created
🔔 [Notification Worker]    📁 File conflicts: 1
🔔 [Notification Worker]    🧠 Semantic conflicts: 1
🔔 [Notification Worker] ════════════════════════════════════════
```

---

### 4. Configure Environment Variables (Optional)
```bash
# In .env or Render environment
NOTIFICATION_CHECK_INTERVAL_MINUTES=15  # Default: 15
CANON_WORKER_CHECK_INTERVAL_MINUTES=1   # Default: 1
```

---

## 🎨 Frontend Integration

The frontend notification panel is already complete and ready to use. No frontend changes needed.

**Existing Frontend Features**:
- ✅ Badge with urgent count
- ✅ Notification panel with severity styling
- ✅ Mark as read functionality
- ✅ Delete notifications
- ✅ Auto-refresh every minute

**Backend Now Provides**:
- ✅ `urgent_count` field in response
- ✅ `severity` field on each notification
- ✅ `source_type` for filtering
- ✅ Filtering query parameters
- ✅ Mark all read endpoint
- ✅ Delete endpoint

**Frontend Will Automatically**:
- Display urgent badge when `urgent_count > 0`
- Style urgent notifications differently
- Show conflict details in notification message
- Update badge when notifications marked read

---

## 📈 Performance Considerations

### Database Indexes

**Already Indexed**:
- `user_actions.user_id` (for conflict queries)
- `user_actions.timestamp` (for time-based filtering)
- `user_actions.activity_embedding` (IVFFlat index for vector search)
- `notifications.user_id` (for user notification queries)

**New Indexes** (from migration):
- `notifications.severity` (for urgent filtering)
- `notifications.source_type` (for conflict type filtering)

### Query Optimization

**Notification Worker**:
- Looks back only 15 minutes + 1 minute buffer (minimal rows)
- Filters for `is_status_change = True` (sparse dataset)
- Uses pgvector IVFFlat index for fast similarity search
- Limits semantic search to 10 results per activity

**Notifications Endpoint**:
- Paginated with `LIMIT` (default 50)
- Indexed queries for severity and source_type
- Separate count query for urgent_count (indexed)

### Scaling Recommendations

**For Large Teams** (100+ users):
1. Increase semantic search limit cautiously (more = slower)
2. Consider lowering semantic_window_days from 7 to 3-5 days
3. Add caching layer for `urgent_count` (Redis)
4. Consider async notification creation (Celery/RQ)

**For High Activity** (1000+ actions/hour):
1. Consider increasing worker interval to 30 minutes
2. Add activity rate limiting (max 1 notification per user per hour)
3. Batch notification creation (commit every 10 instead of every 1)
4. Add background job queue for conflict detection

---

## 🔧 Troubleshooting

### Worker Not Starting

**Symptom**: No logs from notification worker on startup

**Check**:
```bash
# Verify import works
python3 -c "from app.workers.notification_worker import start_notification_worker"

# Check for import errors
grep "Failed to start notification worker" logs/app.log
```

**Fix**:
- Ensure `conflict_detector.py` exists and has no syntax errors
- Verify `models.py` has updated Notification class
- Check database migration applied (`alembic current`)

---

### No Notifications Created

**Symptom**: Worker runs but creates 0 notifications

**Check**:
```sql
-- Are there recent status changes?
SELECT COUNT(*) FROM user_actions
WHERE is_status_change = TRUE
  AND timestamp >= NOW() - INTERVAL '1 hour';

-- Do activities have embeddings?
SELECT COUNT(*) FROM user_actions
WHERE activity_embedding IS NOT NULL
  AND timestamp >= NOW() - INTERVAL '1 hour';

-- Are there any conflicts?
SELECT COUNT(*) FROM notifications
WHERE created_at >= NOW() - INTERVAL '1 hour';
```

**Fix**:
- Send chat messages or VSCode activities to create status changes
- Ensure activity_manager is generating embeddings
- Lower similarity threshold temporarily (0.7 instead of 0.85) for testing
- Check worker logs for errors during conflict detection

---

### Urgent Count Not Showing

**Symptom**: `urgent_count` is always 0

**Check**:
```sql
-- Are there any urgent notifications?
SELECT COUNT(*) FROM notifications
WHERE severity = 'urgent' AND is_read = FALSE;

-- Is severity column populated?
SELECT severity, COUNT(*) FROM notifications
GROUP BY severity;
```

**Fix**:
- Run migration if severity column missing
- Create file conflict (edit same file with 2 users)
- Check notification creation logs for errors
- Verify frontend is reading `urgent_count` from response

---

### Duplicate Notifications

**Symptom**: Same conflict notified multiple times

**Check**:
```sql
-- Check for duplicate notifications
SELECT user_id, source_type, data->>'related_user_id',
       COUNT(*), MIN(created_at), MAX(created_at)
FROM notifications
WHERE created_at >= NOW() - INTERVAL '2 hours'
GROUP BY user_id, source_type, data->>'related_user_id'
HAVING COUNT(*) > 1;
```

**Fix**:
- Duplicate prevention should check last hour
- Verify worker isn't running multiple instances
- Check for multiple processes (Render auto-scaling)
- Add unique constraint if needed

---

### Slow Notification Queries

**Symptom**: `/api/notifications` takes >500ms

**Check**:
```sql
-- Explain query performance
EXPLAIN ANALYZE
SELECT * FROM notifications
WHERE user_id = 'YOUR_USER_ID'
  AND severity = 'urgent'
  AND is_read = FALSE
ORDER BY created_at DESC
LIMIT 50;
```

**Fix**:
- Ensure migration created indexes
- Run `VACUUM ANALYZE notifications;`
- Consider composite index: `(user_id, is_read, severity, created_at)`
- Add Redis caching for `urgent_count`

---

## 📚 Additional Resources

### Related Files
- `/app/services/activity_manager.py` - Activity summary generation
- `/app/services/rag.py` - pgvector similarity search patterns
- `/app/workers/canon_worker.py` - Background worker example
- `/models.py` - Database schema
- `/main.py` - API endpoints

### Documentation
- `NOTIFICATION_SYSTEM_ARCHITECTURE_AUDIT.md` - Pre-implementation audit
- `ACTIVITY_HISTORY_INVESTIGATION.md` - Activity system investigation
- `RIGHT_SIDEBAR_ADMIN_ONLY.md` - Frontend admin controls

### Dependencies
- **pgvector 0.8.1**: PostgreSQL vector extension
- **APScheduler**: Background job scheduling
- **OpenAI API**: Embeddings and summaries
- **SQLAlchemy**: ORM and migrations
- **Alembic**: Database migrations

---

## ✅ Completion Checklist

- [x] Created `conflict_detector.py` service
- [x] Implemented `find_conflicts()` function
- [x] Implemented `detect_file_conflicts()` function
- [x] Implemented `detect_semantic_conflicts()` function
- [x] Created `notification_worker.py` background job
- [x] Added APScheduler configuration
- [x] Added VSCode activity endpoint (`POST /api/vscode/activity`)
- [x] Enhanced notifications endpoint with filtering
- [x] Added `urgent_count` to notifications response
- [x] Added `severity` and `source_type` to response
- [x] Created `POST /api/notifications/mark-all-read` endpoint
- [x] Created `DELETE /api/notifications/{id}` endpoint
- [x] Updated Notification model with new fields
- [x] Created database migration
- [x] Added worker startup to main.py
- [x] Documented testing procedures
- [x] Documented deployment steps

---

## 🚦 Status

**Current State**: ✅ **Implementation Complete**

**Ready For**:
1. Database migration (`alembic upgrade head`)
2. Backend restart
3. Frontend testing
4. User acceptance testing

**Next Steps**:
1. Apply database migration
2. Restart backend with new code
3. Monitor worker logs for 1 hour
4. Test with real user activities
5. Verify notifications appear in frontend
6. Tune similarity thresholds if needed
7. Adjust worker interval based on activity volume

---

**Implementation Date**: 2026-01-01
**Implemented By**: Claude Sonnet 4.5
**Status**: Ready for Production Testing
