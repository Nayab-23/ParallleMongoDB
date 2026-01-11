# Recurring Event Processing and Timestamp Fixes

**Date**: 2026-01-01
**Status**: ✅ **COMPLETE**

---

## Summary

Fixed 4 critical bugs in the timeline generation system causing recurring events to display incorrectly and timestamps to be lost.

---

## 🐛 Issues Fixed

### Issue #1: Double Consolidation (Redundant and Broken)

**Problem**:
- System was consolidating recurring events TWICE:
  1. Before AI (Stage 6.5) - ✅ CORRECT
  2. After AI returns results - ❌ BROKEN
- Post-AI consolidation failed because AI strips the `deadline_raw` field needed for pattern detection

**Root Cause**:
- Original consolidation logic only worked per-section (7d/urgent vs 7d/normal treated separately)
- Developer added post-AI consolidation to fix cross-section consolidation
- This broke because AI response doesn't include raw timestamps

**Solution**:
- ✅ Removed post-AI consolidation entirely
- ✅ Pre-AI consolidation already handles cross-section patterns correctly
- ✅ Added logging to track when consolidation happens

**Code Changes** ([canon.py:1655-1657](app/services/canon.py:1655-1657)):
```python
# Added logging
logger.warning(f"[Stage 6.5] 🔄 Running PRE-AI recurring consolidation")
consolidated_events_pre_ai = consolidate_recurring_events(filtered_events)
logger.warning(f"[Stage 6.5] ✅ Consolidation complete: {len(filtered_events)} → {len(consolidated_events_pre_ai)} events")
```

**Code Removed** ([canon.py:1777-1866](app/services/canon.py:1777-1779)):
```python
# Removed entire post-AI consolidation block (90 lines)
# Replaced with:
logger.warning("[Timeline] ℹ️  Skipping post-AI consolidation (already done pre-AI)")
```

---

### Issue #2: AI Strips Raw Timestamps

**Problem**:
- Events sent to AI have `deadline_raw` field with ISO timestamps
- AI returns categorized events WITHOUT `deadline_raw`
- Future processing (like post-AI consolidation) fails without this field

**Root Cause**:
- AI prompt doesn't ask to preserve `deadline_raw` field
- AI only returns fields it's instructed to include
- Consolidation logic requires `deadline_raw` to detect patterns

**Solution**:
- ✅ After AI returns timeline, restore `deadline_raw` from original events
- ✅ Match events by `source_id` to find original event
- ✅ Also restore `start` and `start_time` fields if missing

**Code Changes** ([canon.py:1715-1741](app/services/canon.py:1715-1741)):
```python
# === FIX #2: Restore deadline_raw fields that AI stripped ===
# Create a lookup of original events by source_id
original_events_map = {}
for item in ai_input_items:  # ai_input_items = what was sent to AI
    source_id = item.get('source_id')
    if source_id:
        original_events_map[source_id] = item

# Restore deadline_raw to AI-returned events
restored_count = 0
for timeframe in ['1d', '7d', '28d']:
    for priority in ['urgent', 'normal']:
        items = stabilized_timeline.get(timeframe, {}).get(priority, [])
        for item in items:
            source_id = item.get('source_id')
            if source_id and source_id in original_events_map:
                original = original_events_map[source_id]
                # Restore raw timestamp fields
                if 'deadline_raw' in original and 'deadline_raw' not in item:
                    item['deadline_raw'] = original['deadline_raw']
                    restored_count += 1
                if 'start' not in item and 'start' in original:
                    item['start'] = original['start']
                if 'start_time' not in item and 'start_time' in original:
                    item['start_time'] = original['start_time']

logger.warning(f"[AI Response] ✅ Restored deadline_raw to {restored_count} events")
```

**Testing**:
- Look for log message: `[AI Response] ✅ Restored deadline_raw to X events`
- `X` should be > 0 for calendar events

---

### Issue #3: Invalid Deadline Formats

**Problem**:
- AI sometimes returns ISO datetime strings in `deadline` field:
  - Example: `"2026-01-02T06:30:00-08:00"`
- Frontend expects human-readable text:
  - Example: `"Due in 8 hours"`
- Frontend shows "Invalid Date" when it gets ISO strings

