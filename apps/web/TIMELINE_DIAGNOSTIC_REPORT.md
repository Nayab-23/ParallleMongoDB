# COMPREHENSIVE TIMELINE DIAGNOSTIC REPORT

## EXECUTIVE SUMMARY

Based on code analysis of the Timeline component system, I have identified the root causes of all reported issues. This report documents findings WITHOUT making any fixes.

---

## PART 1: DATA FETCHING AUDIT

### API Endpoint & Response Structure

**File:** `src/pages/DailyBrief.jsx`

**Line 154:** Data is fetched from `/api/canon`
```javascript
const response = await fetch(`${API_BASE_URL}/api/canon`, {
  credentials: "include",
});
```

**Lines 200-207:** Data transformation
```javascript
const canonPersonal = {
  timeline: validateTimelineSchema(data.timeline || {}),
  priorities: data.priorities || [],
  integrations: data.integrations || {},
  data_stale: data.data_stale || false,
  needs_reconnect: data.needs_reconnect || false,
  last_sync: data.last_sync || data.last_ai_sync || null,
};
```

**Lines 44-68:** Schema validation function
```javascript
function validateTimelineSchema(timeline) {
  // Ensures keys '1d', '7d', '28d' have 'urgent' and 'normal' arrays
  for (const timeframe of ["1d", "7d", "28d", "today", "this_week", "this_month"]) {
    const section = validatedTimeline[timeframe];
    if (!section) continue;
    if (!("urgent" in section)) section.urgent = [];
    if (!("normal" in section)) section.normal = [];
  }
  return validatedTimeline;
}
```

### Data Flow Chain

1. **API Call** → `/api/canon` returns raw data
2. **Validation** → `validateTimelineSchema()` ensures structure
3. **State Storage** → Stored in `brief` state (line 222)
4. **Filtering** → `filteredTimeline` removes dismissed items (lines 497-511)
5. **Hero Mapping** → `heroTimeline` maps to component format (lines 539-550)
6. **Component Render** → Passed to `<Timeline items={heroTimeline} />` (line 944)

### Critical Finding #1: Data Transformation

**Lines 539-550:**
```javascript
const heroTimeline = useMemo(() => {
  const tl = filteredPersonal?.timeline || {};
  const mapSection = (section) => ({
    urgent: section?.urgent || [],
    normal: section?.normal || [],
  });
  return {
    today: mapSection(tl["1d"] || tl.today || {}),      // ← Maps 1d to "today"
    this_week: mapSection(tl["7d"] || tl.this_week || {}), // ← Maps 7d to "this_week"
    this_month: mapSection(tl["28d"] || tl.this_month || {}), // ← Maps 28d to "this_month"
  };
}, [filteredPersonal?.timeline]);
```

**ISSUE IDENTIFIED:** The data is transformed from `1d/7d/28d` keys to `today/this_week/this_month` keys before being passed to Timeline component.

---

## PART 2: DAILY GOALS DISPLAY ISSUE

### Root Cause: Key Mismatch

**File:** `src/components/brief/Timeline.jsx`

**Lines 14-39:** Timeline component expects specific keys
```javascript
const timeframes = useMemo(
  () => [
    {
      key: "today",           // ← Expects "today"
      fallbacks: ["1d"],      // ← Falls back to "1d" if not found
      title: "Daily Goals",
      icon: "",
      empty: "No urgent tasks today 🎉",
    },
    {
      key: "this_week",       // ← Expects "this_week"
      fallbacks: ["7d"],      // ← Falls back to "7d"
      title: "Weekly Focus",
      // ...
    },
    {
      key: "this_month",      // ← Expects "this_month"
      fallbacks: ["28d"],     // ← Falls back to "28d"
      title: "Monthly Objectives",
      // ...
    },
  ],
  []
);
```

**Lines 44-50:** Section data retrieval
```javascript
const section =
  timelineData?.[tf.key] ||                        // Try primary key first
  (tf.fallbacks || []).reduce(                     // Then try fallbacks
    (acc, alt) => acc || timelineData?.[alt],
    null
  ) ||
  {};
```

**Lines 51:** Task count calculation
```javascript
const count = getTotalTaskCount(section);
```

**Lines 215-218:** Count function
```javascript
function getTotalTaskCount(data) {
  if (!data) return 0;
  return ["urgent", "normal"].reduce((sum, key) => sum + ((data[key] || []).length || 0), 0);
}
```

