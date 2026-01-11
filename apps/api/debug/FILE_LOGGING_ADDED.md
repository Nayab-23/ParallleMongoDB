# File-Based Logging for Timeline Diagnostics

## Summary

Added rotating file-based logging to solve Render's terrible log viewer. All timeline diagnostic logs are now saved to a downloadable file with API endpoints for viewing and management.

**Status**: COMPLETE - Ready for testing
**Problem Solved**: Render's log viewer truncates logs, making it impossible to see complete diagnostic output
**Solution**: All WARNING-level logs from timeline generation are saved to a persistent file

---

## What Was Added

### 1. File Handler in canon.py (Lines 29-54)

**Location**: `/Users/severinspagnola/Desktop/MongoDBHack/apps/api/app/services/canon.py`

Added rotating file handler that:
- Saves all WARNING+ logs to `logs/timeline_diagnostics.log`
- Rotates at 10MB (keeps 5 backup files)
- Includes timestamps in format: `YYYY-MM-DD HH:MM:SS - module - LEVEL - message`
- Created automatically on first import

**Key Features**:
```python
# Rotating file handler (max 10MB, keep 5 backups)
file_handler = RotatingFileHandler(
    timeline_log_file,
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
```

### 2. Three New Debug API Endpoints in main.py

**Location**: `/Users/severinspagnola/Desktop/MongoDBHack/apps/api/main.py` (Lines 8141-8238)

All endpoints require admin privileges (`is_platform_admin = True`).

---

## API Endpoints

### 1. Download Complete Log File

**Endpoint**: `GET /api/debug/timeline-logs`

**Purpose**: Download the entire timeline diagnostic log file

**Response**: File download (text/plain)

**Example**:
```bash
curl -X GET "https://your-api.com/api/debug/timeline-logs" \
  --cookie "session=your-session-cookie" \
  --output timeline_diagnostics.log
```

**Use Case**: Get complete logs for local analysis, searching, or archiving

---

### 2. View Last N Lines (Tail)

**Endpoint**: `GET /api/debug/timeline-logs/tail?lines=500`

**Purpose**: View the most recent log entries without downloading entire file

**Parameters**:
- `lines` (optional, default=500): Number of recent lines to return

**Response**:
```json
{
  "logs": "2026-01-01 15:03:42 - app.services.canon - WARNING - [Timeline Input] STARTING...\n...",
  "total_lines": 2847,
  "showing_lines": 500
}
```

**Example**:
```bash
# Get last 100 lines
curl -X GET "https://your-api.com/api/debug/timeline-logs/tail?lines=100" \
  --cookie "session=your-session-cookie"

# Get last 1000 lines
curl -X GET "https://your-api.com/api/debug/timeline-logs/tail?lines=1000" \
  --cookie "session=your-session-cookie"
```

**Use Case**: Quick check of recent activity without downloading full file

---

### 3. Clear Log File

**Endpoint**: `POST /api/debug/timeline-logs/clear`

**Purpose**: Delete the log file to start fresh

**Response**:
```json
{
  "status": "cleared",
  "message": "Log file deleted"
}
```

**Example**:
```bash
curl -X POST "https://your-api.com/api/debug/timeline-logs/clear" \
  --cookie "session=your-session-cookie"
```

**Use Case**: Clear logs before running a specific test to isolate new log entries

---

## Usage Workflow

### Testing Timeline Diagnostics

1. **Clear existing logs** (optional):
```bash
POST /api/debug/timeline-logs/clear
```

2. **Trigger a timeline refresh**:
- Click 🔄 Refresh button in Intelligence tab
- Or wait for automatic refresh (within 1 minute)

3. **Check recent logs**:
```bash
GET /api/debug/timeline-logs/tail?lines=200
```

4. **Download complete file** (if needed):
```bash
GET /api/debug/timeline-logs
```

5. **Search locally**:
```bash
grep "Actionable time" timeline_diagnostics.log
grep "STAGE" timeline_diagnostics.log
grep "LOSS REPORT" timeline_diagnostics.log
```