**Root Cause**:
- AI prompt asks for relative time descriptions
- AI occasionally ignores instructions and returns absolute ISO timestamps
- No validation of AI response format

**Solution**:
- ✅ After AI returns timeline, validate all `deadline` fields
- ✅ Detect ISO datetime patterns (regex: `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}`)
- ✅ Convert ISO strings to human-readable relative time
- ✅ Store original ISO string in `deadline_raw` for future use

**Code Changes** ([canon.py:1743-1799](app/services/canon.py:1743-1799)):
```python
# === FIX #3: Validate and fix AI-returned deadline formats ===
import re

def is_iso_datetime(value):
    """Check if string looks like ISO datetime"""
    if not isinstance(value, str):
        return False
    # Matches patterns like: 2026-01-02T06:30:00-08:00
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', value))

def format_relative_time(iso_string):
    """Convert ISO string to human-readable relative time"""
    try:
        dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        diff = dt - now

        hours = diff.total_seconds() / 3600

        if hours < -1:
            return f"{abs(int(hours))} hours ago"
        elif hours < 0:
            return "Just passed"
        elif hours < 1:
            return "Due now"
        elif hours < 24:
            return f"Due in {int(hours)} hours"
        else:
            days = int(hours / 24)
            return f"Due in {days} day{'s' if days != 1 else ''}"
    except:
        return iso_string  # Return original if parsing fails

# Validate and fix deadlines in AI timeline
fixed_count = 0
for timeframe in ['1d', '7d', '28d']:
    for priority in ['urgent', 'normal']:
        items = stabilized_timeline.get(timeframe, {}).get(priority, [])
        for item in items:
            deadline = item.get('deadline')

            # If deadline is an ISO string, convert to human-readable
            if deadline and is_iso_datetime(deadline):
                logger.warning(
                    f"[AI Response] ⚠️  Fixing invalid deadline format for '{item.get('title')}': {deadline}"
                )
                item['deadline'] = format_relative_time(deadline)
                fixed_count += 1

                # Ensure deadline_raw exists for future processing
                if 'deadline_raw' not in item:
                    item['deadline_raw'] = deadline

if fixed_count > 0:
    logger.warning(f"[AI Response] ⚠️  Fixed {fixed_count} invalid deadline format(s)")
else:
    logger.warning(f"[AI Response] ✅ All deadline formats valid")
```

**Testing**:
- Look for log messages:
  - `[AI Response] ⚠️  Fixing invalid deadline format for '...'` (if AI returns bad format)
  - `[AI Response] ⚠️  Fixed X invalid deadline format(s)` (summary)
  - `[AI Response] ✅ All deadline formats valid` (if no issues)

---

### Issue #4: Missing Consolidation Tracking

**Problem**:
- Hard to debug consolidation issues without clear logging
- Can't tell when consolidation happens or how many events were consolidated

**Solution**:
- ✅ Added detailed logging to pre-AI consolidation
- ✅ Added note that post-AI consolidation is skipped
- ✅ Logs show input/output counts

**Code Changes**:
- Pre-AI logging ([canon.py:1655-1657](app/services/canon.py:1655-1657))
- Post-AI skip message ([canon.py:1779](app/services/canon.py:1779))

---

## 🔄 Processing Flow (After Fixes)

### Before Fixes (BROKEN):
```
1. Fetch calendar events
2. Filter and deduplicate
3. Consolidate recurring events (GOOD)
4. Send to AI
5. AI returns timeline (strips deadline_raw)
6. Try to consolidate AGAIN (FAILS - no deadline_raw)
7. Save broken timeline
```

### After Fixes (CORRECT):
```
1. Fetch calendar events
2. Filter and deduplicate
3. [Stage 6.5] Consolidate recurring events (ONLY ONCE)
   - Logs: "Running PRE-AI recurring consolidation"
   - "Trade with Chase" 3 instances → 1 consolidated event
4. Send consolidated events to AI
5. AI returns timeline
6. [FIX #2] Restore deadline_raw from original events
   - Logs: "Restored deadline_raw to X events"
7. [FIX #3] Validate and fix deadline formats
   - Logs: "Fixed X invalid deadline format(s)" OR "All deadline formats valid"
8. Save correct timeline
   - "Trade with Chase" appears once (recurring)
   - All timestamps preserved
   - No "Invalid Date" errors
```

---

