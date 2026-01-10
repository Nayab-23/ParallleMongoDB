# Canon Frontend Analysis Report

**Generated:** 2025-12-22
**Status:** Complete Analysis of Daily Brief / Canon System

---

## Executive Summary

The frontend canon/daily brief system is a **display-only layer** that expects the backend to handle all business logic including:
- Date filtering (past vs. future items)
- Completion filtering
- Timeline categorization (1d/7d/28d)
- Priority assignment (critical/high/normal)

### Critical Finding: NO FRONTEND DATE FILTERING

**The frontend does NOT filter old/past items.** If old events appear in the Daily Brief, it's because:
1. The backend is sending them in the `timeline` response
2. The frontend displays whatever the backend provides
3. There is no client-side date comparison or filtering logic

---

## 1. File Inventory

### Core Components

| File | Lines | Purpose | Key Functions |
|------|-------|---------|---------------|
| `src/pages/Intelligence.jsx` | 658 | Main container for Canon system | `loadCanon()`, `performCanonRefresh()`, `handleRefresh()` |
| `src/pages/DailyBrief.jsx` | 675 | Daily Brief display page | `handleComplete()`, `handleDelete()`, filtering logic |
| `src/components/brief/Timeline.jsx` | 173 | Timeline section renderer | `TimelineSection`, `TaskCard`, `formatDeadline()` |
| `src/components/brief/PersonalBrief.jsx` | 134 | Personal brief grid display | Section rendering (Priorities, Emails, Meetings, etc.) |
| `src/components/brief/OrgBrief.jsx` | 40 | Organizational brief view | Org sections (Risks, Statuses, Bottlenecks) |
| `src/components/brief/OutboundBrief.jsx` | 40 | Outbound/client view | Client sections (At-risk, Opportunities, Sentiment) |
| `src/components/brief/CompletedSidebar.jsx` | 30 | Completed items sidebar | Undo functionality |
| `src/components/brief/Recommendations.jsx` | 70 | AI recommendations UI | **EXISTS BUT NOT RENDERED** |

### API/Config

| File | Lines | Purpose |
|------|-------|---------|
| `src/lib/tasksApi.js` | 514 | API helper functions (no canon-specific calls) |
| `src/config.js` | 42 | Exports `API_BASE_URL` |

---

## 2. API Integration

### GET /api/canon

**File:** `Intelligence.jsx` Lines 278-416
**Triggered by:**
- Initial page load (Line 422-424)
- After `POST /api/canon/refresh` completes
- After `POST /api/canon/generate` (first-time users)

**Implementation:**
```javascript
const loadCanon = useCallback(async ({ skipEmptyCheck = false } = {}) => {
  setLoadingBrief(true);
  try {
    const response = await fetch(`${API_BASE_URL}/api/canon`, {
      credentials: "include",
    });

    const raw = await response.text();
    const data = raw ? JSON.parse(raw) : null;

    // OAuth error handling
    if (!response.ok) {
      if (response.status === 401 && data?.error === "oauth_refresh_failed") {
        setOAuthError({
          provider: data?.provider || "google",
          message: data?.message || "Please reconnect your accounts.",
          error: data?.error,
        });
        return;
      }
    }

    // First-time user detection
    if (data.exists === false) {
      await generateInitialCanon();
      return;
    }

    // Empty canon detection - auto-triggers refresh
    const timeline = data.timeline || {};
    const priorities = Array.isArray(data.priorities) ? data.priorities : [];
    const isEmpty = !skipEmptyCheck &&
      Object.values(timeline).every((timeframe) => {
        if (!timeframe || typeof timeframe !== "object") return true;
        return Object.values(timeframe).every((section) => {
          if (!Array.isArray(section)) return true;
          return section.length === 0;
        });
      });

    if (isEmpty && priorities.length === 0) {
      // Auto-refresh if canon is empty
      await performCanonRefresh();
      await loadCanonRef.current({ skipEmptyCheck: true });
      return;
    }

    // Success - update state
    setCanonicalPlan({ timeline, priorities });
    setRecommendations(data.recommendations || []);
    setLastCanonSync(data.last_sync || data.last_ai_sync || null);
    setLoadedCanon(true);
    setOAuthError(null);
  } catch (error) {
    console.error("[Canon] Failed to load:", error);
  } finally {
    setLoadingBrief(false);
  }
}, [API_BASE_URL, generateInitialCanon, performCanonRefresh]);
```

