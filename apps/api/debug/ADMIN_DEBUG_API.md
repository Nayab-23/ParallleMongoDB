# Admin Debug Dashboard API Documentation

**Date**: 2026-01-02
**Status**: ✅ **IMPLEMENTED**

---

## Summary

Backend API endpoints for the Admin Debug Dashboard, providing real-time diagnostics and insights into the Timeline generation system, VSCode activity tracking, and collaboration features.

**Current Implementation**: Timeline Debug endpoints (MVP complete)

---

## 🎯 Implemented Endpoints

### 1. GET /api/admin/timeline/timeline-debug/{user_email}

**Purpose**: Get detailed timeline generation debug information for a specific user

**Authentication**: Required (platform admin only)

**Path Parameters**:
- `user_email` (string): Email address of the user to debug

**Response**:
```json
{
  "user": "user@example.com",
  "user_id": "uuid",
  "last_refresh": "2026-01-02T12:00:00Z",
  "data_source": "cache",

  "stages": {
    "stage_0": {
      "total_items": 650,
      "calendar_events": 150,
      "emails": 500,
      "timestamp": "2026-01-02T12:00:00Z"
    },
    "stage_final_pre_ai": {
      "total_items": 245,
      "emails": 120,
      "calendar_events": 125,
      "items_lost_total": 405
    },
    "stage_post_ai": {
      "total_items": 19,
      "1d_items": 5,
      "7d_items": 7,
      "28d_items": 7
    },
    "stage_65_recurring": {
      "events_before": 125,
      "events_after": 125,
      "patterns_consolidated": 0
    }
  },

  "recurring_consolidation": {
    "patterns_detected": [],
    "pattern_count": 0
  },

  "ai_processing": {
    "items_sent": 245,
    "items_returned": 19,
    "excluded": 405,
    "validation_fixes": 5
  },

  "guardrails": {
    "1d_before": "unknown",
    "1d_after": 5,
    "7d_before": "unknown",
    "7d_after": 7,
    "backfill_triggered": "unknown"
  },

  "current_timeline": {
    "1d": {
      "urgent": [
        {
          "title": "Sprint Planning",
          "deadline": "Due in 3 hours",
          "source_type": "calendar"
        }
      ],
      "normal": [...]
    },
    "7d": {...},
    "28d": {...},
    "total_items": 19
  },

  "recent_completions": [
    {
      "title": "Review PRs",
      "completed_at": "2026-01-01T15:00:00Z",
      "signature": "review-prs-abc123"
    }
  ],
  "total_completions": 42
}
```

**Fields Explained**:

**data_source**:
- `"cache"`: Data from in-memory cache (most recent refresh)
- `"logs"`: Parsed from timeline_diagnostics.log file
- `"estimates"`: Estimated from current timeline state (no logs/cache available)

**stages**: Stage-by-stage processing counts
- `stage_0`: Initial items (raw emails + calendar events)
- `stage_1`: After source_id deduplication
- `stage_2`: After similarity deduplication
- `stage_3`: After semantic deduplication
- `stage_4`: After semantic dedup (includes emails)
- `stage_5`: After time-based filtering (past events removed)
- `stage_65_recurring`: After recurring event consolidation
- `stage_final_pre_ai`: Items sent to AI
- `stage_post_ai`: Items returned by AI after categorization

**recurring_consolidation**:
- `patterns_detected`: List of recurring event titles that were consolidated
- `pattern_count`: Number of unique patterns found

**ai_processing**:
- `items_sent`: Total items sent to AI for categorization
- `items_returned`: Total items AI returned in timeline
- `excluded`: Items filtered out before AI or excluded by AI
- `validation_fixes`: Number of deadline_raw fields restored after AI

**guardrails**:
- Tracks min/max enforcement for each timeframe
- Shows backfill operations when buckets are too empty

**current_timeline**: The actual timeline currently stored in database

**recent_completions**: Last 10 completed items (for deletion filter context)

**Example Request**:
```bash
curl "http://localhost:8000/api/admin/timeline/timeline-debug/severin.spagnola@sjsu.edu" \
  -H "Cookie: access_token=YOUR_ADMIN_TOKEN"
```

---

### 2. POST /api/admin/timeline/timeline-debug/{user_email}/refresh

**Purpose**: Manually trigger a timeline refresh for a specific user

**Authentication**: Required (platform admin only)

**Path Parameters**:
- `user_email` (string): Email address of the user to refresh

**Response**:
```json
{
  "success": true,
  "user": "user@example.com",
  "message": "Timeline refresh triggered successfully",
  "timestamp": "2026-01-02T12:00:00Z",
  "result": "Timeline generated"
}
```

**Error Response**:
```json
{
  "success": false,
  "user": "user@example.com",
  "error": "Error message here",
  "traceback": "Full Python traceback...",
  "timestamp": "2026-01-02T12:00:00Z"
}
```

**Example Request**:
```bash
curl -X POST "http://localhost:8000/api/admin/timeline/timeline-debug/severin.spagnola@sjsu.edu/refresh" \
  -H "Cookie: access_token=YOUR_ADMIN_TOKEN"
```