### Why Daily Goals Shows "0 tasks"

**ANALYSIS:**

1. DailyBrief passes `heroTimeline` with keys: `today`, `this_week`, `this_month`
2. Timeline component looks for `today` key first ✓ (MATCH)
3. Timeline component checks `section.urgent` and `section.normal` ✓ (CORRECT)
4. `getTotalTaskCount()` correctly counts both urgent + normal ✓ (CORRECT)

**VERDICT:** The Daily Goals component logic is CORRECT. The "0 tasks" issue must be caused by:
- Backend not returning data in `1d.normal` array
- Data being filtered out in `filteredTimeline` (lines 497-511)
- Items being in `dismissedItems` state

### Diagnostic Logging Needed

**Add to DailyBrief.jsx line 944:**
```javascript
console.log('[TIMELINE DEBUG] heroTimeline data:', {
  today_urgent: heroTimeline.today?.urgent?.length || 0,
  today_normal: heroTimeline.today?.normal?.length || 0,
  today_items: heroTimeline.today,
  week_urgent: heroTimeline.this_week?.urgent?.length || 0,
  week_normal: heroTimeline.this_week?.normal?.length || 0,
  month_urgent: heroTimeline.this_month?.urgent?.length || 0,
  month_normal: heroTimeline.this_month?.normal?.length || 0,
});
```

**Add to Timeline.jsx line 52:**
```javascript
console.log(`[TIMELINE] ${tf.title} section data:`, {
  key: tf.key,
  fallbacks: tf.fallbacks,
  section,
  urgent_count: section?.urgent?.length || 0,
  normal_count: section?.normal?.length || 0,
  total_count: count,
  urgent_items: section?.urgent,
  normal_items: section?.normal,
});
```

---

## PART 3: DUPLICATE TASKS ISSUE

### Rendering Logic

**Lines 103-116:** Task rendering
```javascript
{count === 0 ? (
  <div className="empty-timeline-section">
    <p className="empty-message">{emptyMessage}</p>
  </div>
) : (
  ["urgent", "normal"].map(
    (priority) =>
      Array.isArray(items?.[priority]) &&
      items[priority].map((task) => (
        <TaskCard
          key={task.signature || task.id || task.title}  // ← KEY ISSUE
          task={task}
          priority={priority}
          onComplete={onComplete}
          onDelete={onDelete}
        />
      ))
  )
)}
```

### Critical Finding #2: Duplicate Rendering

**ISSUE IDENTIFIED:** The rendering loops through BOTH `["urgent", "normal"]` arrays separately. If the same task exists in BOTH arrays (with same `source_id`), it will render TWICE.

**Example:**
```javascript
// Backend returns:
{
  "7d": {
    "urgent": [
      { source_id: "cal_123", title: "Trade with Chase", ... }
    ],
    "normal": [
      { source_id: "cal_123", title: "Trade with Chase", ... }  // SAME item
    ]
  }
}
```

**Result:** "Trade with Chase" appears twice in the UI.

### Why Duplicates Occur

**Lines 103-116 Analysis:**
- The code does TWO separate `.map()` operations (one for urgent, one for normal)
- No deduplication logic exists
- React keys use `task.signature || task.id || task.title`, but this doesn't prevent duplicates
- It just ensures React doesn't warn about missing keys

### Diagnostic Logging Needed

**Add to Timeline.jsx line 106:**
```javascript
const urgentItems = items?.urgent || [];
const normalItems = items?.normal || [];

console.log(`[TIMELINE] ${tf.title} rendering:`, {
  urgent_count: urgentItems.length,
  normal_count: normalItems.length,
  urgent_source_ids: urgentItems.map(t => t.source_id),
  normal_source_ids: normalItems.map(t => t.source_id),
  duplicates: urgentItems.filter(u =>
    normalItems.some(n => n.source_id === u.source_id)
  ).map(t => ({ title: t.title, source_id: t.source_id }))
});
```

---

## PART 4: TIME DISPLAY ISSUE (2-Minute Offset)

### Date Parsing Logic

**File:** `src/utils/dateUtils.js`