**Response Structure:**
```json
{
  "exists": true,
  "timeline": {
    "1d": {
      "critical": [...],
      "high_priority": [...],
      "normal": [...]
    },
    "7d": { ... },
    "28d": { ... }
  },
  "priorities": [...],
  "recommendations": [],
  "last_sync": "2025-12-23T01:28:08+00:00"
}
```

**What happens with response:**
1. Stored in `canonicalPlan` state
2. Passed to `DailyBrief` as `externalPersonalData` prop
3. Filtered for dismissed items (NOT filtered by date)
4. Rendered in Timeline component

---

### POST /api/canon/refresh

**File:** `Intelligence.jsx` Lines 252-276, 426-482
**Triggered by:**
- User clicks "Refresh" button
- Auto-refresh timer (every N minutes)
- Empty canon detection

**Implementation:**
```javascript
const performCanonRefresh = useCallback(async () => {
  const response = await fetch(`${API_BASE_URL}/api/canon/refresh`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });

  const raw = await response.text();
  let data = null;
  try {
    data = raw ? JSON.parse(raw) : null;
  } catch (err) {
    console.error("[Canon] JSON parse error:", err);
  }

  return { response, data, raw };
}, [API_BASE_URL]);

// Manual/Auto refresh handler
const handleRefresh = useCallback(async ({ source = "manual" } = {}) => {
  if (refreshingRef.current) return;
  refreshingRef.current = true;
  setRefreshing(true);

  try {
    const { response, data } = await performCanonRefresh();

    if (response.status === 401 && data?.error === "oauth_refresh_failed") {
      setOAuthError({ ... });
      return;
    }

    if (response.ok) {
      setOAuthError(null);
      // CRITICAL: Reloads canon after refresh
      await loadCanonRef.current({ skipEmptyCheck: true });
    }
  } catch (error) {
    console.error("[Canon] Refresh failed:", error);
  } finally {
    setRefreshing(false);
    refreshingRef.current = false;
  }
}, [performCanonRefresh]);
```

**Response Structure:**
```json
{
  "recommendations_added": 0,
  "total_recommendations": 0,
  "last_sync": "2025-12-23T01:28:08+00:00",
  "success": true
}
```

**What happens after refresh:**
1. Backend processes Gmail/Calendar
2. AI generates new timeline
3. Items auto-added to `approved_timeline` (NOT recommendations)
4. Frontend calls `GET /api/canon` again
5. UI updates with new timeline data

---

### POST /api/brief/items/complete

**File:** `DailyBrief.jsx` Lines 212-243

```javascript
const handleComplete = async (item) => {
  setCompletingItem(item);
  await new Promise((resolve) => setTimeout(resolve, 600)); // Animation

  await fetch(`${API_BASE_URL}/api/brief/items/complete`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      signature: item.signature || item.source_id || item.id || item.title,
      title: item.title,
      source_id: item.source_id,
      source_type: item.source_type,
    }),
  });

  setCompletedItems((prev) => [item, ...prev]);
  setDismissedItems((prev) => [...prev, item]);

  // Reload canon after 300ms
  setTimeout(() => {
    if (externalReloadCanon) {
      externalReloadCanon();
    } else {
      loadBrief();
    }
  }, 300);
};
```

---

### POST /api/brief/items/delete

**File:** `DailyBrief.jsx` Lines 245-271

```javascript
const handleDelete = (item) => {
  setDismissedItems((prev) => [...prev, item]);

  const signature = item.signature || item.source_id || item.id || item.title;
  await fetch(`${API_BASE_URL}/api/brief/items/delete`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ signature }),
  });

  setTimeout(() => {
    if (externalReloadCanon) {
      externalReloadCanon();
    } else {
      loadBrief();
    }
  }, 300);
};
```

---

## 3. Timeline Display Logic

### Component Hierarchy

```
Intelligence.jsx
└── DailyBrief.jsx
    └── Timeline.jsx
        └── TimelineSection (3 instances)
            └── TaskCard (multiple per section)
```

### Timeline.jsx Rendering

**File:** `Timeline.jsx` Lines 40-66