---

## What Gets Logged

All stage-by-stage diagnostic logging from the pipeline:

### Stage 0: Initial
```
2026-01-01 15:03:42 - app.services.canon - WARNING - ================================================================================
2026-01-01 15:03:42 - app.services.canon - WARNING - 🔍 [STAGE 0: Initial] ITEM COUNTS:
2026-01-01 15:03:42 - app.services.canon - WARNING - [STAGE 0: Initial] Total: 31
2026-01-01 15:03:42 - app.services.canon - WARNING - [STAGE 0: Initial]   - Calendar: 31
2026-01-01 15:03:42 - app.services.canon - WARNING - [STAGE 0: Initial]   - Email: 0
2026-01-01 15:03:42 - app.services.canon - WARNING - [STAGE 0: Initial] 🎯 'Actionable time': 9
2026-01-01 15:03:42 - app.services.canon - WARNING - [STAGE 0: Initial] === ALL 'Actionable time' ITEMS ===
2026-01-01 15:03:42 - app.services.canon - WARNING - [STAGE 0: Initial]   1. Actionable time
2026-01-01 15:03:42 - app.services.canon - WARNING - [STAGE 0: Initial]      Source ID: abc123def456
...
```

### Loss Reports
```
2026-01-01 15:03:43 - app.services.canon - WARNING - ⚠️ LOSS REPORT: Stage 0 → Stage 1: Lost 0 items
2026-01-01 15:03:44 - app.services.canon - WARNING - ⚠️ LOSS REPORT: Stage 1 → Stage 2: Lost 0 items
2026-01-01 15:03:45 - app.services.canon - WARNING - ⚠️ LOSS REPORT: Stage 4 → Stage 5: Lost 19 items (past events)
```

### Final Stage
```
2026-01-01 15:03:46 - app.services.canon - WARNING - 🤖 [STAGE FINAL] === COMPLETE LIST SENT TO AI ===
2026-01-01 15:03:46 - app.services.canon - WARNING - [STAGE FINAL] Total items: 12
2026-01-01 15:03:46 - app.services.canon - WARNING - [STAGE FINAL]   - Emails: 0
2026-01-01 15:03:46 - app.services.canon - WARNING - [STAGE FINAL]   - Events: 12
2026-01-01 15:03:46 - app.services.canon - WARNING - [STAGE FINAL] ALL ITEMS BEING SENT TO AI:
2026-01-01 15:03:46 - app.services.canon - WARNING -   1. [calendar] Event Title
2026-01-01 15:03:46 - app.services.canon - WARNING -      Source ID: abc123
2026-01-01 15:03:46 - app.services.canon - WARNING -      Time: 2026-01-01T10:00:00Z
...
```

---

## File Rotation

**Max File Size**: 10MB
**Backup Count**: 5 files
**File Names**:
- `timeline_diagnostics.log` (current)
- `timeline_diagnostics.log.1` (previous)
- `timeline_diagnostics.log.2` (older)
- `timeline_diagnostics.log.3`
- `timeline_diagnostics.log.4`
- `timeline_diagnostics.log.5` (oldest)

When `timeline_diagnostics.log` reaches 10MB:
1. `.log.5` is deleted
2. `.log.4` → `.log.5`
3. `.log.3` → `.log.4`
4. `.log.2` → `.log.3`
5. `.log.1` → `.log.2`
6. `.log` → `.log.1`
7. New `.log` file created

---

## Local Development

On your local machine, logs are saved to:
```
/Users/severinspagnola/Desktop/MongoDBHack/apps/api/logs/timeline_diagnostics.log
```

**View logs locally**:
```bash
# Tail the log file
tail -f logs/timeline_diagnostics.log

# Search for specific stages
grep "STAGE" logs/timeline_diagnostics.log

# Search for "Actionable time"
grep -i "actionable time" logs/timeline_diagnostics.log

# Count loss events
grep "LOSS REPORT" logs/timeline_diagnostics.log | wc -l
```

---

## Production (Render)

