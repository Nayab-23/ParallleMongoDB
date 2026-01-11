# Frontend Canon System Analysis - Complete Report Needed

## Context

We have a Canon system (AI-powered daily timeline) that's showing issues:

1. **Old events/tasks appearing** in Daily Brief despite being past
2. **Recommendation system still being used** when it should directly populate the timeline
3. **Canon refresh working on backend** but frontend may not be handling updates correctly

Backend is now working correctly:
- Worker runs every 1 minute ✅
- Fetches Gmail/Calendar ✅
- Calls AI to generate timeline ✅
- Auto-adds items to `approved_timeline` (no longer uses recommendations) ✅
- Returns via `GET /api/canon` ✅

## Your Task

Please analyze the **entire frontend canon/daily brief flow** and provide a complete report covering:

---

## PART 1: Current Implementation Analysis

### A. File Structure
List ALL files involved in canon/daily brief:
- Components (Intelligence.jsx, DailyBrief.jsx, etc.)
- API calls/hooks
- State management
- Utils/helpers

For each file, provide:
- File path
- Purpose
- Key functions/components
- Lines of code that interact with canon

### B. API Integration

**Show the complete code** for:

1. **GET /api/canon** - How is it called?
   - When does it trigger? (on mount, interval, manual refresh?)
   - What does it do with the response?
   - Where is the response stored? (state, context, localStorage?)

2. **POST /api/canon/refresh** - How is it called?
   - What triggers manual refresh?
   - What happens after refresh completes?
   - Does it reload canon after refresh?

3. **Response handling**
   - Show exact response structure expected
   - Show how `timeline`, `priorities`, `recommendations` are used
   - Any data transformations applied?

### C. Timeline Display Logic

**Critical:** Show exactly how items are displayed in the UI:

1. **Where are timeline items rendered?**
   - Component name and file path
   - Code snippet showing the render logic

2. **Filtering logic:**
   ```javascript
   // Show ALL code that filters timeline items:
   // - Date filtering (past vs future)
   // - Completion filtering
   // - Any other filtering
   ```

3. **Item structure:**
   ```javascript
   // What does a timeline item look like?
   {
     title: "...",
     detail: "...",
     deadline: "...",  // ← Is this used for filtering?
     date: "...",      // ← Is this used for filtering?
     signature: "...",
     // What else?
   }
   ```

### D. Recommendation System (Should be Removed)

**Show all code related to recommendations:**

1. Where are `recommendations` from API response used?
2. Is there UI to "approve" recommendations?
3. Does it call any `/recommendations/accept` endpoints?
4. **Are recommendations being mixed with approved timeline items?**

### E. State Management

**Show complete state flow:**

1. Where is canon data stored?
   ```javascript
   // useState? useContext? Redux? localStorage?
   const [canon, setCanon] = useState(...)
   ```

2. When does state update?
   - After GET /api/canon?
   - After POST /api/canon/refresh?
   - On interval polling?

3. Is there any caching?
   - localStorage cache?
   - stale-while-revalidate?
   - Any timestamps checked?

---

## PART 2: Current Behavior Documentation

### A. User Flow - Daily Brief Load

**Step by step, what happens when user opens Daily Brief?**

Example format:
```
1. User clicks "Daily Brief" tab
2. Component mounts → calls useEffect
3. useEffect calls GET /api/canon
4. Response arrives: {timeline: {...}, recommendations: [...]}
5. State updates: setCanon(response)
6. Render function filters items by... [WHAT FILTERS?]
7. Display shows items from... [timeline? recommendations? both?]
```

### B. User Flow - Manual Refresh

**Step by step, what happens when user clicks "Refresh Canon"?**

Example:
```
1. User clicks refresh button
2. onClick handler calls POST /api/canon/refresh
3. Backend returns: {recommendations_added: 0, total_recommendations: 0}
4. Frontend does... [WHAT HAPPENS NEXT?]
5. Does it reload GET /api/canon? Or just update recommendations?
```

### C. Auto-Refresh Behavior

**Does frontend poll for updates?**

1. Is there a `setInterval` or polling?
2. How often does it check for new data?
3. Does it use WebSocket/SSE for real-time updates?

---

## PART 3: Issues to Investigate

Based on the logs you provided:
```javascript
[Canon] Refresh successful: {
  last_sync: "2025-12-23T01:28:08.460751+00:00",
  recommendations_added: 0,
  success: true,
  total_recommendations: 0
}
[Canon] Loading existing canon...
```

### Questions:

1. **Why does refresh return `recommendations_added: 0`?**
   - Backend now auto-adds to timeline (not recommendations)
   - Is frontend expecting recommendations?

2. **After refresh, does it reload canon?**
   - Log shows "Loading existing canon..." AFTER refresh
   - Does this mean it's calling GET /api/canon again?
   - Show that code

3. **Old items appearing - Filtering issue?**
   - Show ALL code that filters items by date
   - Are you checking `deadline` field?
   - Are you comparing against current date?
   - Example:
     ```javascript
     // Is there code like this?
     const today = new Date();
     const futureItems = items.filter(item =>
       new Date(item.deadline) >= today
     );
     ```

4. **Are completed items being filtered out?**
   - Backend filters by `completed_signatures`
   - Does frontend also filter?
   - Is there duplicate filtering causing issues?

