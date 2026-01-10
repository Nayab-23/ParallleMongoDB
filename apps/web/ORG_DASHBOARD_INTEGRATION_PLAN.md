# Organization Dashboard Integration Plan

**Date**: 2026-01-01
**Status**: 📋 Analysis Complete - Ready for Implementation
**Purpose**: Wire up the Org Intelligence Graph with real team activity, notifications, and status data

---

## 🎯 Current State Analysis

### What Exists Now

#### 1. **Daily Brief Page** (`/src/pages/DailyBrief.jsx`)

**Tab Structure**:
- **Personal Tab**: Individual user timeline (already working with real data)
- **Org Tab**: Team/organization dashboard ← **Currently using mock data**
- **Outbound Tab**: Outbound brief

**Key Code**:
```jsx
// Line 953 - Renders OrgIntelligenceGraph component
{activeTab === "org" && <OrgIntelligenceGraph />}
```

---

#### 2. **OrgIntelligenceGraph Component** (`/src/components/brief/OrgIntelligenceGraph.jsx`)

**Current Implementation**: 100% **Mock Data**

**Mock Data Structure**:
```javascript
const MOCK_ROOMS = [
  {
    id: "room-backend",
    name: "Backend",
    status: "Healthy",           // ← From activity analysis
    fires: 1,                     // ← Urgent notifications count
    overdue: 2,                   // ← Overdue tasks
    sentiment: "🙂",              // ← Team sentiment from activity
    lastActive: "5m",             // ← Most recent activity timestamp
    summary: "Stabilizing APIs...", // ← AI-generated summary
    risks: ["OAuth refresh failures", "Queue latency spikes"], // ← Detected conflicts
    activity: ["Reviewed canon refresh", "Merged hotfix"], // ← Recent activities
    members: ["Severin", "Sean", "Yug"], // ← Room members
    position: { x: 40, y: 140 },  // ← Graph layout position
  },
  // ... 5 more rooms
];

const MOCK_EDGES = [
  {
    id: "e-backend-frontend",
    source: "room-backend",
    target: "room-frontend",
    strength: 0.7,        // ← Collaboration intensity (from shared work)
    overlap: 3            // ← Number of shared activities/files
  },
  // ... 6 more edges
];
```

**Visual Features**:
- ReactFlow graph with draggable nodes
- Color-coded by status (Healthy=green, Strained=yellow, Critical=red)
- Edge thickness = collaboration strength
- Hoverable nodes with tooltips
- Selectable nodes with detailed drawer

**Drawer Details Panel**:
- Room summary (AI-generated)
- Key risks (from conflict detection)
- Recent activity (from activity history)
- Top members (from room memberships)
- Related rooms (connected nodes)

---

### What Data We Have Available

From the **backend notification system** and **activity history**:

#### ✅ Already Exists:
1. **`user_actions` table** - All team activity with embeddings
2. **`notifications` table** - Conflict/collaboration notifications
3. **`rooms` table** - Team/room structure
4. **`room_memberships` table** - Who's in which room
5. **Activity embeddings** - For semantic similarity
6. **Conflict detection** - File conflicts, semantic overlaps
7. **Activity Manager** - Generates AI summaries

#### 🔌 Endpoints Available:
```
GET  /api/rooms                    # List all rooms
GET  /api/rooms/{id}               # Room details
GET  /api/rooms/{id}/members       # Room members
GET  /api/activity/history         # User/team activity
GET  /api/notifications            # Notifications (conflicts)
GET  /api/team/activity (?)        # Team-wide activity (needs verification)
```

---

## 🏗️ Integration Architecture

### Data Flow

```
Backend (PostgreSQL + pgvector)
    ↓
Activity Worker (15min polling)
    ↓
Detects conflicts/collaboration
    ↓
Creates notifications + embeddings
    ↓
Frontend API calls
    ↓
OrgIntelligenceGraph Component
    ↓
ReactFlow Visualization
```

---

## 📊 Data Mapping Strategy

### How to Build Each Field

#### **1. Room Status** (`status: "Healthy" | "Strained" | "Critical"`)