```javascript
export default function Timeline({ data = {}, items, onComplete, onDelete, onRefresh }) {
  const timelineData = items || data || {};

  const timeframes = [
    {
      key: "today",
      fallbacks: ["1d"],
      title: "Daily Goals",
      icon: "",
      empty: "No critical tasks today 🎉",
    },
    {
      key: "this_week",
      fallbacks: ["7d"],
      title: "Weekly Focus",
      icon: "",
      empty: "No tasks scheduled this week",
    },
    {
      key: "this_month",
      fallbacks: ["28d"],
      title: "Monthly Objectives",
      icon: "",
      empty: "No monthly goals set",
    },
  ];

  return (
    <div className="timeline-container">
      {timeframes.map((tf) => {
        const section = timelineData?.[tf.key] ||
                        (tf.fallbacks || []).reduce((acc, alt) =>
                          acc || timelineData?.[alt], null) || {};
        const count = getTotalTaskCount(section);

        return (
          <TimelineSection
            key={tf.key}
            title={tf.title}
            icon={tf.icon}
            count={count}
            items={section}
            emptyMessage={tf.empty}
            onComplete={onComplete}
            onDelete={onDelete}
            onRefresh={tf.key === "today" ? onRefresh : null}
          />
        );
      })}
    </div>
  );
}
```

**Key insights:**
- Uses flexible key mapping: `"today"` → fallback to `"1d"` if not found
- No date filtering - displays whatever is in the section
- Empty state handling only (cosmetic)

---

### Item Structure

**File:** `Timeline.jsx` Lines 121-156

```javascript
// Timeline item object structure:
{
  title: string,              // Required - main display text
  detail: string,             // Optional - description
  description: string,        // Alternative to detail
  deadline: string,           // ISO timestamp - formatted for display
  date: string,               // Alternative to deadline
  signature: string,          // Unique ID for API calls
  source_id: string,          // Alternative ID
  source_type: string,        // "email", "calendar", etc.
  id: string,                 // Fallback ID
  priority: string,           // Not used (inferred from section)
}
```

### TaskCard Component

**File:** `Timeline.jsx` Lines 121-156

```javascript
function TaskCard({ task = {}, priority = "normal", onComplete, onDelete }) {
  const signature = task.signature || task.id || task.title;
  const priorityBorder = {
    critical: "border-red-500",
    high: "border-yellow-500",
    normal: "border-gray-300",
  }[priority];
  const deadlineText = formatDeadline(task.deadline || task.date);

  return (
    <div className={`task-card ${priorityBorder}`}>
      <div className="task-top">
        <div className="task-titles">
          <h3>{task.title || "Task"}</h3>
          {task.detail || task.description ?
            <p>{task.detail || task.description}</p> : null}
          {deadlineText && (
            <span className="task-deadline">
              <span role="img" aria-label="deadline">⏰</span> {deadlineText}
            </span>
          )}
        </div>
        <div className="task-actions">
          <button onClick={() => onComplete({ ...task, signature })} title="Complete">
            ✓
          </button>
          <button onClick={() => onDelete({ ...task, signature })} title="Delete">
            ✕
          </button>
        </div>
      </div>
    </div>
  );
}
```

### Priority Levels

**File:** `Timeline.jsx` Lines 102-114

Items are rendered in this order within each timeframe:
1. **critical** → Red border
2. **high** → Yellow border
3. **normal** → Gray border

```javascript
["critical", "high", "normal"].map(
  (priority) =>
    Array.isArray(items?.[priority]) &&
    items[priority].map((task) => (
      <TaskCard
        key={task.signature || task.id || task.title}
        task={task}
        priority={priority}
        onComplete={onComplete}
        onDelete={onDelete}
      />
    ))
)
```

---

## 4. Filtering Logic

### What IS Filtered (Client-Side)

**File:** `DailyBrief.jsx` Lines 354-397

```javascript
// Only dismissed/completed items are filtered
const isDismissed = (item) => dismissedItems.some((d) => isSameItem(d, item));
const filterList = (list) => (Array.isArray(list) ? list.filter((i) => !isDismissed(i)) : []);

const filteredTimeline = useMemo(() => {
  const tl = personalData?.timeline || {};
  const keys = ["1d", "7d", "28d"];
  const out = {};
  keys.forEach((k) => {
    const section = tl[k];
    if (!section) return;
    const filtered = {};
    Object.entries(section).forEach(([key, val]) => {
      filtered[key] = Array.isArray(val) ? filterList(val) : val;
    });
    out[k] = filtered;
  });
  return out;
}, [personalData, dismissedItems]);
```

