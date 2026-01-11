# Activity History Investigation Report

## Summary

Investigation completed for user `5bdc33dc-1bdf-4db0-bd66-91e7702e6aaf` to determine why activity history appears empty or incomplete.

**Status**: ✅ SYSTEM WORKING AS DESIGNED
**Finding**: Only **2 activities within the 7-day window**, which is expected behavior

---

## Database Analysis

### Total Activities for User
```sql
SELECT COUNT(*), MAX(timestamp) as latest, MIN(timestamp) as earliest
FROM user_actions
WHERE user_id = '5bdc33dc-1bdf-4db0-bd66-91e7702e6aaf';
```

**Result**:
- **Total**: 3 activities
- **Latest**: 2026-01-01 23:44:17 (7 minutes ago)
- **Earliest**: 2025-12-24 06:17:24 (8.7 days ago)

---

### All Activities with Details

```sql
SELECT id, timestamp, tool, action_type, activity_summary, is_status_change
FROM user_actions
WHERE user_id = '5bdc33dc-1bdf-4db0-bd66-91e7702e6aaf'
ORDER BY timestamp DESC;
```

| ID | Timestamp | Age | Summary | Status Change |
|----|-----------|-----|---------|---------------|
| 8 | 2026-01-01 23:44:17 | **7 min** | "Finalizing development for pilot testing with tech companies." | ✅ Yes |
| 7 | 2025-12-31 07:09:25 | **1.7 days** | "Check calendar for events on the 17th; review monthly objectives." | ✅ Yes |
| 1 | 2025-12-24 06:17:24 | **8.7 days** | "Discussing: I specifically want to make the UX very nice/apple-ish to use so users enjoy using it" | ✅ Yes |

---

### Activities Within 7-Day Window

```sql
SELECT id, timestamp, activity_summary
FROM user_actions
WHERE user_id = '5bdc33dc-1bdf-4db0-bd66-91e7702e6aaf'
  AND activity_summary IS NOT NULL
  AND timestamp >= NOW() - INTERVAL '7 days'
ORDER BY timestamp DESC;
```

**Result**: **2 activities** (IDs 8 and 7)
- Activity #1 is **8.7 days old**, falling outside the 7-day window ❌

---

## Backend Endpoint Analysis

### Endpoint: `GET /api/activity/history`

**Location**: `main.py` lines 4453-4510

**Query Logic**:
```python
since = datetime.now(timezone.utc) - timedelta(days=days)

activities = db.query(UserAction).filter(
    UserAction.user_id == target_user_id,
    UserAction.timestamp >= since,
    UserAction.activity_summary.isnot(None)  # ← CRITICAL FILTER
).order_by(desc(UserAction.timestamp)).limit(limit).all()
```

**Key Filters**:
1. ✅ User ID match
2. ✅ Timestamp within `days` parameter (default 7)
3. ✅ Activity summary must exist (not NULL)

**Default Parameters**:
- `days=7` (This Week)
- `limit=50`

---

## Activity Creation Flow

### Where Activities Are Created

**Endpoint**: `POST /api/actions` (main.py line 7439)

```python
user_action = UserAction(
    user_id=current_user.id,
    tool=tool,                    # e.g., "chat"
    action_type=action_type,      # e.g., "chat_message"
    action_data=action_data,
    task_id=action.get("task_id"),
    session_id=session_id,
)
```

**NOTE**: `activity_summary` is **NOT** set during creation! ⚠️

---

### When Summaries Are Generated

Activities are created **without** summaries initially. The `activity_summary` field must be populated by a **background process** or **hook** (not found in current investigation).

**Evidence**:
- All 3 activities for this user have summaries
- All are marked as `is_status_change = true`
- Summaries are AI-generated (natural language, not raw action data)

**Hypothesis**: There's a background job or status change detection system that:
1. Monitors new `UserAction` records
2. Generates AI summaries for significant activities
3. Sets `is_status_change = true` for status-worthy actions
4. Populates `activity_summary` field

**To Find**: Search for:
- Background workers/celery tasks
- Status update hooks
- AI summary generation code
- Database triggers

---

## Frontend Analysis

### Component: `ActivityHistory.jsx`

**Location**: `/Users/severinspagnola/Desktop/MongoDBHack/apps/web/src/components/activity/ActivityHistory.jsx`

**Time Range Options**:
- Today (1 day)
- This Week (7 days) ← **Default**
- This Month (30 days)

**Rendering Logic**:
```javascript
const loadActivities = async () => {
  const data = await getActivityHistory(userId, timeRange, 50);
  setActivities(data.activities || []);
};
```

**Display**:
```javascript
{activities.length === 0 ? (
  <div className="no-activities">No activity yet</div>
) : (
  activities.map((activity, index) => (
    <div className="activity-item">
      <div className="activity-time">{formatTimestamp(activity.timestamp)}</div>
      <div className="activity-summary">{String(summaryText)}</div>
    </div>
  ))
)}
```

**Extensive Debug Logging**:
- ✅ Console logs total activities received
- ✅ Character-by-character analysis of summaries
- ✅ Pattern detection for control characters
- ✅ Normalization testing
- ✅ Render data for first 3 items

---

## Expected Behavior

### For This Specific User

**With `days=7` (This Week)**:
- ✅ Should show **2 activities** (IDs 8 and 7)
- ❌ Should NOT show activity ID 1 (too old)

**With `days=30` (This Month)**:
- ✅ Should show **3 activities** (all of them)