**Logic**:
```javascript
function calculateRoomStatus(room, notifications, activities) {
  const urgentCount = notifications.filter(n =>
    n.room_id === room.id && n.severity === 'urgent'
  ).length;

  const activityRecent = activities.filter(a =>
    a.room_id === room.id &&
    (Date.now() - new Date(a.timestamp)) < 3600000 // 1 hour
  ).length;

  // Critical: 5+ urgent notifications OR no activity in 24h
  if (urgentCount >= 5 || activityRecent === 0) return "Critical";

  // Strained: 2-4 urgent notifications
  if (urgentCount >= 2) return "Strained";

  // Healthy: <2 urgent, recent activity
  return "Healthy";
}
```

**Data Source**:
- `GET /api/notifications?room_id={id}&severity=urgent`
- `GET /api/activity/history?room_id={id}&days=1`

---

#### **2. Fires Count** (`fires: number`)

**Mapping**: Number of **urgent** notifications for this room

**Query**:
```javascript
const fires = notifications.filter(n =>
  n.room_id === room.id &&
  n.severity === 'urgent' &&
  !n.is_read
).length;
```

**Data Source**: `GET /api/notifications?room_id={id}&severity=urgent&unread_only=true`

---

#### **3. Overdue Count** (`overdue: number`)

**Mapping**: Number of tasks past their deadline

**Backend Needed**:
```python
# Add endpoint to count overdue tasks
GET /api/rooms/{room_id}/tasks/overdue
```

**Or from activities**:
```javascript
// Parse activity summaries for overdue mentions
const overdue = activities.filter(a =>
  a.summary && /overdue|late|missed deadline/i.test(a.summary)
).length;
```

---

#### **4. Sentiment** (`sentiment: string emoji`)

**Mapping**: Derived from activity tone analysis

**Options**:
1. **Simple**: Count negative keywords
   ```javascript
   function getSentiment(activities) {
     const recent = activities.slice(0, 10).join(' ');
     const negativeWords = /critical|urgent|failure|blocked|delayed/gi;
     const positiveWords = /completed|resolved|success|launched/gi;

     const negCount = (recent.match(negativeWords) || []).length;
     const posCount = (recent.match(positiveWords) || []).length;

     if (negCount > posCount * 2) return "😬"; // Stressed
     if (posCount > negCount) return "😊";     // Happy
     return "🙂";                              // Neutral
   }
   ```

2. **Advanced**: Use OpenAI to analyze activity tone
   ```python
   # Backend endpoint
   GET /api/rooms/{room_id}/sentiment
   # Returns: { sentiment: "positive", emoji: "😊", score: 0.75 }
   ```

---

#### **5. Last Active** (`lastActive: string`)

**Mapping**: Most recent activity timestamp

**Query**:
```javascript
const lastActivity = activities
  .filter(a => a.room_id === room.id)
  .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0];

const lastActive = formatRelativeTime(lastActivity.timestamp);
// "5m", "2h", "3d"
```

**Data Source**: `GET /api/activity/history?room_id={id}&limit=1`

---

#### **6. Summary** (`summary: string`)

**Mapping**: AI-generated room status summary

**Backend Approach**:
```python
# Endpoint to generate room summary
GET /api/rooms/{room_id}/summary

# Logic:
# 1. Get last 20 activities for room
# 2. Combine activity summaries
# 3. Send to GPT-4o-mini: "Summarize this team's work in 1 sentence"
# 4. Cache for 15 minutes
```

**Frontend Fallback**:
```javascript
// Use most recent status-change activity summary
const latestSummary = activities
  .filter(a => a.is_status_change && a.room_id === room.id)
  .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0]
  ?.activity_summary || "No recent activity";
```

---

#### **7. Risks** (`risks: string[]`)

**Mapping**: Extracted from urgent notifications

**Query**:
```javascript
const risks = notifications
  .filter(n => n.room_id === room.id && n.severity === 'urgent')
  .map(n => n.title || n.message)
  .slice(0, 5); // Top 5 risks

// Example:
// ["OAuth refresh failures", "Queue latency spikes", "API rate limit approaching"]
```

**Data Source**: `GET /api/notifications?room_id={id}&severity=urgent&limit=5`

---

#### **8. Activity List** (`activity: string[]`)

**Mapping**: Recent activity summaries (last 5)