**Item comparison logic:**
```javascript
const isSameItem = (a, b) => {
  if (!a || !b) return false;
  if (a.source_id && b.source_id && a.source_id === b.source_id) return true;
  return a.title === b.title && a.source_type === b.source_type;
};
```

---

### What IS NOT Filtered (NO Date Filtering)

**File:** `Timeline.jsx` Lines 164-173

```javascript
// This function ONLY formats dates for display - DOES NOT FILTER
function formatDeadline(deadline) {
  if (!deadline) return "";
  const date = new Date(deadline);
  const now = new Date();
  const diffHours = (date - now) / (1000 * 60 * 60);

  if (diffHours < 0) return date.toLocaleString();  // ← Past items still SHOWN
  if (diffHours < 1) return `Due in ${Math.round(diffHours * 60)} minutes`;
  if (diffHours < 24) return `Due in ${Math.round(diffHours)} hours`;
  return date.toLocaleDateString();
}
```

**Critical Analysis:**

🔴 **NO DATE-BASED FILTERING EXISTS**

The frontend does NOT:
- Filter items by deadline/date
- Check if items are past due
- Remove old items from display
- Compare current date to item dates for filtering

If `diffHours < 0` (item is past deadline), the function returns `date.toLocaleString()` but **still displays the item**.

**The backend is 100% responsible for:**
- Removing past items from timeline
- Categorizing into 1d/7d/28d buckets
- Filtering by deadline proximity

---

### Section Mapping

**File:** `DailyBrief.jsx` Lines 399-416

```javascript
// Maps backend sections to frontend priority buckets
const heroTimeline = useMemo(() => {
  const tl = filteredPersonal?.timeline || {};
  const mapSection = (section) => ({
    critical: section?.critical || section?.high_priority || [],
    high: section?.high_priority || section?.milestones || [],
    normal:
      section?.normal ||
      section?.low ||
      section?.upcoming ||
      section?.goals ||
      [],
  });
  return {
    today: mapSection(tl["1d"] || tl.today || {}),
    this_week: mapSection(tl["7d"] || tl.this_week || {}),
    this_month: mapSection(tl["28d"] || tl.this_month || {}),
  };
}, [filteredPersonal?.timeline]);
```

**Flexible key mapping:**
- Backend sends `"1d"` → Frontend displays as "Daily Goals" (today)
- Backend sends `"7d"` → Frontend displays as "Weekly Focus" (this_week)
- Backend sends `"28d"` → Frontend displays as "Monthly Objectives" (this_month)

---

## 5. Recommendation System

### Status: Built but Disabled

**Component exists:** `src/components/brief/Recommendations.jsx` (70 lines)

```javascript
export default function Recommendations({
  recommendations = [],
  onAccept = () => {},
  onDismiss = () => {},
  processingIndex = null,
  showEmptyState = false,
}) {
  return (
    <div className="recommendations-panel">
      {recommendations.map((rec, index) => (
        <div key={index} className="rec-card">
          <h3>{rec.title}</h3>
          <p>{rec.detail}</p>
          <div className="rec-actions">
            <button className="rec-btn accept" onClick={() => onAccept(index)}>
              ✓ Accept
            </button>
            <button className="rec-btn dismiss" onClick={() => onDismiss(index)}>
              ✕ Dismiss
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
```

### Current Implementation

**Backend sends recommendations:**
```javascript
// Intelligence.jsx Line 406
setRecommendations(data.recommendations || []);
```

**But UI never renders them:**
```javascript
// DailyBrief.jsx - NO import of Recommendations component
// Intelligence.jsx - NO import of Recommendations component
// PersonalBrief.jsx - NO import of Recommendations component
```

**No API endpoints for recommendations:**
- ❌ No calls to `/api/recommendations/accept`
- ❌ No calls to `/api/recommendations/dismiss`
- ❌ No recommendation-specific endpoints

**Conclusion:**
The backend likely returns `recommendations: []` (empty array) in the canon response. Even if it returned recommendations, the frontend UI doesn't display them. The component is dead code.

---

## 6. State Management

### Architecture: React useState (No Redux/Context)

**File:** `Intelligence.jsx` Lines 8-28

```javascript
// Main canon state
const [canonicalPlan, setCanonicalPlan] = useState(null);
const [recommendations, setRecommendations] = useState([]);
const [loadingBrief, setLoadingBrief] = useState(true);
const [refreshing, setRefreshing] = useState(false);
const [loadedCanon, setLoadedCanon] = useState(false);
const [lastCanonSync, setLastCanonSync] = useState(null);
const [oAuthError, setOAuthError] = useState(null);
```