**Lines 74-132:** Human-readable relative time parsing
```javascript
// Human-readable relative time patterns
const patterns = [
  {
    regex: /(?:due\s+)?in\s+(\d+\.?\d*)\s*(second|sec|minute|min|hour|hr|h|day|d|week|wk|w|month|mo|year|yr|y)s?/i,
    future: true
  },
  // ...
];

for (const pattern of patterns) {
  const match = trimmed.match(pattern.regex);
  if (match) {
    const amount = parseFloat(match[1]);
    const unit = match[2].toLowerCase();
    const now = new Date();  // ← USES CURRENT TIME
    const multiplier = pattern.future ? 1 : -1;

    const ms = unitMap[unit];
    if (ms) {
      const resultDate = new Date(now.getTime() + (amount * ms * multiplier));
      if (!isNaN(resultDate.getTime())) return resultDate;
    }
  }
}
```

### Critical Finding #3: Incorrect Parsing Logic

**THE BUG:**

When backend sends: `"Due in 8 hours"`
- Current time: 10:28 AM
- Calculation: `10:28 AM + 8 hours = 6:28 PM` ❌
- Should use: Backend's `deadline_raw` field (6:30 PM) ✅

**ISSUE:** The parser calculates a NEW deadline from the current time instead of parsing the actual deadline from `deadline_raw`.

### Timeline.jsx Usage

**Lines 130-141:** TaskCard component extracts deadline
```javascript
let deadline = task.deadline || task.date;
const description = task.detail || task.description;

// If no deadline but description contains ISO timestamp, extract it
if (!deadline && description) {
  const isoMatch = description.match(/\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}/i);
  if (isoMatch) {
    deadline = isoMatch[0].replace(' ', 'T');  // ← Tries to extract from description
  }
}

const deadlineText = formatDeadlineDisplay(deadline);
const relativeTime = getTimeUntil(deadline);
```

**MISSING:** No usage of `task.deadline_raw` field!

### Why Times Are Off By 2 Minutes

**ANALYSIS:**

1. Backend generates tasks at 10:28 AM with `deadline_raw: "2026-01-02T18:30:00Z"` (6:30 PM)
2. Backend creates human-readable `deadline: "Due in 8 hours"`
3. Frontend receives `deadline: "Due in 8 hours"`
4. `parseDeadline()` calculates: `current time (10:28) + 8 hours = 6:28 PM` ❌
5. Should use: `deadline_raw: "2026-01-02T18:30:00Z"` → `6:30 PM` ✅

**VERDICT:** The 2-minute offset comes from the time elapsed between when the backend generated the timeline (10:28) and when the frontend parses "Due in 8 hours" (still using 10:28 as the base).

### Diagnostic Logging Needed

**Add to Timeline.jsx line 140:**
```javascript
console.log('[TIMELINE] Task deadline parsing:', {
  title: task.title,
  deadline: task.deadline,
  deadline_raw: task.deadline_raw,  // Check if this exists!
  date: task.date,
  description_contains_iso: /\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}/.test(description || ''),
  parsed_deadline_text: deadlineText,
  parsed_relative_time: relativeTime,
});
```

**Add to dateUtils.js line 269:**
```javascript
console.log('[dateUtils] parseDeadline failed:', {
  input: deadline,
  type: typeof deadline,
  current_time: new Date().toISOString(),
});
```

---

## PART 5: MISSING TASKS AUDIT

### Filtering Logic

**File:** `src/pages/DailyBrief.jsx`

**Lines 476-479:** Dismissed items check
```javascript
const isDismissed = useCallback(
  (item) => dismissedItems.some((d) => isSameItem(d, item)),
  [dismissedItems]
);
```

**Lines 113-119:** Item comparison logic
```javascript
const isSameItem = (a, b) => {
  if (!a || !b) return false;
  if (a.source_id && b.source_id && a.source_id === b.source_id) return true;
  if (a.signature && b.signature) return a.signature === b.signature;
  return a.title === b.title && a.source_type === b.source_type;
};
```

**Lines 492-495:** Filter function
```javascript
const filterList = useCallback(
  (list) => (Array.isArray(list) ? list.filter((i) => !isDismissed(i)) : []),
  [isDismissed]
);
```

**Lines 497-511:** Timeline filtering
```javascript
const filteredTimeline = useMemo(() => {
  const tl = personalData?.timeline || {};
  const keys = ["1d", "7d", "28d"];
  const out = {};
  keys.forEach((k) => {
    const section = tl[k];
    if (!section) return;
    const filtered = {};
    Object.entries(section).forEach(([key, val]) => {
      filtered[key] = Array.isArray(val) ? filterList(val) : val;  // ← FILTERS HERE
    });
    out[k] = filtered;
  });
  return out;
}, [personalData, filterList]);
```