**Query**:
```javascript
const activity = activities
  .filter(a => a.room_id === room.id && a.is_status_change)
  .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
  .slice(0, 5)
  .map(a => a.activity_summary);

// Example:
// ["Reviewed canon refresh", "Merged hotfix for chat reload", "Deployed to staging"]
```

**Data Source**: `GET /api/activity/history?room_id={id}&limit=5`

---

#### **9. Members** (`members: string[]`)

**Mapping**: Room membership list

**Query**:
```javascript
// From backend endpoint
const members = await fetch(`/api/rooms/${roomId}/members`);
const memberNames = members.map(m => m.name || m.email.split('@')[0]);
```

**Data Source**: `GET /api/rooms/{id}/members`

---

#### **10. Position** (`position: {x, y}`)

**Approaches**:

**Option A**: Auto-layout using force-directed algorithm
```javascript
import { useNodesState } from '@xyflow/react';

// Let ReactFlow auto-position based on connections
const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);

useEffect(() => {
  // Apply force-directed layout
  const layoutedNodes = getLayoutedNodes(nodes, edges);
  setNodes(layoutedNodes);
}, []);
```

**Option B**: Store positions in database
```python
# rooms table
ALTER TABLE rooms ADD COLUMN graph_position_x INT DEFAULT 100;
ALTER TABLE rooms ADD COLUMN graph_position_y INT DEFAULT 100;
```

**Option C**: Calculate from room hierarchy
```javascript
// Position based on room creation order + spacing
const positions = rooms.map((room, idx) => ({
  ...room,
  position: {
    x: (idx % 3) * 300 + 100,
    y: Math.floor(idx / 3) * 200 + 100
  }
}));
```

---

#### **11. Edges (Connections)** (`edges: Array`)

**Mapping**: Rooms are connected if they share:
- Same files being edited
- Cross-room notifications
- Shared members
- Semantic activity overlap

**Query**:
```javascript
function calculateEdges(rooms, activities, notifications) {
  const edges = [];

  for (let i = 0; i < rooms.length; i++) {
    for (let j = i + 1; j < rooms.length; j++) {
      const roomA = rooms[i];
      const roomB = rooms[j];

      // Shared members
      const sharedMembers = roomA.members.filter(m =>
        roomB.members.includes(m)
      ).length;

      // Cross-room notifications
      const crossNotifs = notifications.filter(n =>
        (n.related_rooms || []).includes(roomA.id) &&
        (n.related_rooms || []).includes(roomB.id)
      ).length;

      // Shared files (from VSCode activities)
      const filesA = getFilesFromActivities(roomA.id, activities);
      const filesB = getFilesFromActivities(roomB.id, activities);
      const sharedFiles = filesA.filter(f => filesB.includes(f)).length;

      const overlap = sharedMembers + crossNotifs + sharedFiles;

      if (overlap > 0) {
        edges.push({
          id: `e-${roomA.id}-${roomB.id}`,
          source: roomA.id,
          target: roomB.id,
          strength: Math.min(overlap / 10, 1), // Normalize to 0-1
          overlap
        });
      }
    }
  }

  return edges;
}
```

---

## 🔌 Required Backend Endpoints

### Existing (Verified):
- ✅ `GET /api/rooms` - List rooms
- ✅ `GET /api/activity/history` - Activity data
- ✅ `GET /api/notifications` - Notifications

### Needed (To Build):
1. **`GET /api/rooms/{id}/summary`** - AI-generated room summary
2. **`GET /api/rooms/{id}/stats`** - Room statistics
   ```json
   {
     "urgent_count": 3,
     "overdue_count": 2,
     "last_active": "2026-01-01T12:00:00Z",
     "recent_activities": [...],
     "recent_risks": [...]
   }
   ```
3. **`GET /api/rooms/{id}/sentiment`** - Team sentiment analysis
4. **`GET /api/org/graph-data`** - Complete graph data for all rooms
   ```json
   {
     "rooms": [...],
     "edges": [...],
     "last_updated": "2026-01-01T12:00:00Z"
   }
   ```

---

## 📝 Implementation Plan

### Phase 1: Basic Data Fetching (2-3 hours)

**Tasks**:
1. Create `orgApi.js` with endpoint calls
2. Replace `MOCK_ROOMS` with API data
3. Calculate basic metrics (fires, overdue, lastActive)
4. Wire up real room memberships