**File:** `DailyBrief.jsx` Lines 43-62

```javascript
// Local component state
const [completedItems, setCompletedItems] = useState([]);
const [dismissedItems, setDismissedItems] = useState([]);
const [completingItem, setCompletingItem] = useState(null);
const [canonicalPlan, setCanonicalPlan] = useState(null);
const [lastAiSync, setLastAiSync] = useState(null);
```

### Props Flow

**Intelligence.jsx → DailyBrief.jsx:**
```javascript
<DailyBrief
  externalPersonalData={
    loadedCanon
      ? {
          timeline: canonicalPlan?.timeline || {},
          priorities: canonicalPlan?.priorities || [],
        }
      : null
  }
  externalRecommendations={loadedCanon ? recommendations : null}
  externalLoading={loadingBrief}
  externalOnRefresh={handleRefresh}
  externalRefreshing={refreshing}
  externalReloadCanon={loadCanon}
  externalRefreshInterval={refreshInterval}
  externalLastSync={lastCanonSync}
/>
```

**DailyBrief.jsx → Timeline.jsx:**
```javascript
<Timeline
  items={heroTimeline}
  onComplete={handleComplete}
  onDelete={handleDelete}
  onRefresh={handleTimelineRefresh}
/>
```

### localStorage Usage

**Keys:**
- `"assistantChatId"` - Personal assistant chat ID
- `"assistantRoomId"` - Personal assistant room ID
- `"canonOAuthError"` - OAuth error state persistence

**No canon data caching:**
- Canon is NOT stored in localStorage
- Always fetched fresh from API on page load
- Completed/dismissed items are session-only (lost on refresh)

### State Update Triggers

1. **Initial load** → `useEffect(() => { loadCanon(); }, []);`
2. **Manual refresh** → User clicks button → `handleRefresh()`
3. **Auto-refresh** → Timer → `handleRefresh({ source: "auto" })`
4. **After completion/deletion** → 300ms delay → `externalReloadCanon()`
5. **Empty canon** → Auto-triggers refresh → `performCanonRefresh()`

---

## 7. User Flows

### Flow 1: Daily Brief Initial Load

```
1. User navigates to Intelligence page
   ↓
2. Intelligence.jsx mounts
   ↓
3. useEffect triggers: loadCanon()
   ↓
4. GET /api/canon
   ↓
5. Response handling:

   IF exists === false (first-time user):
      ↓
      POST /api/canon/generate
      ↓
      Set canonicalPlan, recommendations
      ↓
      Render DailyBrief with data

   ELSE IF timeline is empty:
      ↓
      Show "Timeline is empty. Refreshing..." banner
      ↓
      POST /api/canon/refresh
      ↓
      GET /api/canon (with skipEmptyCheck=true)
      ↓
      Set canonicalPlan
      ↓
      Render DailyBrief

   ELSE (normal case):
      ↓
      setCanonicalPlan({ timeline, priorities })
      ↓
      setRecommendations(data.recommendations || [])
      ↓
      setLastCanonSync(data.last_sync)
      ↓
      Render DailyBrief

6. DailyBrief.jsx receives externalPersonalData prop
   ↓
7. useMemo calculates:
   - filteredTimeline (removes dismissed items)
   - heroTimeline (maps to critical/high/normal buckets)
   ↓
8. Timeline.jsx renders 3 sections:
   - Daily Goals (1d/today)
   - Weekly Focus (7d/this_week)
   - Monthly Objectives (28d/this_month)
   ↓
9. TaskCard components render items
```

### Flow 2: Manual Refresh

```
1. User clicks "Refresh" button
   ↓
2. externalOnRefresh() → Intelligence.handleRefresh()
   ↓
3. Check: if (refreshingRef.current) → Skip (prevent double-refresh)
   ↓
4. setRefreshing(true) → Shows spinner in UI
   ↓
5. POST /api/canon/refresh
   ↓
6. Response handling:

   IF status === 401 (OAuth error):
      ↓
      Set oAuthError banner
      ↓
      Store in localStorage
      ↓
      Stop (don't reload)

   ELSE IF response.ok:
      ↓
      Clear oAuthError
      ↓
      GET /api/canon (with skipEmptyCheck=true)
      ↓
      Update canonicalPlan state
      ↓
      UI re-renders with new data

7. setRefreshing(false) → Hide spinner
   ↓
8. Timeline updates with fresh items
```