**Use Case**:
- Force a fresh timeline generation for debugging
- Test changes to timeline logic immediately
- Clear cached/stale data for a user

---

### 3. GET /api/admin/timeline/users

**Purpose**: Get list of all users in the system

**Authentication**: Required (platform admin only)

**Response**:
```json
{
  "users": [
    {
      "email": "user1@example.com",
      "name": "User One",
      "id": "uuid-1",
      "created_at": "2025-12-01T00:00:00Z",
      "is_platform_admin": false
    },
    {
      "email": "admin@example.com",
      "name": "Admin User",
      "id": "uuid-2",
      "created_at": "2025-11-01T00:00:00Z",
      "is_platform_admin": true
    }
  ],
  "total_users": 2
}
```

**Example Request**:
```bash
curl "http://localhost:8000/api/admin/timeline/users" \
  -H "Cookie: access_token=YOUR_ADMIN_TOKEN"
```

**Use Case**:
- Populate user selector dropdown in admin dashboard
- Browse all users in the system
- Filter to admin users only (frontend can filter by `is_platform_admin`)

---

## 🔐 Authentication & Authorization

All admin endpoints require:

1. **Authentication**: Valid JWT token in `access_token` cookie
2. **Authorization**: User must have `is_platform_admin = true`

**Error Responses**:

**401 Unauthorized** (not logged in):
```json
{
  "detail": "Not authenticated"
}
```

**403 Forbidden** (not admin):
```json
{
  "detail": "Admin access required"
}
```