**With `days=1` (Today)**:
- ✅ Should show **1 activity** (ID 8 only)

---

## Activity Creation Frequency

### When Are New Activities Created?

Based on the 3 existing activities:
1. **Chat messages** trigger activity creation
2. Activities are **NOT** created for every chat message
3. Activities appear to be **status changes** only
4. All 3 have `is_status_change = true`

### Why Not More Activities?

Possible reasons for sparse activity log:
1. **Similarity Filtering**: Similar messages might be deduplicated
2. **Status Change Detection**: Only "significant" activities trigger summaries
3. **Manual Logging**: Activities might be manually logged, not automatic
4. **Background Job Delay**: Summaries might be generated asynchronously with delay

---

## Testing Recommendations

### Test 1: Create New Activity
```bash
# Send a chat message and verify activity creation
# Check if it appears in user_actions table
# Verify if activity_summary is populated
```

### Test 2: Check Time Range Filter
```bash
# Change frontend dropdown to "This Month" (30 days)
# Should see all 3 activities instead of 2
```

### Test 3: Send Multiple Messages
```bash
# Send 5 different chat messages
# Check if 5 new activities are created
# Verify summaries are generated
# Check similarity_to_previous scores
```

### Test 4: Find Background Job
```bash
# Search for activity summary generation code
grep -r "activity_summary" --include="*.py"
grep -r "is_status_change" --include="*.py"
grep -r "generate.*summary" --include="*.py"
```

---

## Database Schema

### UserAction Model
```python
class UserAction(Base):
    __tablename__ = "user_actions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    tool = Column(String, nullable=False)          # "chat", "gmail", "calendar", etc.
    action_type = Column(String, nullable=False)   # "chat_message", "email_sent", etc.
    action_data = Column(json_field_type, nullable=False)

    task_id = Column(String, ForeignKey("tasks.id"), nullable=True, index=True)
    session_id = Column(String, nullable=True, index=True)

    # Activity manager columns (populated by background job?)
    activity_summary = Column(Text, nullable=True)              # AI-generated summary
    activity_embedding = Column(vector_field_type, nullable=True)
    similarity_to_status = Column(Float, nullable=True)         # Similarity to current status
    similarity_to_previous = Column(Float, nullable=True)       # Similarity to previous activity
    is_status_change = Column(Boolean, server_default='false')  # Is this a status change?
    room_id = Column(String, ForeignKey("rooms.id"), nullable=True)
```

---

## Findings Summary

### ✅ Working Correctly
1. **Backend query** properly filters by time range (7 days)
2. **Frontend component** correctly displays received activities
3. **Database contains** valid activities with summaries
4. **Time filtering** excludes activities older than 7 days

### ⚠️ Questions Remaining
1. **Where are activity summaries generated?** (Background job not found)
2. **Why only 3 activities for this user?** (Are chat messages creating activities?)
3. **What triggers `is_status_change = true`?** (All 3 are status changes)
4. **Is there deduplication happening?** (Similarity scores suggest yes)

### 📊 Expected User Experience
- User sends chat messages
- System creates `UserAction` records
- Background job generates summaries (async?)
- Only "significant" activities get summaries
- Frontend filters by time range (7 days default)
- **Result**: Sparse activity log showing only major status changes

---

## Recommendations

### For More Frequent Activity Updates

If you want to see more activities:

1. **Reduce similarity threshold** - Allow more similar activities to be logged
2. **Lower status change criteria** - Log more activities as status changes
3. **Auto-generate summaries** - Generate summaries for ALL chat messages, not just status changes
4. **Increase time range** - Default to 30 days instead of 7 days

### For Investigation

1. **Find background job** that generates summaries
2. **Check similarity algorithm** - How similar is "too similar"?
3. **Review status change logic** - What makes an activity a "status change"?
4. **Add logging** to activity creation to track when summaries are generated

---

## Quick Verification Commands

```bash
# Check total activities (all time)
psql $DATABASE_URL -c "SELECT COUNT(*) FROM user_actions WHERE user_id = '5bdc33dc-1bdf-4db0-bd66-91e7702e6aaf';"

# Check activities with summaries (7 days)
psql $DATABASE_URL -c "SELECT COUNT(*) FROM user_actions WHERE user_id = '5bdc33dc-1bdf-4db0-bd66-91e7702e6aaf' AND activity_summary IS NOT NULL AND timestamp >= NOW() - INTERVAL '7 days';"

# Check activities with summaries (30 days)
psql $DATABASE_URL -c "SELECT COUNT(*) FROM user_actions WHERE user_id = '5bdc33dc-1bdf-4db0-bd66-91e7702e6aaf' AND activity_summary IS NOT NULL AND timestamp >= NOW() - INTERVAL '30 days';"

# View latest activities
psql $DATABASE_URL -c "SELECT id, timestamp, LEFT(activity_summary, 50) as summary FROM user_actions WHERE user_id = '5bdc33dc-1bdf-4db0-bd66-91e7702e6aaf' AND activity_summary IS NOT NULL ORDER BY timestamp DESC LIMIT 10;"
```

---

## Conclusion

**System Status**: ✅ **Working as designed**

The activity history endpoint is functioning correctly:
- Returns 2 activities for 7-day window (correct)
- Would return 3 activities for 30-day window (correct)
- Filters out activity #1 as too old (8.7 days)

**Next Steps**:
1. Switch frontend to "This Month" to see all 3 activities
2. Send more chat messages to create more activities
3. Investigate background summary generation system
4. Consider lowering similarity threshold for more frequent updates