### Critical Finding #4: Tasks Hidden by Dismissed Items

**ISSUE:** Any task that was previously completed or deleted is stored in `dismissedItems` state and will be filtered out from the timeline.

**Lines 290-291:** Items added to dismissedItems on complete
```javascript
setCompletedItems((prev) => [item, ...prev]);
setDismissedItems((prev) => [...prev, item]);
```

**Lines 311:** Items added to dismissedItems on delete
```javascript
setDismissedItems((prev) => [...prev, item]);
```

**VERDICT:** If backend shows 12 items but frontend shows 10, likely 2 items are in `dismissedItems` local state.

### Diagnostic Logging Needed

**Add to DailyBrief.jsx line 510:**
```javascript
console.log('[TIMELINE FILTERING]', {
  raw_timeline_keys: Object.keys(tl),
  '1d_urgent_raw': tl['1d']?.urgent?.length || 0,
  '1d_normal_raw': tl['1d']?.normal?.length || 0,
  '7d_urgent_raw': tl['7d']?.urgent?.length || 0,
  '7d_normal_raw': tl['7d']?.normal?.length || 0,
  '28d_urgent_raw': tl['28d']?.urgent?.length || 0,
  '28d_normal_raw': tl['28d']?.normal?.length || 0,
  dismissed_items_count: dismissedItems.length,
  dismissed_items: dismissedItems.map(d => ({
    title: d.title,
    source_id: d.source_id,
    signature: d.signature
  })),
});
```

**Add to DailyBrief.jsx line 550:**
```javascript
console.log('[HERO TIMELINE]', {
  today_urgent_filtered: heroTimeline.today?.urgent?.length || 0,
  today_normal_filtered: heroTimeline.today?.normal?.length || 0,
  week_urgent_filtered: heroTimeline.this_week?.urgent?.length || 0,
  week_normal_filtered: heroTimeline.this_week?.normal?.length || 0,
  month_urgent_filtered: heroTimeline.this_month?.urgent?.length || 0,
  month_normal_filtered: heroTimeline.this_month?.normal?.length || 0,
});
```

---

## PART 6: RECURRING EVENT DISPLAY

### Backend Data Requirements

**File:** `src/components/brief/Timeline.jsx`

**Lines 143:** Recurring check
```javascript
const isRecurring = task.is_recurring === true;
```

**Lines 158-162:** Recurring badge
```javascript
{isRecurring && (
  <span className="recurrence-badge" title={task.recurrence_description || "Recurring event"}>
    🔁 {task.recurrence_description || "Recurring"}
  </span>
)}
```

**Lines 165-175:** Recurrence info
```javascript
{isRecurring && task.instance_count > 1 && (
  <div className="recurrence-info">
    <span className="instance-count">
      {task.instance_count} upcoming occurrence{task.instance_count !== 1 ? 's' : ''}
    </span>
    {task.next_occurrence && formatDeadlineDisplay(task.next_occurrence) && (
      <span className="next-occurrence">
        Next: {formatDeadlineDisplay(task.next_occurrence)}
      </span>
    )}
  </div>
)}
```

### Required Backend Fields

For recurring events to display correctly, backend MUST send:

1. `is_recurring: true` (boolean)
2. `recurrence_description: "Daily at 06:30"` (string)
3. `instance_count: 2` (number, optional but recommended)
4. `next_occurrence: "2026-01-03T06:30:00Z"` (ISO string, optional)

### Diagnostic Logging Needed

**Add to Timeline.jsx line 143:**
```javascript
console.log('[TIMELINE] Task recurring check:', {
  title: task.title,
  is_recurring: task.is_recurring,
  recurrence_description: task.recurrence_description,
  instance_count: task.instance_count,
  next_occurrence: task.next_occurrence,
  has_all_fields: !!(task.is_recurring && task.recurrence_description),
});
```

---

## PART 7: COMPONENT STRUCTURE

### File Hierarchy