**404 Not Found** (user doesn't exist):
```json
{
  "detail": "User user@example.com not found"
}
```

---

## 📊 Data Caching System

### In-Memory Cache

The timeline generation system now caches debug data in memory for fast retrieval:

**Location**: `app/services/canon.py` → `TIMELINE_DEBUG_CACHE`

**Cache Structure**:
```python
TIMELINE_DEBUG_CACHE = {
    "user@example.com": {
        "timestamp": "2026-01-02T12:00:00Z",
        "stages": {
            "stage_0": {"total_items": 650, ...},
            "stage_final_pre_ai": {...},
            "stage_post_ai": {...}
        },
        "recurring_patterns": ["Daily Standup", "Weekly Review"],
        "ai_items_sent": 245,
        "ai_items_returned": 19,
        "ai_excluded": 405,
        "validation_fixes": 5,
        "guardrails": {
            "1d_backfill": 2,
            "7d_backfill": 0
        }
    }
}
```

**Cache Functions** (in `canon.py`):
- `cache_stage_data(user_email, stage, data)`: Cache stage metrics
- `cache_recurring_pattern(user_email, title)`: Cache recurring pattern detection
- `cache_ai_stats(user_email, sent, returned, excluded)`: Cache AI processing stats
- `cache_validation_fix(user_email, count)`: Cache validation fix count
- `cache_guardrail(user_email, timeframe, count, type)`: Cache guardrail activation

**Cache Lifecycle**:
- Created during timeline generation
- Persists until server restart
- Overwritten on each timeline refresh
- Retrieved by admin debug endpoints

**Fallback**: If cache is not available, endpoints parse `timeline_diagnostics.log` file

---

## 🧪 Testing Checklist

### Manual Testing

**Test 1**: Get timeline debug data
```bash
curl "http://localhost:8000/api/admin/timeline/timeline-debug/severin.spagnola@sjsu.edu" \
  -H "Cookie: access_token=ADMIN_TOKEN" | jq
```

**Expected**:
- ✅ Returns 200 OK
- ✅ Contains `stages` object with stage counts
- ✅ Shows `data_source` (cache, logs, or estimates)
- ✅ Includes current timeline buckets (1d, 7d, 28d)
- ✅ Lists recent completions

---

**Test 2**: Trigger timeline refresh
```bash
curl -X POST "http://localhost:8000/api/admin/timeline/timeline-debug/severin.spagnola@sjsu.edu/refresh" \
  -H "Cookie: access_token=ADMIN_TOKEN" | jq
```

**Expected**:
- ✅ Returns 200 OK
- ✅ `success: true`
- ✅ New timeline generated in database
- ✅ Cache updated with fresh data

---

**Test 3**: Get user list
```bash
curl "http://localhost:8000/api/admin/timeline/users" \
  -H "Cookie: access_token=ADMIN_TOKEN" | jq
```

**Expected**:
- ✅ Returns list of all users
- ✅ Each user has email, name, id, created_at
- ✅ Shows `total_users` count

---

**Test 4**: Non-admin access (should fail)
```bash
curl "http://localhost:8000/api/admin/timeline/users" \
  -H "Cookie: access_token=NON_ADMIN_TOKEN" | jq
```

**Expected**:
- ✅ Returns 403 Forbidden
- ✅ Error message: "Admin access required"

---

**Test 5**: Invalid user email
```bash
curl "http://localhost:8000/api/admin/timeline/timeline-debug/nonexistent@example.com" \
  -H "Cookie: access_token=ADMIN_TOKEN" | jq
```

**Expected**:
- ✅ Returns 404 Not Found
- ✅ Error message: "User nonexistent@example.com not found"

---

## 📁 Files Modified/Created

### New Files:
- `app/api/admin/__init__.py`: Admin module init file
- `app/api/admin/timeline.py`: Timeline debug endpoints (378 lines)

### Modified Files:
- `app/api/admin.py`: Include timeline router
- `main.py`: Inject get_current_user dependency
- `app/services/canon.py`: Add caching infrastructure (63 new lines)

---

## 🔄 Frontend Integration

### Timeline Debug Dashboard

The frontend dashboard will call these endpoints to display:

1. **User Selector Dropdown**:
   - Calls `GET /api/admin/timeline/users`
   - Populates dropdown with all users
   - Filters to show admins vs. non-admins

2. **Stage Breakdown Table**:
   - Calls `GET /api/admin/timeline/timeline-debug/{email}`
   - Displays stage-by-stage item counts
   - Shows loss percentages (Stage 0 → Stage Final)

3. **Recurring Patterns Section**:
   - Shows `recurring_consolidation.patterns_detected`
   - Displays how many events were consolidated

4. **AI Processing Stats**:
   - Items sent vs. items returned
   - Validation fixes applied
   - Excluded items count

5. **Current Timeline Viewer**:
   - Shows actual timeline buckets (1d, 7d, 28d)
   - Displays urgent vs. normal items
   - Renders item titles and deadlines

6. **Manual Refresh Button**:
   - Calls `POST /api/admin/timeline/timeline-debug/{email}/refresh`
   - Shows loading spinner
   - Refreshes debug data after completion

---

## 🚀 Deployment Status

**Current State**: ✅ **READY FOR TESTING**

**Implementation Checklist**:
- [x] Create admin timeline router structure
- [x] Implement GET /timeline-debug/{user_email}
- [x] Implement POST /timeline-debug/{user_email}/refresh
- [x] Implement GET /users
- [x] Add stage data caching to canon.py
- [x] Register admin router in main.py
- [x] Syntax validation (no errors)
- [ ] **NEXT**: Manual testing with production data
- [ ] **NEXT**: Frontend integration
- [ ] **NEXT**: WebSocket live updates (optional)

**Deployment Notes**:
- No database migrations required (uses existing tables)
- No environment variables needed
- Cache is in-memory (will be empty on first request after deploy)
- Log parsing requires `timeline_diagnostics.log` file to exist

---

## 🐛 Troubleshooting

### Error: "Admin access required" (403)

**Cause**: User is not a platform admin

**Fix**: Set `is_platform_admin = true` for user:
```sql
UPDATE users SET is_platform_admin = true WHERE email = 'admin@example.com';
```

---

### Error: "No timeline found for this user"

**Cause**: User has never generated a timeline

**Solution**: Trigger manual refresh:
```bash
curl -X POST "http://localhost:8000/api/admin/timeline/timeline-debug/{email}/refresh" \
  -H "Cookie: access_token=ADMIN_TOKEN"
```

---

### Error: Data source shows "estimates" instead of "cache"

**Cause**: Timeline hasn't been refreshed since server restart (cache is empty)

**Solution**:
1. Trigger manual refresh to populate cache
2. Or wait for automatic timeline worker to run

---

### Error: Stages object is empty

**Cause**:
- Cache is empty (server just restarted)
- Log file doesn't exist or doesn't contain user's data

**Solution**:
- Trigger timeline refresh to populate cache
- Check that `logs/timeline_diagnostics.log` exists and has data

---

## 📈 Future Enhancements

### Phase 2: VSCode Debug Endpoints

**Planned**:
- `GET /api/admin/vscode-debug/{user_email}`: VSCode activity tracking stats
- `GET /api/admin/vscode-debug/file-conflicts`: Recent file conflict detections

### Phase 3: Collaboration Debug Endpoints

**Planned**:
- `GET /api/admin/collab-debug/{room_id}`: Room collaboration metrics
- `GET /api/admin/collab-debug/notifications`: Notification worker status

### Phase 4: System Health Endpoints

**Planned**:
- `GET /api/admin/system/workers`: Background worker health
- `GET /api/admin/system/database`: Database connection pool stats
- `GET /api/admin/system/logs`: Download log files

### Phase 5: WebSocket Live Updates

**Planned**:
- `WS /ws/timeline-debug/{user_email}`: Live stage updates during refresh
- Push stage counts in real-time as timeline generates
- Show progress bar in frontend

---

## ✅ Completion Summary

**Status**: ✅ Timeline Debug endpoints implemented and ready for testing

**What's Working**:
- GET timeline debug data (with caching)
- POST timeline refresh trigger
- GET user list for dropdown
- Admin authentication/authorization
- Stage data caching in canon.py
- Log parsing fallback

**What's Next**:
1. Manual testing with real user data
2. Frontend dashboard implementation
3. Deploy to production
4. Monitor cache performance
5. Add WebSocket support (optional)

---

**Implementation Date**: 2026-01-02
**Implemented By**: Claude Sonnet 4.5
**Status**: Ready for Testing
