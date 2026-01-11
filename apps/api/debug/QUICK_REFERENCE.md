# Quick Reference - Timeline Diagnostics

## Fast Debugging Workflow

### 1. Clear Logs (Start Fresh)
```bash
curl -X POST "https://your-api.com/api/debug/timeline-logs/clear" \
  --cookie "session=your-cookie"
```

### 2. Trigger Timeline Refresh
- Click 🔄 Refresh button in Intelligence tab
- Or wait 1 minute for auto-refresh

### 3. View Recent Logs
```bash
# Last 100 lines
curl "https://your-api.com/api/debug/timeline-logs/tail?lines=100" \
  --cookie "session=your-cookie" | jq -r '.logs'

# Last 500 lines (default)
curl "https://your-api.com/api/debug/timeline-logs/tail" \
  --cookie "session=your-cookie" | jq -r '.logs'
```

### 4. Download Complete File
```bash
curl "https://your-api.com/api/debug/timeline-logs" \
  --cookie "session=your-cookie" \
  --output timeline.log
```

### 5. Search Locally
```bash
# Find "Actionable time" counts at each stage
grep "Actionable time.*:" timeline.log

# Find loss reports
grep "LOSS REPORT" timeline.log

# Find specific stage
grep "STAGE 5" timeline.log

# Find final summary
grep "FINAL LOSS REPORT" timeline.log
```

---

## API Endpoints (Quick Copy/Paste)

### Download Logs
```
GET /api/debug/timeline-logs
```

### View Last N Lines
```
GET /api/debug/timeline-logs/tail?lines=100
```

### Clear Logs
```
POST /api/debug/timeline-logs/clear
```

---

## Search Patterns

### Find Item Counts
```bash
grep "ITEM COUNTS" timeline.log
```

### Find "Actionable time" Events
```bash
grep -i "actionable time" timeline.log
```

### Find Loss Reports
```bash
grep "LOSS REPORT" timeline.log
```

### Find Stage 5 (Time Filter)
```bash
grep "STAGE 5" timeline.log
```

### Find Items Sent to AI
```bash
grep "STAGE FINAL" timeline.log -A 50
```

---

## Expected Item Loss Pattern

Based on your report (31 events → 12 items):

```
Stage 0: Total: 31, Calendar: 31, Actionable time: 9
Stage 1: Total: 31, Calendar: 31, Actionable time: 9  (no loss)
Stage 2: Total: 31, Calendar: 31, Actionable time: 9  (no loss)
Stage 3: Total: 31, Calendar: 31, Actionable time: 9  (no loss)
Stage 4: Total: 31, Calendar: 31, Actionable time: 9  (no loss)
Stage 5: Total: 12, Calendar: 12, Actionable time: 0  (LOST 19 ITEMS!)
Stage 6: Total: 12, Calendar: 12, Actionable time: 0  (no change)
Final:   Total: 12, Calendar: 12, Actionable time: 0
```

**Conclusion**: Stage 5 (time-based filter) is removing "Actionable time" events as "past events"

---

## One-Liner Debug Commands

### Complete Investigation
```bash
# Clear → Wait 2 min → Download → Search
curl -X POST "https://api.com/api/debug/timeline-logs/clear" --cookie "session=x" && \
echo "Waiting 2 minutes for refresh..." && sleep 120 && \
curl "https://api.com/api/debug/timeline-logs" --cookie "session=x" -o timeline.log && \
echo "=== Actionable time counts ===" && grep "Actionable time.*:" timeline.log && \
echo "=== Loss reports ===" && grep "LOSS REPORT" timeline.log
```

### Quick Check (Last 200 Lines)
```bash
curl "https://api.com/api/debug/timeline-logs/tail?lines=200" --cookie "session=x" | jq -r '.logs' | grep -E "(STAGE|LOSS|Actionable)"
```

---

## Log File Locations

### Local Development
```
/Users/severinspagnola/Desktop/MongoDBHack/apps/api/logs/timeline_diagnostics.log
```

### Render Production
```
/opt/render/project/src/logs/timeline_diagnostics.log
```

---

## Stage Names Reference

| Stage | Name | What It Does |
|-------|------|--------------|
| 0 | Initial | Raw events + emails from API |
| 1 | source_id dedup | Remove exact duplicates by source_id |
| 2 | similar dedup | Remove similar events (e.g., 3x "Meeting") |
| 3 | prep dedup | Remove "Prepare for X" when X exists |
| 4 | semantic dedup | Remove semantically similar (AI embeddings) |
| 5 | time filter | Remove past events (already happened) |
| 6 | deletion filter | Remove events user repeatedly deleted |
| FINAL | To AI | Items actually sent to AI for categorization |

---

## Emojis in Logs (Easy Scanning)

- 🔥 = Timeline Input (start)
- 🔍 = Stage counts
- ⚠️ = Loss report
- 🎯 = "Actionable time" count
- 🤖 = Final stage (to AI)
- ✅ = Timeline Final (saved to DB)

---

## Common Issues & Quick Fixes

### "Admin only" Error
```sql
-- Run in database
UPDATE users SET is_platform_admin = true WHERE email = 'your@email.com';
```

### "Log file not found"
```bash
# Trigger a refresh first, then retry
# Logs are only created during timeline generation
```

### Empty Logs
```bash
# Wait for timeline generation to complete (can take 30-60 seconds)
```

---

## Files Modified

- `app/services/canon.py` - Added file logging + stage tracking
- `main.py` - Added 3 debug endpoints
- `logs/` - Created directory for log storage

---

## Documentation Files

- `FILE_LOGGING_ADDED.md` - Complete file logging documentation
- `DIAGNOSTIC_LOGGING_ADDED.md` - Complete stage tracking documentation
- `DEPLOYMENT_CHECKLIST.md` - Deployment and testing guide
- `QUICK_REFERENCE.md` - This file

---

## Support

If logs show unexpected behavior, check:
1. Are timestamps correct? (timezone issue)
2. Are source_ids present? (missing for "Actionable time"?)
3. Which stage loses most items? (that's the culprit)
4. What does the loss report say? (past events, deletion patterns, etc.)

Share the complete log file for detailed analysis.
