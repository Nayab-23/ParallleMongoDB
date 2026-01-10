# Organization Intelligence Graph - Backend Endpoints

**Date**: 2026-01-01
**Status**: ✅ **COMPLETE**

---

## Summary

Backend endpoints implemented to support the frontend Organization Intelligence Graph visualization. These endpoints provide aggregated statistics, activities, and relationship data for rooms in the organization.

---

## 🎯 New Endpoints

### 1. GET /api/rooms/{room_id}/stats

**Purpose**: Get aggregated statistics for a single room

**Authentication**: Required (user must be room member)

**Query Parameters**:
- `days` (int, default 7): Time window for statistics in days

**Response**:
```json
{
  "room_id": "uuid",
  "fires": 3,
  "last_active": "2026-01-01T12:00:00Z",
  "recent_activities": [
    {
      "summary": "User completed task: Update API documentation",
      "timestamp": "2026-01-01T11:30:00Z"
    }
  ],
  "risks": [
    {
      "title": "File Conflict with Alice",
      "message": "Alice is also working on auth.py...",
      "created_at": "2026-01-01T10:00:00Z"
    }
  ]
}
```

**Fields**:
- `fires`: Count of urgent unread notifications for room members
- `last_active`: ISO timestamp of most recent activity in room
- `recent_activities`: Last 5 status change activities in room
- `risks`: Last 5 urgent notifications for room members

**Implementation Details**:
- Verifies user is room member (403 if not)
- Notifications aggregated from all room members (no direct room_id on notifications)
- Only includes `is_status_change = true` activities
- All timestamps returned in ISO 8601 format

**Example Request**:
```bash
curl "https://api.parallel.com/api/rooms/300e5cc4-641f-4f4c-97e6-32ce3732f9d1/stats?days=7" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

### 2. GET /api/org/graph-data

**Purpose**: Get complete organization graph data for visualization

**Authentication**: Required

**Query Parameters**:
- `days` (int, default 7): Time window for statistics in days

**Response**:
```json
{
  "rooms": [
    {
      "id": "room-uuid-1",
      "name": "Engineering Team",
      "fires": 2,
      "last_active": "2026-01-01T12:00:00Z",
      "recent_activities": [
        {
          "summary": "Deployed v2.0 to production",
          "timestamp": "2026-01-01T11:00:00Z"
        }
      ],
      "risks": [
        {
          "title": "File Conflict",
          "message": "Multiple users editing same file",
          "created_at": "2026-01-01T10:00:00Z"
        }
      ],
      "members": [
        {
          "id": "user-uuid-1",
          "name": "Alice Smith",
          "email": "alice@company.com"
        },
        {
          "id": "user-uuid-2",
          "name": "Bob Jones",
          "email": "bob@company.com"
        }
      ]
    },
    {
      "id": "room-uuid-2",
      "name": "Product Team",
      "fires": 0,
      "last_active": "2025-12-31T16:00:00Z",
      "recent_activities": [],
      "risks": [],
      "members": [
        {
          "id": "user-uuid-2",
          "name": "Bob Jones",
          "email": "bob@company.com"
        },
        {
          "id": "user-uuid-3",
          "name": "Charlie Brown",
          "email": "charlie@company.com"
        }
      ]
    }
  ],
  "edges": [
    {
      "source": "room-uuid-1",
      "target": "room-uuid-2",
      "overlap": 1,
      "strength": 0.2
    }
  ],
  "last_updated": "2026-01-01T12:30:00Z"
}
```

**Fields**:

**Rooms Array**:
- `id`: Room UUID
- `name`: Room display name
- `fires`: Urgent unread notifications count
- `last_active`: Most recent activity timestamp
- `recent_activities`: Last 5 significant activities
- `risks`: Last 5 urgent notifications
- `members`: List of room members with id, name, email

**Edges Array**:
- `source`: Room UUID (source node)
- `target`: Room UUID (target node)
- `overlap`: Number of shared members
- `strength`: Normalized connection strength (0-1 scale, overlap/5)

**Implementation Details**:
- Only returns rooms user has access to (via room_members table)
- Edges calculated by finding shared members between rooms
- Edge strength normalized: `min(overlap / 5.0, 1.0)`
- Returns empty arrays if user has no room memberships

**Example Request**:
```bash
curl "https://api.parallel.com/api/org/graph-data?days=7" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## 🔄 Existing Endpoints (Verified)

These existing endpoints continue to work as expected:

### GET /api/rooms
Returns list of all rooms user has access to.

**Response**:
```json
[
  {
    "id": "uuid",
    "name": "Team Name",
    "org_id": "org-uuid",
    "created_at": "2026-01-01T00:00:00Z"
  }
]
```

---

### GET /api/rooms/{room_id}/members
Returns members of a specific room.

**Response**:
```json
[
  {
    "id": "member-uuid",
    "room_id": "room-uuid",
    "user_id": "user-uuid",
    "role_in_room": "member",
    "joined_at": "2026-01-01T00:00:00Z"
  }
]
```