### Flow 3: Auto-Refresh

```
1. Intelligence.jsx loads user preferences
   ↓
2. GET /api/me → extract canon_refresh_interval_minutes
   ↓
3. setRefreshInterval(interval || 1)
   ↓
4. useEffect creates interval timer
   ↓
5. Every N minutes:
   ↓
6. handleRefresh({ source: "auto" })
   ↓
7. Same flow as manual refresh
   ↓
8. Console logs: "[Canon] Auto-refresh triggered"
   ↓
9. UI updates silently in background
```

**Special cases:**
- If `refreshInterval === 0` → Auto-refresh disabled
- User activity tracking exists (lines 418-441) but unused

### Flow 4: Completing a Task

```
1. User clicks "✓" button on task card
   ↓
2. TaskCard.onClick → onComplete(task)
   ↓
3. DailyBrief.handleComplete(item)
   ↓
4. setCompletingItem(item) → Triggers animation
   ↓
5. Wait 600ms (animation duration)
   ↓
6. POST /api/brief/items/complete
   Body: {
     signature: item.signature || item.source_id || item.id,
     title: item.title,
     source_id: item.source_id,
     source_type: item.source_type,
   }
   ↓
7. Update local state:
   - Add to completedItems (for sidebar)
   - Add to dismissedItems (for filtering)
   ↓
8. Wait 300ms
   ↓
9. externalReloadCanon() → Intelligence.loadCanon()
   ↓
10. GET /api/canon
   ↓
11. Timeline re-renders WITHOUT completed item
   ↓
12. Item appears in CompletedSidebar
   ↓
13. User can click "Undo" to restore
```

---

## 8. Issues Identified

### Issue #1: No Frontend Date Filtering

**Location:** `Timeline.jsx:164-173`

**Problem:**
```javascript
function formatDeadline(deadline) {
  if (!deadline) return "";
  const date = new Date(deadline);
  const now = new Date();
  const diffHours = (date - now) / (1000 * 60 * 60);

  if (diffHours < 0) return date.toLocaleString();  // ← Still displays!
  // ...
}
```

**Impact:**
- Old/past items are NOT filtered out
- Items with `deadline < now` are still shown with full timestamp
- Backend MUST handle all date filtering

**Root Cause:**
Frontend is designed as a "dumb" display layer. It assumes backend sends only relevant items.

**If old items are appearing, the backend is sending them.**

---

### Issue #2: Recommendations System Unused

**Location:** `src/components/brief/Recommendations.jsx` (entire file)

**Problem:**
- Component built with full UI
- Backend sends `recommendations` in API response
- Frontend stores recommendations in state
- BUT: Component is never imported or rendered

**Impact:**
- Dead code (70 lines + 2,599 bytes CSS)
- Backend might be wasting resources generating recommendations
- Confusing for developers (is it used or not?)

**Recommendation:**
Since backend now auto-adds items to `approved_timeline` instead of recommendations:
1. Remove `Recommendations.jsx` component
2. Remove `Recommendations.css`
3. Remove `recommendations` state from `Intelligence.jsx`
4. Update backend to stop returning `recommendations` field

---

### Issue #3: Refresh Response Confusing

**Location:** `Intelligence.jsx:426-482`

**Problem:**
After `POST /api/canon/refresh`, backend returns:
```json
{
  "recommendations_added": 0,
  "total_recommendations": 0,
  "last_sync": "..."
}
```

But frontend expects items to be in `timeline`, not `recommendations`.

**Impact:**
- Frontend correctly ignores `recommendations_added`
- But the field names are misleading (implies recommendations are used)
- Could confuse future developers

**Recommendation:**
Update backend to return:
```json
{
  "timeline_updated": true,
  "items_processed": 5,
  "last_sync": "..."
}
```

---

### Issue #4: Aggressive Auto-Refresh

**Location:** `Intelligence.jsx:484-506`

**Problem:**
- Default refresh interval: **1 minute**
- No debouncing or request deduplication
- No smart diffing (full reload every time)
- Runs even when user is inactive

**Impact:**
- High API call frequency (60 calls/hour per user)
- Potential race conditions if manual refresh during auto-refresh
- Could miss updates if backend processing takes >1 minute