## 📊 Expected Log Output

### Successful Run (No Invalid Formats):
```
[Stage 6.5] 🔄 Running PRE-AI recurring consolidation
[Stage 6.5] ✅ Consolidation complete: 15 → 12 events
... (AI processing) ...
[AI Response] ✅ Restored deadline_raw to 8 events
[AI Response] ✅ All deadline formats valid
[Timeline] ℹ️  Skipping post-AI consolidation (already done pre-AI)
```

### With Invalid Formats (AI Misbehaved):
```
[Stage 6.5] 🔄 Running PRE-AI recurring consolidation
[Stage 6.5] ✅ Consolidation complete: 15 → 12 events
... (AI processing) ...
[AI Response] ✅ Restored deadline_raw to 8 events
[AI Response] ⚠️  Fixing invalid deadline format for 'Meeting with Bob': 2026-01-02T14:00:00-08:00
[AI Response] ⚠️  Fixing invalid deadline format for 'Project Review': 2026-01-03T10:00:00-08:00
[AI Response] ⚠️  Fixed 2 invalid deadline format(s)
[Timeline] ℹ️  Skipping post-AI consolidation (already done pre-AI)
```

---

## 🧪 Testing Checklist

### Test 1: Recurring Events Consolidate Correctly

**Setup**:
- Add 3 instances of "Trade with Chase" calendar event at different times
- Ensure they have identical titles and locations

**Expected Behavior**:
- ✅ Only ONE "Trade with Chase" appears in timeline
- ✅ Shows as recurring event with `is_recurring: true`
- ✅ All 3 instances listed in `all_instances` array
- ✅ Timeline shows count: "(3 events)"

**Logs to Check**:
```
[Stage 6.5] 🔄 Running PRE-AI recurring consolidation
[Stage 6.5] ✅ Consolidation complete: 15 → 13 events  # 3 consolidated to 1
[Timeline] ℹ️  Skipping post-AI consolidation (already done pre-AI)
```

---

### Test 2: deadline_raw Fields Preserved

**Setup**:
- Add calendar event with specific time (e.g., "Meeting at 2pm")
- Check timeline after AI processing

**Expected Behavior**:
- ✅ Event has `deadline_raw` field with ISO timestamp
- ✅ Event has `deadline` field with human-readable text
- ✅ Frontend can parse and display correctly

**Logs to Check**:
```
[AI Response] ✅ Restored deadline_raw to X events  # X > 0
```

**Database/API Check**:
```json
{
  "title": "Meeting at 2pm",
  "deadline": "Due in 3 hours",
  "deadline_raw": "2026-01-02T14:00:00-08:00",  // ← Should exist
  "source_id": "calendar_event_123"
}
```

---

### Test 3: No "Invalid Date" Errors

**Setup**:
- Create several calendar events
- Refresh timeline
- Check frontend display

**Expected Behavior**:
- ✅ All events show human-readable times ("Due in X hours")
- ❌ NO "Invalid Date" text anywhere
- ❌ NO ISO timestamp strings visible to user

**Logs to Check** (if AI misbehaves):
```
[AI Response] ⚠️  Fixing invalid deadline format for '...': 2026-01-02T...
[AI Response] ⚠️  Fixed 2 invalid deadline format(s)
```

**Logs to Check** (if AI behaves):
```
[AI Response] ✅ All deadline formats valid
```

---

### Test 4: Different-Time Events NOT Consolidated

**Setup**:
- Add 2 "Actionable time" events at DIFFERENT times:
  - "Actionable time" at 6:30am
  - "Actionable time" at 7:00am

**Expected Behavior**:
- ✅ Both events appear separately (NOT consolidated)
- ✅ Consolidation only happens for SAME time + SAME title + SAME location
- ✅ Different times = different events

**Why**: Events at different times serve different purposes and shouldn't be merged.

---

## 🐛 Troubleshooting

### Problem: Events Still Showing Multiple Times

**Symptom**: "Trade with Chase" appears 3 times instead of once

**Diagnosis**:
```bash
# Check logs for consolidation
grep "Running PRE-AI recurring consolidation" logs/app.log
grep "Consolidation complete" logs/app.log
```

**Expected**: Should see exactly ONE consolidation happening (pre-AI)