**Files to Edit**:
- `/src/api/orgApi.js` (create new)
- `/src/components/brief/OrgIntelligenceGraph.jsx`

---

### Phase 2: Smart Calculations (1-2 hours)

**Tasks**:
1. Implement `calculateRoomStatus()` logic
2. Implement `getSentiment()` analysis
3. Build edge calculation (shared members/files)
4. Add caching to avoid re-calculating

**Files to Edit**:
- `/src/components/brief/OrgIntelligenceGraph.jsx`
- `/src/utils/orgCalculations.js` (create new)

---

### Phase 3: Backend Summary Endpoints (Backend work)

**Tasks**:
1. `GET /api/rooms/{id}/summary` - AI summary generation
2. `GET /api/rooms/{id}/stats` - Aggregate statistics
3. `GET /api/org/graph-data` - Optimized single endpoint

**Backend Files**:
- `main.py` (add new endpoints)
- `services/org_intelligence.py` (create new service)

---

### Phase 4: Polish & Real-time Updates (1-2 hours)

**Tasks**:
1. Add auto-refresh every 30 seconds
2. Implement WebSocket for live updates (optional)
3. Add loading states during data fetch
4. Add error handling & fallbacks

**Files to Edit**:
- `/src/components/brief/OrgIntelligenceGraph.jsx`

---

## 🧪 Testing Strategy

### Manual Testing:
1. Create test rooms with different activity levels
2. Generate notifications for rooms
3. Add VSCode activities to create edges
4. Verify status calculations match expectations

### Automated Testing:
```javascript
// Example test
describe('Room Status Calculation', () => {
  it('should mark room as Critical with 5+ urgent notifications', () => {
    const room = { id: 'test-room' };
    const notifications = Array(6).fill({ severity: 'urgent', room_id: 'test-room' });

    expect(calculateRoomStatus(room, notifications, [])).toBe('Critical');
  });
});
```

---

## 📊 Data Refresh Strategy

**Options**:

1. **Polling** (Simple)
   ```javascript
   useEffect(() => {
     fetchOrgData();
     const interval = setInterval(fetchOrgData, 30000); // 30s
     return () => clearInterval(interval);
   }, []);
   ```

2. **WebSocket** (Real-time)
   ```javascript
   useEffect(() => {
     const ws = new WebSocket('ws://api/org-updates');
     ws.onmessage = (event) => {
       const update = JSON.parse(event.data);
       updateRoom(update.room_id, update.data);
     };
   }, []);
   ```

3. **Hybrid** (Recommended)
   - Poll every 30s for full refresh
   - WebSocket for instant urgent notification updates

---

## 🚀 Next Steps (When Rate Limits Reset)

1. **Create `orgApi.js`** - API client functions
2. **Update `OrgIntelligenceGraph.jsx`** - Replace mock data
3. **Implement calculation utilities** - Status, sentiment, edges
4. **Coordinate with backend** - Build missing endpoints
5. **Add real-time updates** - Polling or WebSocket
6. **Test with real data** - Verify calculations

---

## 💡 Key Design Decisions

### Why This Approach?

**Pros**:
- ✅ Leverages existing activity/notification infrastructure
- ✅ No new database tables needed
- ✅ Real-time data from actual team work
- ✅ Scales with team size

**Cons**:
- ⚠️ Requires aggregation logic (can cache)
- ⚠️ Initial load may be slow (optimize with dedicated endpoint)

### Performance Optimizations:
1. **Cache room stats** - Refresh every 15 min (same as notification worker)
2. **Dedicated endpoint** - `GET /api/org/graph-data` returns pre-calculated data
3. **Frontend caching** - Use React Query or SWR for automatic caching

---

## 📖 Summary

**Current Status**:
- ✅ Graph UI is built and working (with mock data)
- ✅ Backend has all necessary data (activities, notifications, rooms)
- ⚠️ Need to wire them together

**What to Build**:
1. Frontend: `orgApi.js` + calculation utilities
2. Backend: Summary/stats endpoints
3. Integration: Replace mock data with real API calls

**Timeline**: 4-6 hours of frontend work + 2-3 hours backend endpoints

**Ready to implement when rate limits reset!** 🚀