**Mitigation Exists:**
- `refreshingRef` prevents overlapping refreshes
- User can configure interval in settings

**Recommendation:**
- Increase default to 5 minutes
- Add smart diffing (compare `last_sync` timestamp before fetching)
- Pause auto-refresh during active user interaction

---

### Issue #5: Completed Items Not Persisted

**Location:** `DailyBrief.jsx:54-56`

**Problem:**
```javascript
const [completedItems, setCompletedItems] = useState([]);
const [dismissedItems, setDismissedItems] = useState([]);
```

These are session-only. On page refresh, completed items sidebar is empty.

**Impact:**
- User loses "Undo" functionality after page refresh
- Can't review what they completed today

**Recommendation:**
Store in localStorage:
```javascript
const [completedItems, setCompletedItems] = useState(() => {
  const saved = localStorage.getItem('completedItems');
  return saved ? JSON.parse(saved) : [];
});

useEffect(() => {
  localStorage.setItem('completedItems', JSON.stringify(completedItems));
}, [completedItems]);
```

---

### Issue #6: No Error Boundary

**Location:** All components

**Problem:**
- No React error boundaries
- If rendering fails, entire app crashes
- User sees blank screen with no context

**Impact:**
- Poor user experience
- Hard to debug production issues

**Recommendation:**
Add error boundary component:
```javascript
<ErrorBoundary fallback={<ErrorState />}>
  <Intelligence />
</ErrorBoundary>
```

---

## 9. Recommendations

### Priority 1: Verify Backend Date Filtering

**Action:** Investigate backend `GET /api/canon` response

**Check if:**
1. Backend filters items by deadline (removes past items)
2. Timeline categorization logic is correct (1d/7d/28d)
3. Completed items are excluded from timeline

**Why:** Frontend relies 100% on backend filtering. If old items appear, backend is the culprit.

---

### Priority 2: Remove Recommendations Feature

**Files to modify:**
1. Delete `src/components/brief/Recommendations.jsx`
2. Delete `src/components/brief/Recommendations.css`
3. Remove from `Intelligence.jsx`:
   - `const [recommendations, setRecommendations] = useState([]);`
   - `setRecommendations(data.recommendations || []);`
   - `externalRecommendations` prop
4. Update backend to stop returning `recommendations` field

**Why:** Feature is built but completely unused. Dead code.

---

### Priority 3: Add Frontend Date Filter (Optional Safety Net)

**File:** `Timeline.jsx`

**Add defensive filtering:**
```javascript
function filterOldItems(items, timeframe) {
  const now = new Date();
  return items.filter((item) => {
    const deadline = item.deadline || item.date;
    if (!deadline) return true; // Keep items without deadline

    const itemDate = new Date(deadline);
    if (timeframe === "today") {
      return itemDate >= now; // Only future items
    }
    return true; // Keep all for weekly/monthly
  });
}
```

**Why:** Defense-in-depth. Even if backend messes up, frontend won't show old items.

---

### Priority 4: Reduce Auto-Refresh Frequency

**File:** `Intelligence.jsx`

**Change default from 1 to 5 minutes:**
```javascript
const [refreshInterval, setRefreshInterval] = useState(5); // Was: 1
```

**Add smart diffing:**
```javascript
const loadCanon = async () => {
  const response = await fetch(`${API_BASE_URL}/api/canon`);
  const data = await response.json();

  // Only update if last_sync changed
  if (data.last_sync !== lastCanonSync) {
    setCanonicalPlan(data);
    setLastCanonSync(data.last_sync);
  }
};
```

**Why:** Reduce API load and improve performance.

---

### Priority 5: Persist Completed Items

**File:** `DailyBrief.jsx`

**Use localStorage:**
```javascript
const [completedItems, setCompletedItems] = useState(() => {
  const saved = localStorage.getItem('completedItemsToday');
  const savedDate = localStorage.getItem('completedItemsDate');
  const today = new Date().toDateString();

  if (savedDate === today && saved) {
    return JSON.parse(saved);
  }
  return []; // Clear if different day
});

useEffect(() => {
  localStorage.setItem('completedItemsToday', JSON.stringify(completedItems));
  localStorage.setItem('completedItemsDate', new Date().toDateString());
}, [completedItems]);
```

**Why:** Better UX - preserve undo functionality across page refreshes.

---

