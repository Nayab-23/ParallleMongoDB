# Complete Pipeline Diagnostics - Logging Added

## Summary

Added comprehensive stage-by-stage diagnostic logging to track where items are being lost in the timeline generation pipeline.

**Status**: DIAGNOSTIC LOGGING COMPLETE - Ready for testing
**File Modified**: `/Users/severinspagnola/Desktop/MongoDBHack/apps/api/app/services/canon.py`
**Purpose**: Track the exact stage where "Actionable time" events (and other items) disappear

---

## What Was Added

### 1. Helper Function: `count_items()`

**Location**: Lines 1232-1258 in `canon.py`

This function tracks item counts at each pipeline stage:
- Total items
- Calendar items
- Email items
- **"Actionable time" items** (specifically tracked)

For every "Actionable time" item found, it logs:
- Full title
- Source ID (to identify which exact event it is)

### 2. Stage-by-Stage Tracking

Added logging at **7 critical stages**:

#### **Stage 0: Initial** (Line 1315-1317)
- Right after fetching raw events + emails
- Before any processing

#### **Stage 1: After source_id dedup** (Lines 1323-1326)
- After `deduplicate_by_source_id()` removes exact duplicates
- Loss report: Stage 0 → Stage 1

#### **Stage 2: After similar dedup** (Lines 1331-1334)
- After `deduplicate_similar_events()` removes similar events (e.g., 3x "Supabase Security Issue")
- Loss report: Stage 1 → Stage 2

#### **Stage 3: After prep dedup** (Lines 1339-1342)
- After `deduplicate_prep_events()` removes "Prepare for X" when main event exists
- Loss report: Stage 2 → Stage 3

#### **Stage 4: After semantic dedup** (Lines 1348-1351)
- After `deduplicate_by_semantics()` removes semantically similar events
- Loss report: Stage 3 → Stage 4

#### **Stage 5: After time filter** (Lines 1387-1390)
- After removing past events (events that already happened)
- Loss report: Stage 4 → Stage 5

#### **Stage 6: After deletion filter** (Lines 1400-1402)
- After `filter_by_deletion_patterns()` removes events user has repeatedly deleted
- Loss report: Stage 5 → Stage 6

#### **Stage FINAL: Items sent to AI** (Lines 1409-1433)
- Complete list of ALL items being sent to AI
- Shows EVERY item with:
  - Full title
  - Source type (calendar/email)
  - Source ID
  - Time field
- Final loss report: Stage 0 → Final

---

## What You'll See in Logs

### At Each Stage:
```
================================================================================
🔍 [STAGE X: Description] ITEM COUNTS:
[STAGE X] Total: 31
[STAGE X]   - Calendar: 31
[STAGE X]   - Email: 0
[STAGE X] 🎯 'Actionable time': 9
[STAGE X] === ALL 'Actionable time' ITEMS ===
[STAGE X]   1. Actionable time
[STAGE X]      Source ID: abc123def456
[STAGE X]   2. Actionable time
[STAGE X]      Source ID: xyz789ghi012
... (for all 9 "Actionable time" events)
================================================================================
⚠️ LOSS REPORT: Stage X-1 → Stage X: Lost 0 items
```

### At Final Stage:
```
================================================================================
🤖 [STAGE FINAL] === COMPLETE LIST SENT TO AI ===
[STAGE FINAL] Total items: 12
[STAGE FINAL]   - Emails: 0
[STAGE FINAL]   - Events: 12

[STAGE FINAL] ALL ITEMS BEING SENT TO AI:
  1. [calendar] Event Title Here
     Source ID: abc123
     Time: 2025-01-01T10:00:00Z
  2. [calendar] Another Event
     Source ID: def456
     Time: 2025-01-01T14:00:00Z
... (for all 12 items)
================================================================================
⚠️ FINAL LOSS REPORT: Stage 0 → Final: Lost 19 total items
================================================================================
```

---

## How to Use This

### Step 1: Trigger a Timeline Refresh
1. Click the "🔄 Refresh" button in the Intelligence tab
2. Or wait for the next automatic refresh (within 1 minute)

### Step 2: Check Backend Logs
Look for the following log sections (in order):

1. **STAGE 0**: Should show 31 total items with 9 "Actionable time"
2. **STAGE 1**: Track if any "Actionable time" lost here
3. **STAGE 2**: Track if any "Actionable time" lost here
4. **STAGE 3**: Track if any "Actionable time" lost here
5. **STAGE 4**: Track if any "Actionable time" lost here
6. **STAGE 5**: Track if any "Actionable time" lost here (past events)
7. **STAGE 6**: Track if any "Actionable time" lost here (deletion patterns)
8. **STAGE FINAL**: Should show exactly what the AI receives

### Step 3: Identify the Problem Stage
- Compare the "Actionable time" count at each stage
- The stage where it drops from 9 to 0 is the culprit
- Look at the LOSS REPORT for that stage

---

## Expected Findings

Based on your report:
- **Stage 0**: 31 items total, 9 "Actionable time" events
- **Stage FINAL**: 12 items total, 0 "Actionable time" events
- **Missing**: 19 items total, including all 9 "Actionable time"

The logs will reveal:
1. **Which specific stage** loses the "Actionable time" events
2. **Source IDs** of all 9 "Actionable time" events
3. **Which deduplication or filter function** is responsible
4. **Why** those events are being removed (e.g., marked as past, filtered by deletion patterns, considered duplicates, etc.)

---

## Important Notes

- **NO FIXES WERE MADE** - Only diagnostic logging was added (as requested)
- All existing deduplication and filtering logic remains unchanged
- The logs will help identify which function needs to be investigated/fixed
- All logs use `logger.warning()` level so they appear in production

---

## Next Steps (After Testing)

1. Run a timeline refresh
2. Copy the relevant log sections from backend
3. Share the logs to identify which stage loses the "Actionable time" events
4. Based on findings, decide whether to:
   - Fix the deduplication logic (if false positive)
   - Fix the time-based filtering (if timezone issue)
   - Fix the deletion pattern filter (if incorrectly learning)
   - Or confirm it's working as intended

---

## File Changes Summary

**File**: `app/services/canon.py`
- **Lines 1232-1258**: Added `count_items()` helper function
- **Lines 1315-1317**: Stage 0 tracking
- **Lines 1323-1326**: Stage 1 tracking + loss report
- **Lines 1331-1334**: Stage 2 tracking + loss report
- **Lines 1339-1342**: Stage 3 tracking + loss report
- **Lines 1348-1351**: Stage 4 tracking + loss report
- **Lines 1387-1390**: Stage 5 tracking + loss report
- **Lines 1400-1402**: Stage 6 tracking + loss report
- **Lines 1409-1433**: Stage FINAL tracking + complete item list + final loss report

**Total Lines Added**: ~100 lines of diagnostic logging
**Impact on Performance**: Minimal (only WARNING level logs during timeline generation)