On Render, logs are saved to the ephemeral filesystem at:
```
/opt/render/project/src/logs/timeline_diagnostics.log
```

**Important**: Render's filesystem is ephemeral, so logs will be lost on:
- Deploys
- Instance restarts
- Scaling events

**Solution**: Download logs regularly or use the `/tail` endpoint to monitor

---

## Security

All endpoints require:
1. Valid authenticated session (cookie)
2. Admin privileges (`is_platform_admin = True`)

Non-admin users will receive:
```json
{
  "detail": "Admin only"
}
```

---

## Benefits

### ✅ Complete Logs
- No truncation from Render's log viewer
- Full diagnostic output with all stages

### ✅ Searchable
- Download and use grep, awk, or text editor
- Search for specific events, stages, or patterns

### ✅ Downloadable
- Save logs locally for analysis
- Share with team or support

### ✅ Tail Support
- Quick view of recent activity
- No need to download full file for recent checks

### ✅ Rotating
- Automatic cleanup (keeps 5 backups)
- Won't fill disk space

### ✅ Timestamped
- Every log entry has exact timestamp
- Track processing duration

---

## Troubleshooting

### "Log file not found"

**Cause**: No timeline refresh has occurred yet, or file was cleared

**Solution**: Trigger a refresh first
```bash
# In frontend: Click 🔄 Refresh button
# Or wait for automatic refresh
```

### "Admin only" error

**Cause**: Current user doesn't have admin privileges

**Solution**: Log in as admin user or set `is_platform_admin = True` in database

### Empty log file

**Cause**: No WARNING-level logs generated yet

**Solution**: Wait for timeline generation to complete (logs appear during processing)

---

## Files Modified

1. **app/services/canon.py**:
   - Lines 9: Added `from logging.handlers import RotatingFileHandler`
   - Lines 29-54: Added file logging setup

2. **main.py**:
   - Lines 8141-8170: Added `/debug/timeline-logs` endpoint (download)
   - Lines 8173-8210: Added `/debug/timeline-logs/tail` endpoint (view last N lines)
   - Lines 8213-8238: Added `/debug/timeline-logs/clear` endpoint (clear logs)

3. **logs/** directory:
   - Created directory for log storage
   - Added README.txt

---

## Next Steps

1. **Test locally**:
```bash
# Start the backend
uvicorn main:app --reload

# Trigger a timeline refresh
# Check logs/timeline_diagnostics.log exists

# View last 100 lines
curl http://localhost:8000/api/debug/timeline-logs/tail?lines=100
```

2. **Deploy to Render**:
```bash
git add .
git commit -m "Add file-based logging for timeline diagnostics"
git push
```

3. **Test in production**:
```bash
# Trigger refresh
# Download logs
curl https://your-api.com/api/debug/timeline-logs > production_logs.log

# Search for "Actionable time" loss
grep -i "actionable time" production_logs.log
grep "LOSS REPORT" production_logs.log
```

---

## Example: Finding "Actionable time" Loss

1. **Clear logs**:
```bash
POST /api/debug/timeline-logs/clear
```

2. **Trigger refresh** (click 🔄 in UI)

3. **Download logs**:
```bash
GET /api/debug/timeline-logs
```

4. **Search locally**:
```bash
# Find all "Actionable time" references
grep -i "actionable time" timeline_diagnostics.log

# Find where count drops
grep "Actionable time.*:" timeline_diagnostics.log

# Expected output:
# [STAGE 0] 🎯 'Actionable time': 9
# [STAGE 1] 🎯 'Actionable time': 9
# [STAGE 2] 🎯 'Actionable time': 9
# [STAGE 5] 🎯 'Actionable time': 0  ← FOUND IT!
```

5. **Check loss report for Stage 5**:
```bash
grep "Stage 4 → Stage 5" timeline_diagnostics.log

# Output:
# ⚠️ LOSS REPORT: Stage 4 → Stage 5: Lost 19 items (past events)
```

6. **Conclusion**: "Actionable time" events are being filtered as **past events** in the time-based filter stage!