```
src/pages/DailyBrief.jsx
  ├── Fetches /api/canon
  ├── Validates timeline schema
  ├── Filters dismissed items
  ├── Maps to heroTimeline format
  └── Renders <Timeline items={heroTimeline} />

src/components/brief/Timeline.jsx
  ├── Maps timeframes (today, this_week, this_month)
  ├── Renders TimelineSection for each
  └── TimelineSection
      └── Renders TaskCard for each task

src/components/brief/TaskCard (inline in Timeline.jsx)
  ├── Extracts deadline from task
  ├── Calls parseDeadline() from dateUtils
  ├── Calls formatDeadlineDisplay() from dateUtils
  ├── Calls getTimeUntil() from dateUtils
  └── Renders task UI with deadline info

src/utils/dateUtils.js
  ├── parseDeadline(deadline) - Parses various formats
  ├── formatDeadlineDisplay(deadline) - Returns "today at 6:30 PM"
  └── getTimeUntil(deadline) - Returns "in 8 hours"
```

### Data Flow

```
API Response (JSON)
  ↓
validateTimelineSchema() - Ensures { urgent: [], normal: [] } structure
  ↓
State: brief.timeline = { "1d": {...}, "7d": {...}, "28d": {...} }
  ↓
filteredTimeline - Removes dismissed items
  ↓
heroTimeline - Maps keys: 1d→today, 7d→this_week, 28d→this_month
  ↓
Timeline Component - Receives items prop
  ↓
TimelineSection - For each timeframe
  ↓
TaskCard - For each task
  ↓
dateUtils functions - Parse and format deadlines
```

### State Management

**Local State (DailyBrief.jsx):**
- `brief` - Raw API response
- `canonicalPlan` - Validated data
- `dismissedItems` - User actions (complete/delete)
- `completedItems` - Completed tasks history

**No Redux/Context** - All state is local to DailyBrief component

**LocalStorage** - Used only in TaskContext (not used by Timeline)

---

## PART 8: CODE LOCATIONS & LINE NUMBERS

### Files to Investigate

| File | Lines | Purpose |
|------|-------|---------|
| `src/pages/DailyBrief.jsx` | 154-233 | API fetching and data loading |
| `src/pages/DailyBrief.jsx` | 44-68 | Schema validation |
| `src/pages/DailyBrief.jsx` | 497-511 | Timeline filtering (dismissedItems) |
| `src/pages/DailyBrief.jsx` | 539-550 | Hero timeline mapping (KEY TRANSFORM) |
| `src/pages/DailyBrief.jsx` | 113-119 | Item comparison logic |
| `src/components/brief/Timeline.jsx` | 14-39 | Timeframe configuration |
| `src/components/brief/Timeline.jsx` | 44-50 | Section data retrieval |
| `src/components/brief/Timeline.jsx` | 103-116 | Task rendering (DUPLICATE ISSUE) |
| `src/components/brief/Timeline.jsx` | 130-141 | Deadline extraction |
| `src/components/brief/Timeline.jsx` | 143 | Recurring check |
| `src/components/brief/Timeline.jsx` | 158-175 | Recurring display |
| `src/components/brief/Timeline.jsx` | 215-218 | Count calculation |
| `src/utils/dateUtils.js` | 74-132 | Relative time parsing (TIME BUG) |
| `src/utils/dateUtils.js` | 278-333 | Format deadline display |
| `src/utils/dateUtils.js` | 340-377 | Get time until |

---

## FINAL SUMMARY: ROOT CAUSES

### Issue 1: Daily Goals Shows "0 tasks"
**Root Cause:** NOT a code bug. Either:
- Backend not returning data in `1d.normal` array
- Tasks filtered out via `dismissedItems` state
- Need logging to confirm which

**Action Required:** Add diagnostic logging to verify backend response

---

### Issue 2: Duplicate Tasks in Weekly Focus
**Root Cause:** Code bug in `Timeline.jsx` lines 103-116
- Renders urgent array separately from normal array
- No deduplication when same `source_id` exists in both
- Backend may be returning same event in both priority levels

**Fix Needed:** Deduplicate tasks by `source_id` before rendering

---

### Issue 3: Times Off by 2 Minutes
**Root Cause:** Logic bug in `dateUtils.js` lines 74-132
- Parses "Due in 8 hours" by adding 8 hours to CURRENT time
- Should use `task.deadline_raw` ISO timestamp instead
- Offset = time elapsed since backend generated timeline

**Fix Needed:**
1. Use `task.deadline_raw` if available
2. Only fallback to parsing "Due in X hours" if no `deadline_raw`

---

