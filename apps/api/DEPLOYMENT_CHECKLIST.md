# Deployment Checklist - Timeline Diagnostics + File Logging

## Summary

Two major features added:
1. **Stage-by-stage diagnostic logging** - Track where items are lost in pipeline
2. **File-based logging** - Save logs to downloadable file (solves Render's terrible log viewer)

---

## Changes Made

### 1. app/services/canon.py

**Lines 9**: Added import
```python
from logging.handlers import RotatingFileHandler
```

**Lines 29-54**: File logging setup
- Creates `logs/` directory
- Sets up rotating file handler (10MB max, 5 backups)
- All WARNING+ logs saved to `logs/timeline_diagnostics.log`

**Lines 914-940**: Diagnostic helper function
- `count_items()` tracks counts at each stage
- Shows total, calendar, email, and "Actionable time" counts
- Lists all "Actionable time" items with source IDs

**Lines 936-1030**: Stage-by-stage tracking
- Stage 0: Initial (raw events + emails)
- Stage 1: After source_id dedup
- Stage 2: After similar events dedup
- Stage 3: After prep events dedup
- Stage 4: After semantic dedup
- Stage 5: After time-based filter (past events removed)
- Stage 6: After deletion pattern filter
- Stage FINAL: Complete list sent to AI with full details

**Loss Reports**: After each stage
- Shows how many items lost
- Identifies which filter is responsible

---

### 2. main.py

**Lines 8141-8170**: Download log file endpoint
```
GET /api/debug/timeline-logs
```
Returns: File download (text/plain)

**Lines 8173-8210**: Tail log file endpoint
```
GET /api/debug/timeline-logs/tail?lines=500
```
Returns: JSON with last N lines

**Lines 8213-8238**: Clear log file endpoint
```
POST /api/debug/timeline-logs/clear
```
Returns: Status message

---

## Deployment Steps

### 1. Commit Changes
```bash
git add .
git commit -m "Add timeline diagnostics + file logging

- Stage-by-stage pipeline tracking (7 stages)
- Track 'Actionable time' events with source IDs
- Loss reports at each stage
- File-based logging (rotating, 10MB max)
- Download/tail/clear log endpoints
- Solves Render's log truncation issue"
git push
```

### 2. Verify Deployment on Render
- Check build logs for successful deployment
- Look for: `[File Logging] Timeline diagnostics will be saved to:` message

### 3. Test File Logging
```bash
# Trigger a timeline refresh (click 🔄 in UI)

# Check last 100 lines
curl https://your-api.com/api/debug/timeline-logs/tail?lines=100 \
  --cookie "session=your-session-cookie"

# Should see STAGE 0-6 logs with item counts
```

### 4. Download Complete Logs
```bash
# Download full file
curl https://your-api.com/api/debug/timeline-logs \
  --cookie "session=your-session-cookie" \
  --output timeline_diagnostics.log

# Search for "Actionable time"
grep -i "actionable time" timeline_diagnostics.log

# Find loss reports
grep "LOSS REPORT" timeline_diagnostics.log
```

---

## Expected Log Output

### On Timeline Refresh

You should see:

1. **File Logging Initialization** (on server start):
```
[File Logging] Timeline diagnostics will be saved to: /opt/render/project/src/logs/timeline_diagnostics.log
```

2. **Timeline Input** (start of generation):
```
🔥 [Timeline Input] STARTING for USER: severin.spagnola@sjsu.edu
[Timeline Input] TOTAL CALENDAR EVENTS: 31
[Timeline Input] TOTAL EMAILS: 0
```

3. **Stage 0** (initial):
```
🔍 [STAGE 0: Initial] ITEM COUNTS:
[STAGE 0: Initial] Total: 31
[STAGE 0: Initial]   - Calendar: 31
[STAGE 0: Initial]   - Email: 0
[STAGE 0: Initial] 🎯 'Actionable time': 9
[STAGE 0: Initial] === ALL 'Actionable time' ITEMS ===
[STAGE 0: Initial]   1. Actionable time
[STAGE 0: Initial]      Source ID: abc123...
```

4. **Loss Reports**:
```
⚠️ LOSS REPORT: Stage 0 → Stage 1: Lost 0 items
⚠️ LOSS REPORT: Stage 1 → Stage 2: Lost 0 items
⚠️ LOSS REPORT: Stage 2 → Stage 3: Lost 0 items
⚠️ LOSS REPORT: Stage 3 → Stage 4: Lost 0 items
⚠️ LOSS REPORT: Stage 4 → Stage 5: Lost 19 items (past events)
⚠️ LOSS REPORT: Stage 5 → Stage 6: Lost 0 items (filtered by deletion patterns)
```

5. **Final Stage**:
```
🤖 [STAGE FINAL] === COMPLETE LIST SENT TO AI ===
[STAGE FINAL] Total items: 12
[STAGE FINAL] ALL ITEMS BEING SENT TO AI:
  1. [calendar] Event Title
     Source ID: abc123
     Time: 2026-01-01T10:00:00Z
...
⚠️ FINAL LOSS REPORT: Stage 0 → Final: Lost 19 total items
```

---

## Troubleshooting

### Issue: "Log file not found"

**Cause**: Timeline hasn't been generated yet

**Solution**: Trigger a refresh first (click 🔄 button)

---

### Issue: "Admin only" error

**Cause**: User is not admin

**Solution**: Set `is_platform_admin = True` in database:
```sql
UPDATE users SET is_platform_admin = true WHERE email = 'severin.spagnola@sjsu.edu';
```

---

### Issue: Logs are empty

**Cause**: No WARNING-level logs generated

**Solution**: Wait for timeline generation to complete

---

### Issue: Can't find where "Actionable time" is lost

**Steps**:
1. Clear logs: `POST /api/debug/timeline-logs/clear`
2. Trigger refresh
3. Download logs: `GET /api/debug/timeline-logs`
4. Search: `grep "Actionable time" timeline_diagnostics.log`
5. Compare counts across stages:
   - Stage 0: 9 items
   - Stage 1: ? items
   - Stage 2: ? items
   - ...
   - Stage where it drops to 0 = culprit

---

## Success Criteria

After deployment, you should be able to:

✅ Trigger a timeline refresh
✅ Download complete diagnostic logs via API
✅ View last 500 lines without downloading
✅ See stage-by-stage item counts
✅ See all "Actionable time" events with source IDs
✅ See loss reports showing items lost at each stage
✅ Identify exact stage where "Actionable time" events disappear
✅ Clear logs for fresh testing

---

## What This Solves

### Problem 1: Render's Log Viewer
- **Before**: Logs truncated, incomplete, hard to read
- **After**: Complete logs saved to file, downloadable via API

### Problem 2: Missing Items
- **Before**: 31 events → 12 items, no visibility into why
- **After**: Stage-by-stage tracking shows exactly where items are lost

### Problem 3: "Actionable time" Mystery
- **Before**: 9 "Actionable time" events disappear, no idea why
- **After**: Track them through all 7 stages, see source IDs, find exact stage where they're filtered

---

## Documentation

See these files for complete details:
- `DIAGNOSTIC_LOGGING_ADDED.md` - Stage-by-stage logging details
- `FILE_LOGGING_ADDED.md` - File logging system details
- `TIMELINE_INVESTIGATION_REPORT.md` - Original investigation notes

---

## Next Actions

1. **Deploy** - Push to Render
2. **Test** - Trigger refresh and download logs
3. **Analyze** - Find where "Actionable time" events are lost
4. **Report** - Share findings (do not fix yet, per instructions)
5. **Decide** - Based on findings, decide if filtering is correct or needs adjustment