**If Not Fixed**:
- Check that post-AI consolidation is truly removed
- Verify `deadline_raw` fields are being restored
- Check that events have matching `source_id` values

---

### Problem: "Invalid Date" Still Appearing

**Symptom**: Frontend shows "Invalid Date" text

**Diagnosis**:
```bash
# Check for invalid format warnings
grep "Fixing invalid deadline format" logs/app.log
grep "All deadline formats valid" logs/app.log
```

**If No Warnings**: AI is behaving correctly, check frontend parsing

**If Warnings Present**: Validation is working, check:
1. Frontend is receiving fixed timeline (not cached old version)
2. Deadline conversion logic handles all edge cases

---

### Problem: deadline_raw Missing

**Symptom**: Events missing `deadline_raw` field in API response

**Diagnosis**:
```bash
# Check restoration logs
grep "Restored deadline_raw" logs/app.log
```

**Expected**: `Restored deadline_raw to X events` where X > 0

**If X = 0**:
- Original events might not have `deadline_raw` (check calendar fetch)
- `source_id` matching might be failing (check event IDs)

---

### Problem: Too Many Consolidation Logs

**Symptom**: Logs show consolidation happening multiple times

**Diagnosis**:
```bash
# Count consolidation occurrences
grep -c "Running PRE-AI recurring consolidation" logs/app.log
grep -c "Skipping post-AI consolidation" logs/app.log
```

**Expected**:
- "Running PRE-AI..." should appear ONCE per timeline generation
- "Skipping post-AI..." should appear ONCE per timeline generation

**If More**: Post-AI consolidation might not be fully removed

---

## 📝 Code Changes Summary

### Files Modified

1. **app/services/canon.py**
   - Line 1655-1657: Added pre-AI consolidation logging
   - Line 1715-1741: Added deadline_raw restoration
   - Line 1743-1799: Added deadline format validation
   - Line 1777-1779: Removed post-AI consolidation (replaced with skip message)

### Lines Changed

- **Added**: ~60 lines (restoration + validation)
- **Removed**: ~90 lines (post-AI consolidation)
- **Modified**: ~3 lines (logging)
- **Net Change**: -27 lines (code reduction is good!)

---

## ✅ Success Criteria

After deploying these fixes, you should see:

1. ✅ **Consolidation happens once**
   - Logs show "Running PRE-AI recurring consolidation" exactly once
   - Logs show "Skipping post-AI consolidation"

2. ✅ **Recurring events display correctly**
   - "Trade with Chase" appears once (not 3 times)
   - Shows as recurring with instance count
   - All instances accessible in timeline

3. ✅ **Timestamps preserved**
   - All events have `deadline_raw` field
   - Logs show "Restored deadline_raw to X events"
   - X matches number of calendar events

4. ✅ **No invalid date errors**
   - Frontend displays human-readable times
   - No ISO timestamps visible to users
   - Logs show "All deadline formats valid" or auto-fixes applied

5. ✅ **Different-time events separate**
   - "Actionable time" at 6:30am and 7:00am appear separately
   - Consolidation only merges identical time+title+location

---

## 🚀 Deployment

### Pre-Deployment Checklist

- [x] Remove post-AI consolidation code
- [x] Add pre-AI consolidation logging
- [x] Add deadline_raw restoration logic
- [x] Add deadline format validation
- [x] Test with sample recurring events

### Deployment Steps

1. **Deploy backend** with updated canon.py
2. **Monitor logs** for first timeline generation:
   ```bash
   tail -f logs/app.log | grep -E "Stage 6.5|AI Response|Timeline"
   ```
3. **Verify log output**:
   - See "Running PRE-AI recurring consolidation"
   - See "Restored deadline_raw to X events"
   - See "All deadline formats valid" (or fixes applied)
   - See "Skipping post-AI consolidation"
4. **Test frontend**:
   - Check timeline displays recurring events correctly
   - Verify no "Invalid Date" errors
   - Confirm different-time events not consolidated

### Rollback Plan

If issues occur, revert to previous version and investigate:

```bash
git revert HEAD
git push origin main
```

Then check:
- Which specific fix is causing the issue
- Whether logs show expected messages
- If validation logic has edge cases

---

**Implementation Date**: 2026-01-01
**Implemented By**: Claude Sonnet 4.5
**Status**: Ready for Production Testing