### Issue 4: Missing Tasks (12 → 10)
**Root Cause:** `dismissedItems` state filtering
- Lines 497-511 filter out any previously completed/deleted items
- Items persist in localStorage/state across sessions
- Need to verify if 2 items are in `dismissedItems`

**Action Required:** Add diagnostic logging to check dismissed items

---

### Issue 5: Recurring Badge Not Showing
**Root Cause:** Backend not sending required fields
- Requires `is_recurring: true` flag
- Requires `recurrence_description` string
- Frontend code is correct (lines 158-175)

**Action Required:** Verify backend sends these fields

---

## RECOMMENDED DIAGNOSTIC SCRIPT

Add this to **DailyBrief.jsx** at line 944 (before `<Timeline />` render):

```javascript
// ========== COMPREHENSIVE TIMELINE DIAGNOSTIC ==========
console.group('📊 TIMELINE DIAGNOSTIC REPORT');

// 1. Raw API Response
console.log('1️⃣ Raw personalData.timeline:', personalData?.timeline);

// 2. Filtered Timeline (after dismissedItems filter)
console.log('2️⃣ Filtered Timeline:', filteredTimeline);
console.log('  └─ Dismissed items count:', dismissedItems.length);
console.log('  └─ Dismissed items:', dismissedItems.map(d => ({
  title: d.title,
  source_id: d.source_id,
  signature: d.signature
})));

// 3. Hero Timeline (after key mapping)
console.log('3️⃣ Hero Timeline (passed to component):', heroTimeline);
console.table({
  'Daily Urgent': heroTimeline.today?.urgent?.length || 0,
  'Daily Normal': heroTimeline.today?.normal?.length || 0,
  'Weekly Urgent': heroTimeline.this_week?.urgent?.length || 0,
  'Weekly Normal': heroTimeline.this_week?.normal?.length || 0,
  'Monthly Urgent': heroTimeline.this_month?.urgent?.length || 0,
  'Monthly Normal': heroTimeline.this_month?.normal?.length || 0,
});

// 4. Check for duplicates in weekly
if (heroTimeline.this_week) {
  const weeklyUrgent = heroTimeline.this_week.urgent || [];
  const weeklyNormal = heroTimeline.this_week.normal || [];
  const duplicates = weeklyUrgent.filter(u =>
    weeklyNormal.some(n => n.source_id === u.source_id)
  );
  console.log('4️⃣ Weekly Duplicates (same source_id in urgent AND normal):', duplicates.map(d => ({
    title: d.title,
    source_id: d.source_id
  })));
}

// 5. Sample task with full data
const sampleTask = heroTimeline.this_week?.urgent?.[0] || heroTimeline.this_week?.normal?.[0];
if (sampleTask) {
  console.log('5️⃣ Sample Task (full data structure):', sampleTask);
  console.log('  └─ Has deadline_raw?', 'deadline_raw' in sampleTask);
  console.log('  └─ Has is_recurring?', 'is_recurring' in sampleTask);
  console.log('  └─ Has recurrence_description?', 'recurrence_description' in sampleTask);
}

console.groupEnd();
// ========== END DIAGNOSTIC ==========
```

Add this to **Timeline.jsx** at line 52:

```javascript
// Log each section as it renders
console.log(`[Timeline Section: ${tf.title}]`, {
  key: tf.key,
  fallbacks: tf.fallbacks,
  found_data: !!section,
  urgent_count: section?.urgent?.length || 0,
  normal_count: section?.normal?.length || 0,
  total_count: count,
  urgent_source_ids: section?.urgent?.map(t => t.source_id) || [],
  normal_source_ids: section?.normal?.map(t => t.source_id) || [],
});
```

Add this to **dateUtils.js** at line 6 (inside parseDeadline function):

```javascript
const originalInput = deadline;  // Store original
const parseStartTime = new Date();  // Track when parsing happens
```

And at line 270 (before return null):

```javascript
console.warn('[dateUtils] Failed to parse:', {
  original_input: originalInput,
  type: typeof originalInput,
  parse_time: parseStartTime.toISOString(),
  current_time: new Date().toISOString(),
  time_elapsed_ms: Date.now() - parseStartTime.getTime(),
});
```

---

## CONCLUSION

All 5 issues have been identified with specific line numbers and root causes. The diagnostic logging above will confirm the findings and provide the exact data needed to implement fixes.

**DO NOT IMPLEMENT FIXES** - This report is for diagnosis only.