---

### GET /api/activity/history
Returns activity history for user or room.

**Query Parameters**:
- `room_id` (optional): Filter by room
- `days` (default 7): Time window

**Response**:
```json
{
  "activities": [
    {
      "id": 123,
      "user_id": "uuid",
      "summary": "Activity summary text",
      "timestamp": "2026-01-01T12:00:00Z",
      "is_status_change": true
    }
  ]
}
```

---

### GET /api/notifications
Returns notifications for user.

**Query Parameters**:
- `severity` (optional): Filter by 'urgent' or 'normal'
- `unread_only` (bool): Only unread notifications

**Response**:
```json
{
  "notifications": [...],
  "total": 10,
  "urgent_count": 3
}
```

---

## 📊 Data Model

### Room Relationships

```
Organization
    ↓
  Rooms (1:many)
    ↓
  RoomMembers (many:many with Users)
    ↓
  UserActions (activities in room)
```

### Notification Aggregation

Since `notifications` table doesn't have `room_id`, we aggregate by:
1. Get all room members → `room_member_ids`
2. Query notifications where `user_id IN (room_member_ids)`
3. Filter by `severity = 'urgent'` and `is_read = false`

This gives us "fires" count per room.

---

## 🧪 Testing

### Test 1: Get Room Stats

```bash
# Get stats for a specific room
curl "http://localhost:8000/api/rooms/ROOM_ID/stats?days=7" \
  -H "Authorization: Bearer TOKEN"
```

**Expected**:
- ✅ Returns room stats with fires, activities, risks
- ✅ Returns 403 if user not room member
- ✅ Returns 404 if room doesn't exist
- ✅ All timestamps in ISO format

---

### Test 2: Get Full Graph Data

```bash
# Get complete graph data
curl "http://localhost:8000/api/org/graph-data?days=7" \
  -H "Authorization: Bearer TOKEN"
```

**Expected**:
- ✅ Returns all rooms user has access to
- ✅ Returns edges based on shared members
- ✅ Edge strength normalized to 0-1
- ✅ Empty arrays if user has no rooms

---

### Test 3: Verify Edge Calculation

```python
# Test edge calculation logic
rooms = [
  {"id": "room-1", "members": [{"id": "user-a"}, {"id": "user-b"}]},
  {"id": "room-2", "members": [{"id": "user-b"}, {"id": "user-c"}]}
]

# Expected edge:
# source: "room-1", target: "room-2", overlap: 1 (user-b), strength: 0.2
```

---

### Test 4: Database Queries

```sql
-- Check room membership
SELECT r.id, r.name, COUNT(rm.user_id) as member_count
FROM rooms r
LEFT JOIN room_members rm ON r.room_id = rm.room_id
GROUP BY r.id, r.name;

-- Check activities per room
SELECT room_id, COUNT(*) as activities,
       COUNT(*) FILTER (WHERE is_status_change = true) as status_changes
FROM user_actions
WHERE room_id IS NOT NULL
GROUP BY room_id;

-- Check urgent notifications per user
SELECT user_id, COUNT(*) as urgent_count
FROM notifications
WHERE severity = 'urgent' AND is_read = false
GROUP BY user_id;
```

---

## 🎨 Frontend Integration

### How Frontend Uses These Endpoints

1. **Initial Load**:
   - Frontend calls `GET /api/org/graph-data`
   - Receives all rooms, edges, and stats
   - Renders graph visualization using D3.js force simulation

2. **Node Click**:
   - User clicks on room node
   - Frontend calls `GET /api/rooms/{room_id}/stats` for fresh data
   - Shows detail panel with activities and risks

3. **Auto-Refresh**:
   - Frontend polls `/api/org/graph-data` every 30-60 seconds
   - Updates node sizes (fires count)
   - Highlights rooms with new urgent notifications

4. **Edge Rendering**:
   - Edges represent shared team members
   - Thickness based on `strength` field (0-1)
   - Helps visualize cross-team collaboration

---

## 🔧 Performance Considerations

### Query Optimization

**Room Stats Endpoint**:
- Single room lookup: Fast (indexed by room_id)
- Member query: Fast (indexed foreign key)
- Notification count: Fast (indexed on user_id, severity, is_read)
- Activities: Fast (indexed on room_id, timestamp)

**Graph Data Endpoint**:
- Queries all user's rooms in one batch
- Loops through rooms for stats (N queries)
- Edge calculation in Python (no DB query)

**Potential Bottleneck**: If user has 50+ rooms, the loop becomes slow

**Optimization Options**:
1. Add caching layer (Redis) with 5-minute TTL
2. Batch queries using subqueries/CTEs
3. Add materialized view for room stats
4. Add background job to pre-calculate stats

### Recommended Caching

```python
# Pseudocode for caching
@cache(ttl=300)  # 5 minutes
async def get_org_graph_data(user_id, days):
    # Expensive queries here
    return graph_data
```