## 10. Answer to Specific Questions

### Q1: Where does "Daily Brief" get its data from?

**Answer:** `GET /api/canon`

**Flow:**
1. `Intelligence.jsx` calls `GET /api/canon`
2. Stores response in `canonicalPlan` state
3. Passes to `DailyBrief` as `externalPersonalData` prop
4. `DailyBrief` renders `Timeline` component
5. `Timeline` displays items

**No deprecated endpoints used.** Only `/api/canon`.

---

### Q2: Are you using `recommendations` field at all?

**Answer:** NO (component exists but never rendered)

**Details:**
- Backend sends `recommendations` array
- Frontend stores in state: `setRecommendations(data.recommendations || [])`
- Passed to `DailyBrief` as `externalRecommendations` prop
- **But:** `Recommendations.jsx` component is never imported
- **Result:** Recommendations are received but never displayed

**Should be removed entirely.**

---

### Q3: How do you determine if an item is "old"?

**Answer:** We DON'T. Backend must handle this.

**Details:**
- Frontend has `formatDeadline()` function (Timeline.jsx:164-173)
- This ONLY formats dates for display
- If `deadline < now`, it shows full timestamp but **still displays the item**
- No filtering logic based on date
- Timeline sections ("1d", "7d", "28d") are labels, not filters

**If old items appear, the backend is sending them.**

---

### Q4: Are there multiple sources of timeline data?

**Answer:** NO, single source: `GET /api/canon`

**Data flow:**
```
GET /api/canon
  ↓
Intelligence.canonicalPlan state
  ↓
DailyBrief.externalPersonalData prop
  ↓
DailyBrief.filteredPersonal (removes dismissed items only)
  ↓
DailyBrief.heroTimeline (maps to critical/high/normal)
  ↓
Timeline component
  ↓
TaskCard components
```

**No caching, no localStorage, no multiple API calls combined.**

---

### Q5: What happens when backend returns empty recommendations?

**Answer:** Nothing (recommendations are unused)

**Details:**
- Backend returns: `{ recommendations: [] }`
- Frontend stores: `setRecommendations([])`
- Passed to DailyBrief but never rendered
- No errors, no fallbacks needed
- Works perfectly fine

**System is designed to work without recommendations.**

---

## 11. Code Quality Assessment

### Strengths ✅

1. **Extensive logging** - Console logs for debugging
2. **Error handling** - Try-catch blocks throughout
3. **OAuth error recovery** - User-friendly reconnect flow
4. **Defensive coding** - Checks for undefined/null everywhere
5. **Flexible data structure** - Fallback keys for backend compatibility

### Weaknesses ❌

1. **No error boundaries** - App crashes on render errors
2. **No TypeScript** - Runtime errors possible
3. **Dead code** - Recommendations component unused
4. **No tests** - Manual testing only
5. **No request deduplication** - Possible race conditions
6. **No caching** - Always fetch fresh (could use stale-while-revalidate)

---

## 12. Summary

### What Works Well

✅ **Backend-centric architecture** - Frontend is a thin display layer
✅ **Auto-refresh system** - Keeps data fresh automatically
✅ **Completion/deletion flow** - Smooth UX with animations
✅ **OAuth error handling** - User-friendly reconnect process
✅ **Flexible data mapping** - Works with multiple backend key formats

### What Needs Fixing

🔴 **No frontend date filtering** - Old items shown if backend sends them
🔴 **Recommendations unused** - Dead code should be removed
🔴 **Aggressive auto-refresh** - 1 minute default is too frequent
🔴 **No completed items persistence** - Lost on page refresh
🔴 **No error boundaries** - Poor crash recovery

### Root Cause of "Old Items Appearing"

**The frontend does NOT filter by date.** If old items appear in the Daily Brief, it's because:

1. **Backend is sending them** in the `timeline` response
2. **Backend date filtering is broken** - Not checking deadlines properly
3. **Backend categorization is wrong** - Old items in "1d" section

**The frontend will display whatever the backend provides.**

---

## Next Steps

1. **Investigate backend** `GET /api/canon` filtering logic
2. **Verify** items in `timeline["1d"]` are actually today's tasks
3. **Check** if backend filters by deadline/date
4. **Remove** recommendations feature entirely
5. **Add** defensive date filtering in frontend (optional safety net)
6. **Reduce** auto-refresh frequency to 5 minutes

---

**END OF REPORT**