---

## PART 4: Expected Backend Behavior (For Your Reference)

**GET /api/canon** returns:
```json
{
  "exists": true,
  "timeline": {
    "1d": {
      "critical": [
        {
          "title": "Fix production bug",
          "detail": "Users affected now",
          "deadline": "5pm today",
          "signature": "abc123..."
        }
      ],
      "high_priority": [...]
    },
    "7d": {
      "milestones": [...],
      "upcoming": [...]
    },
    "28d": {
      "goals": [...],
      "progress": {}
    }
  },
  "priorities": [...],
  "recommendations": [],  // ← SHOULD BE EMPTY NOW (auto-added to timeline)
  "last_sync": "2025-12-23T01:28:08+00:00"
}
```

**POST /api/canon/refresh** returns:
```json
{
  "recommendations_added": 0,  // ← Always 0 now (items auto-added to timeline)
  "total_recommendations": 0,
  "last_sync": "2025-12-23T01:28:08+00:00"
}
```

**After refresh, frontend MUST call GET /api/canon again** to get updated timeline.

---

## PART 5: Code Snippets Requested

Please provide **complete code** for these specific areas:

### 1. Canon API Hook/Service
```javascript
// File: ???
// Show the complete hook or service that calls /api/canon

export function useCanon() {
  // SHOW EVERYTHING
}
```

### 2. Daily Brief Component
```javascript
// File: ???
// Show the main component that displays the daily brief

export default function DailyBrief() {
  // SHOW EVERYTHING - especially:
  // - How canon data is fetched
  // - How items are filtered
  // - How items are rendered
}
```

### 3. Timeline Item Rendering
```javascript
// File: ???
// Show the component that renders individual timeline items

function TimelineItem({ item, timeframe, priority }) {
  // SHOW EVERYTHING
}
```

### 4. Refresh Button Handler
```javascript
// File: ???
// Show the complete refresh logic

async function handleRefreshCanon() {
  // SHOW EVERYTHING - especially:
  // - What API is called
  // - What happens after response
  // - Does it reload canon?
}
```

### 5. Date Filtering Logic
```javascript
// File: ???
// Show ALL code that filters items by date/time

function filterPastItems(items) {
  // SHOW EVERYTHING
}

function filterByDeadline(items) {
  // SHOW EVERYTHING
}
```

---

## PART 6: Specific Questions to Answer

1. **Where does "Daily Brief" get its data from?**
   - GET /api/canon?
   - GET /api/daily-brief? (deprecated endpoint?)
   - Somewhere else?

2. **Are you using `recommendations` field at all?**
   - If yes, WHERE and WHY?
   - Backend no longer populates this (items auto-added to timeline)

3. **How do you determine if an item is "old"?**
   - Do you check `deadline` field?
   - Do you parse dates from `detail` field?
   - Show the exact code

4. **Are there multiple sources of timeline data?**
   - Canon timeline
   - Recommendations (being shown as timeline?)
   - Cached data (localStorage?)
   - Multiple API calls combined?

5. **What happens when backend returns empty recommendations?**
   - Does frontend break?
   - Does it show an error?
   - Does it fall back to something?

---

## Output Format

Please provide your analysis in this format:

```markdown
# Canon Frontend Analysis Report

## 1. File Inventory
- src/components/Intelligence.jsx - [Purpose] - [Key functions]
- src/components/DailyBrief.jsx - [Purpose] - [Key functions]
- ... (ALL FILES)

## 2. API Integration
### GET /api/canon
[Complete code with line numbers]

### POST /api/canon/refresh
[Complete code with line numbers]

## 3. Timeline Display
[Complete code showing how items are rendered]

## 4. Filtering Logic
[Complete code showing date/completion filtering]

## 5. Recommendation Handling
[Complete code - or "NOT USED" if not present]

## 6. State Management
[Complete code showing state flow]

## 7. User Flows
### Daily Brief Load
[Step by step with actual code]

### Manual Refresh
[Step by step with actual code]

## 8. Issues Identified
1. [Issue description] - [File:Line] - [Code snippet]
2. ...

## 9. Recommendations
1. Remove recommendation UI (if present)
2. Fix date filtering to exclude past items
3. Reload canon after refresh
4. ...
```

---

## Why This Matters

Backend now works like this:
1. Worker fetches emails/calendar every 1 minute
2. AI categorizes into timeline (1d/7d/28d)
3. Items **auto-added to `approved_timeline`** (not recommendations)
4. Frontend should just display `timeline`, NOT `recommendations`

But frontend seems to:
- Still expect recommendations
- Not properly filter old items
- Not reload after refresh

We need your complete analysis to fix this properly.

---

## What We'll Do With Your Report

Once you provide the analysis, I'll:
1. Identify exact issues (old filtering, recommendation usage, etc.)
2. Write a new prompt with specific fixes
3. You'll implement the fixes
4. Canon will work perfectly

---

## Please Start Now

Analyze your frontend codebase and provide the complete report above. Focus on:
1. **COMPLETE CODE** (not summaries)
2. **EXACT FILE PATHS** and line numbers
3. **ACTUAL BEHAVIOR** not assumptions
4. **ALL FILTERING LOGIC** especially dates
5. **RECOMMENDATION USAGE** (should be removed)

Thank you!