---

## 📈 Scaling Recommendations

### For Large Organizations (100+ rooms)

1. **Pagination**:
   - Add `limit` and `offset` to graph-data endpoint
   - Return rooms in chunks of 50

2. **Filtering**:
   - Add `org_id` parameter to filter by organization
   - Add `active_only` to exclude inactive rooms

3. **Materialized Views**:
   ```sql
   CREATE MATERIALIZED VIEW room_stats AS
   SELECT
     room_id,
     COUNT(*) FILTER (WHERE is_status_change = true) as activity_count,
     MAX(timestamp) as last_active
   FROM user_actions
   GROUP BY room_id;

   REFRESH MATERIALIZED VIEW room_stats;
   ```

4. **Background Jobs**:
   - Pre-calculate stats every 5 minutes
   - Store in `room_stats` table
   - Serve from cache instead of live queries

---

## 🐛 Troubleshooting

### Error: "Not a member of this room" (403)

**Cause**: User tried to access room stats without being a member

**Fix**: Verify user has room membership:
```sql
SELECT * FROM room_members
WHERE user_id = 'USER_ID' AND room_id = 'ROOM_ID';
```

---

### Error: Empty graph data

**Symptom**: `GET /api/org/graph-data` returns `{"rooms": [], "edges": []}`

**Cause**: User has no room memberships

**Fix**: Add user to at least one room:
```sql
INSERT INTO room_members (id, room_id, user_id, joined_at)
VALUES (gen_random_uuid(), 'ROOM_ID', 'USER_ID', NOW());
```

---

### Error: No activities showing

**Symptom**: `recent_activities` always empty

**Cause**: Activities exist but `is_status_change = false`

**Check**:
```sql
SELECT COUNT(*) as total,
       COUNT(*) FILTER (WHERE is_status_change = true) as status_changes
FROM user_actions
WHERE room_id = 'ROOM_ID';
```

**Fix**: Activity manager should set `is_status_change = true` for significant activities

---

### Error: No "fires" showing

**Symptom**: `fires` count always 0

**Cause**: No urgent unread notifications for room members

**Check**:
```sql
-- Get room member IDs
SELECT user_id FROM room_members WHERE room_id = 'ROOM_ID';

-- Check notifications
SELECT COUNT(*) FROM notifications
WHERE user_id IN ('USER_1', 'USER_2')
  AND severity = 'urgent'
  AND is_read = false;
```

**Fix**: Create urgent notifications via notification worker (file conflicts)

---

## 📝 Implementation Notes

### Why Notifications Don't Have room_id

**Design Decision**: Notifications are user-centric, not room-centric

**Implications**:
- Must aggregate notifications through room members
- Query: `WHERE user_id IN (SELECT user_id FROM room_members WHERE room_id = ?)`
- Slightly slower but more flexible

**Alternative Approach**: Add `room_id` to notifications table
- Migration: `ALTER TABLE notifications ADD COLUMN room_id varchar;`
- Set room_id when creating conflict notifications
- Faster queries: `WHERE room_id = ? AND severity = 'urgent'`

---

### Edge Strength Calculation

**Formula**: `min(overlap / 5.0, 1.0)`

**Reasoning**:
- 1 shared member → strength 0.2 (thin edge)
- 3 shared members → strength 0.6 (medium edge)
- 5+ shared members → strength 1.0 (thick edge, capped)

**Customization**: Adjust divisor (5.0) based on typical team size
- Small teams (2-3 people): Use 3.0
- Large teams (10+ people): Use 10.0

---

### Activities vs Status Changes

**All Activities**: Every action logged (chat messages, code edits, etc.)

**Status Changes**: Only significant activities (`is_status_change = true`)
- Determined by similarity threshold in activity manager
- >85% different from previous status → status change
- Used for "recent activities" to avoid noise

---

## ✅ Completion Checklist

- [x] Implemented `GET /api/rooms/{room_id}/stats`
- [x] Implemented `GET /api/org/graph-data`
- [x] Verified existing endpoints work correctly
- [x] Tested with production database
- [x] Added authentication checks (room membership)
- [x] Normalized all timestamps to ISO format
- [x] Calculated edges based on shared members
- [x] Handled edge cases (no rooms, no members, no activities)
- [x] Documented all endpoints
- [x] Documented testing procedures
- [x] Documented troubleshooting steps

---

## 🚀 Deployment Status

**Current State**: ✅ **Ready for Production**

**Files Changed**:
- `main.py`: Added 2 new endpoints (lines 6570-6769)

**Database Changes**: None required (using existing schema)

**Frontend Requirements**: Already implemented, waiting for these endpoints

**Next Steps**:
1. Deploy backend with new endpoints
2. Update frontend API base URL if needed
3. Test with real user accounts
4. Monitor performance with production data
5. Add caching if query times exceed 500ms

---

**Implementation Date**: 2026-01-01
**Implemented By**: Claude Sonnet 4.5
**Status**: Ready for Production Testing
