# Canon Worker Debug Guide

## Overview

The Canon Worker is a background job that automatically refreshes users' timelines by:
1. Fetching latest Gmail emails
2. Fetching upcoming Calendar events
3. Sending to OpenAI GPT-4 to categorize into timeline (1d/7d/28d)
4. Auto-adding new items to the user's canonical plan

---

## Quick Diagnostic Checklist

### 1. Is the Worker Starting?

**Check production logs for:**
```
🔄 [Canon Worker] ════════════════════════════════════════
🔄 [Canon Worker] 🚀 STARTED (interval: 15 minutes)
🔄 [Canon Worker] 📅 Next run: 2025-12-22 10:15:00
```

**If you DON'T see this:**
- Worker failed to start at server startup
- Check for startup errors: `grep -i "startup.*canon\|failed to start" logs`
- Verify `@app.on_event("startup")` is being called

**If you DO see this:**
- Worker started successfully ✅
- Note the "Next run" timestamp

---

### 2. Is the Worker Running Cycles?

**Check logs every 15 minutes for:**
```
🔄 [Canon Worker] ════════════════════════════════════════
🔄 [Canon Worker] Cycle start: checking 3 canons at 2025-12-22T10:15:00
🔄 [Canon Worker] ════════════════════════════════════════
🔄 [Canon Worker] User sean@gmail.com: 45.2m since sync, interval=60m → REFRESHING
🔄 [Canon Worker]   📧 Fetched 12 emails, 📅 5 events
🔄 [Canon Worker]   ✅ Refreshed! Added 3 items to timeline
🔄 [Canon Worker] ════════════════════════════════════════
🔄 [Canon Worker] Cycle complete: ✅ 1 refreshed | ⏸️  0 disabled | ⏭️  2 too soon | ⚠️  0 OAuth issues | ❌ 0 errors
```

**If cycles are NOT running:**
- Scheduler started but jobs aren't executing
- Check if multiple processes are running (only one should have the scheduler)
- Verify APScheduler is installed: `pip show apscheduler`

**If you see "⚠️  OAuth issues":**
- User's Gmail/Calendar tokens expired
- Tokens need to be refreshed (see OAuth section below)

**If you see "❌ errors":**
- Check full error stacktrace in logs
- Likely AI generation or database issue

---

### 3. Check Worker Status via API

**Development/Admin Only:**

```bash
# Check if worker is running
curl "https://api.parallelos.ai/api/debug/canon-worker/status" \
  -H "Cookie: access_token=YOUR_TOKEN"

# Response if running:
{
  "status": "running",
  "next_run": "2025-12-22 10:30:00",
  "interval_minutes": 15,
  "trigger": "interval[0:15:00]",
  "all_jobs": ["canon_refresh_worker"]
}

# Response if NOT running:
{
  "status": "not_running",
  "message": "Canon worker job not found in scheduler",
  "all_jobs": []
}
```

---

### 4. Manually Trigger a Cycle (Debug)

**Force the worker to run NOW:**

```bash
curl -X POST "https://api.parallelos.ai/api/debug/canon-worker/trigger" \
  -H "Cookie: access_token=YOUR_TOKEN"

# Response:
{
  "status": "success",
  "message": "Canon worker cycle completed. Check logs for details."
}
```

Then immediately check logs for the cycle output.

---

## Configuration

### Environment Variables

**CANON_WORKER_INTERVAL_MINUTES** (default: 15)
- Controls how often the worker runs
- For debugging: Set to `1` minute
- Production: Keep at `15` or `60` minutes

Example:
```bash
export CANON_WORKER_INTERVAL_MINUTES=1  # Run every 1 minute for debugging
```

### User Preferences

Each user can set their own refresh interval via:

```bash
curl -X POST "https://api.parallelos.ai/api/settings/canon-refresh" \
  -H "Cookie: access_token=YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"interval_minutes": 60}'

# Allowed values: 0, 1, 15, 30, 60, 120, 360, 720, 1440
# 0 = disabled (user won't be auto-refreshed)
```

**Important:** The worker runs every `CANON_WORKER_INTERVAL_MINUTES` (e.g., 15min), but ONLY refreshes users whose `interval_minutes` preference has elapsed since their last sync.

Example:
- Worker runs every 15 minutes
- User A has interval=60 (refresh once per hour)
- User B has interval=15 (refresh every 15min)
- On each 15min cycle: User B gets refreshed, User A only every 4th cycle

---

## OAuth Token Issues

### Problem: "⚠️  OAuth failed: 401 oauth_expired"

**Root Cause:** User's Gmail/Calendar access tokens expired

**Check token status:**
```sql
SELECT
  user_id,
  provider,
  access_token IS NOT NULL as has_token,
  refresh_token IS NOT NULL as has_refresh,
  expires_at,
  NOW() > expires_at as is_expired
FROM external_accounts
WHERE provider IN ('google_gmail', 'google_calendar')
ORDER BY created_at DESC;
```

**If is_expired = true and has_refresh = true:**
- Token refresh should work automatically
- Check logs for "[OAuth] Refresh token request failed"
- May need to check GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars

**If has_refresh = false:**
- User must manually reconnect Gmail/Calendar
- Token refresh is impossible
- User sees: "Your Gmail connection expired. Please reconnect in Settings."

**Fix:**
1. User goes to Settings → Connections
2. Click "Reconnect Gmail" or "Reconnect Calendar"
3. Complete OAuth flow
4. New tokens stored with refresh_token

---

## Common Issues

### Issue 1: "Worker logs never appear"

**Symptoms:**
- No "🔄 [Canon Worker]" lines in logs
- Server starts without errors

**Diagnosis:**
1. Check startup logs: `grep -i "startup.*canon" logs`
2. Look for "[Startup] ✅ Canon worker started successfully"
3. If missing, startup hook failed

**Fix:**
- Verify `app/workers/canon_worker.py` exists
- Check for import errors: `python -c "from app.workers.canon_worker import start_canon_worker"`
- Ensure APScheduler is installed: `pip install APScheduler==3.10.4`

---

### Issue 2: "Worker starts but never runs cycles"

**Symptoms:**
- See "🚀 STARTED" log at startup
- Never see "Cycle start:" logs

**Diagnosis:**
1. Check if running multiple processes: `ps aux | grep uvicorn`
2. Verify interval: `echo $CANON_WORKER_INTERVAL_MINUTES`
3. Check scheduler: Use `/api/debug/canon-worker/status` endpoint

**Fix:**
- If multiple processes: Only one should run the scheduler
  - Use single Uvicorn process for debugging: `uvicorn main:app --host 0.0.0.0 --port 8000`
  - Or ensure only worker=1 in production config
- Wait for the interval to pass (default 15 minutes)
- Or manually trigger: `/api/debug/canon-worker/trigger`

---

### Issue 3: "All canons are empty despite worker running"

**Symptoms:**
- Worker logs show "✅ 1 refreshed"
- But timeline remains empty: `{"1d": {"critical": [], "high": []}, ...}`

**Diagnosis:**
1. Check if emails/events were fetched: Look for "📧 Fetched X emails, 📅 Y events"
2. If 0 emails and 0 events → OAuth issue
3. If emails/events fetched but timeline empty → AI generation issue

**Fix for OAuth:**
- See "OAuth Token Issues" section above

**Fix for AI generation:**
- Check OpenAI API key: `echo $OPENAI_API_KEY`
- Look for AI errors: `grep -i "openai\|gpt-4\|brief.*ai" logs`
- Verify model is accessible: GPT-4o-mini

---

### Issue 4: "TypeError: can't compare offset-naive and offset-aware datetimes"

**Symptoms:**
```
TypeError: can't compare offset-naive and offset-aware datetimes
  at line 73: if expires_at_aware and expires_at_aware < (now + timedelta(minutes=5)):
```

**Root Cause:** Database stores `expires_at` without timezone info, code expects timezone-aware

**Fix:** Already implemented! Worker now handles this:
```python
# In canon_worker.py line 66-69:
last_sync = canon.last_ai_sync
if last_sync.tzinfo is None:
    last_sync = last_sync.replace(tzinfo=timezone.utc)
```

Also in `app/services/gmail.py` and `app/services/calendar.py`:
```python
def _normalize_expires_at(value):
    if value and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
```

---

## Testing Workflow

### 1. Enable Debug Mode (1-minute intervals)

```bash
# On production server:
export CANON_WORKER_INTERVAL_MINUTES=1

# Restart server
```

### 2. Set User Preference to 1 minute

```bash
curl -X POST "https://api.parallelos.ai/api/settings/canon-refresh" \
  -H "Cookie: access_token=YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"interval_minutes": 1}'
```

### 3. Watch Logs in Real-Time

```bash
# Tail logs with canon worker filter
tail -f /path/to/logs | grep "Canon Worker"
```

### 4. Verify First Cycle (within 1 minute)

You should see:
```
🔄 [Canon Worker] ════════════════════════════════════════
🔄 [Canon Worker] Cycle start: checking 1 canons at 2025-12-22T10:01:00
🔄 [Canon Worker] User your-email@gmail.com: Never synced → REFRESHING
🔄 [Canon Worker]   📧 Fetched 12 emails, 📅 5 events
🔄 [Canon Worker]   ✅ Refreshed! Added 3 items to timeline
🔄 [Canon Worker] Cycle complete: ✅ 1 refreshed | ...
```

### 5. Check Canon via API

```bash
curl "https://api.parallelos.ai/api/canon" \
  -H "Cookie: access_token=YOUR_TOKEN"

# Should return populated timeline:
{
  "exists": true,
  "timeline": {
    "1d": {
      "critical": [
        {"title": "Fix production bug", "detail": "...", "signature": "abc123"}
      ],
      "high_priority": [...]
    },
    "7d": {...},
    "28d": {...}
  },
  "last_sync": "2025-12-22T10:01:30Z"
}
```

### 6. Verify Subsequent Cycles (every 1 minute)

On the second cycle (1 minute later):
```
🔄 [Canon Worker] Cycle start: checking 1 canons at 2025-12-22T10:02:00
🔄 [Canon Worker] User your-email@gmail.com: 1.0m since sync, interval=1m → REFRESHING
🔄 [Canon Worker]   📧 Fetched 12 emails, 📅 5 events
🔄 [Canon Worker]   ✅ Refreshed! Added 0 items to timeline  # 0 because no NEW items
```

### 7. Restore Production Settings

```bash
# Reset to normal interval
unset CANON_WORKER_INTERVAL_MINUTES  # Defaults to 15 minutes

# Reset user preference to hourly
curl -X POST "https://api.parallelos.ai/api/settings/canon-refresh" \
  -H "Cookie: access_token=YOUR_TOKEN" \
  -d '{"interval_minutes": 60}'

# Restart server
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│ STARTUP                                                 │
│  @app.on_event("startup")                               │
│    → start_canon_worker()                               │
│      → scheduler.add_job(refresh_stale_canons, 15min)  │
│      → scheduler.start()                                │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ BACKGROUND WORKER (runs every 15 min)                   │
│  refresh_stale_canons()                                 │
│    1. Query all UserCanonicalPlan records               │
│    2. For each canon:                                   │
│       a. Check user preferences (interval_minutes)      │
│       b. Skip if disabled (interval=0)                  │
│       c. Skip if too soon (< interval elapsed)          │
│       d. Fetch Gmail emails ───────────────────────┐   │
│       e. Fetch Calendar events                      │   │
│       f. Call generate_recommendations()            │   │
│          → _generate_personal_brief_with_ai()       │   │
│             → OpenAI GPT-4o-mini                    │   │
│             → Returns timeline {1d, 7d, 28d}        │   │
│       g. Auto-add items to approved_timeline        │   │
│       h. Update last_ai_sync timestamp              │   │
│       i. Commit to database                          │   │
│    3. Log cycle summary                              │   │
└──────────────────────────────────────────────────────┘   │
                                                           │
┌──────────────────────────────────────────────────────────┘
│ OAuth Token Refresh (if needed)
│  _get_valid_token(user, db)
│    1. Check if expires_at < NOW + 5min
│    2. If expired: Call refresh_access_token()
│       → POST https://oauth2.googleapis.com/token
│       → Update access_token and expires_at in DB
│    3. Return valid token
│    4. If fails: Raise HTTPException("oauth_expired")
└─────────────────────────────────────────────────────────┘
```

---

## Logs to Expect

### Successful Startup
```
[Startup] Using Postgres - skipping create_all
🔄 [Canon Worker] ════════════════════════════════════════
🔄 [Canon Worker] 🚀 STARTED (interval: 15 minutes)
🔄 [Canon Worker] 📅 Next run: 2025-12-22 10:15:00.123456+00:00
🔄 [Canon Worker] 🔧 To debug, set CANON_WORKER_INTERVAL_MINUTES=1
🔄 [Canon Worker] ════════════════════════════════════════
[Startup] ✅ Canon worker started successfully
[Startup] ===== SERVER READY (Database: postgresql) =====
```

### Successful Refresh Cycle
```
🔄 [Canon Worker] ════════════════════════════════════════
🔄 [Canon Worker] Cycle start: checking 3 canons at 2025-12-22T10:15:00.123456+00:00
🔄 [Canon Worker] ════════════════════════════════════════
🔄 [Canon Worker] User sean@gmail.com: 45.2m since sync, interval=60m → REFRESHING
🔄 [Canon Worker]   📧 Fetched 12 emails, 📅 5 events
🔄 [Canon Worker]   ✅ Refreshed! Added 3 items to timeline
🔄 [Canon Worker] ════════════════════════════════════════
🔄 [Canon Worker] Cycle complete: ✅ 1 refreshed | ⏸️  0 disabled | ⏭️  2 too soon | ⚠️  0 OAuth issues | ❌ 0 errors
🔄 [Canon Worker] ════════════════════════════════════════
```

### OAuth Token Refresh
```
[OAuth] Token expired for user abc-123, attempting refresh...
[OAuth] ✅ Successfully refreshed token for user abc-123
```

### OAuth Failure
```
[OAuth] User abc-123 has no google_gmail account
🔄 [Canon Worker]   ⚠️  OAuth failed: 401 {"error": "oauth_not_connected", ...}
```

### AI Generation
```
[Personal Brief AI] Input: 12 emails, 5 events
[Personal Brief AI] Email context length: 1234 chars
[Personal Brief AI] Calendar context length: 567 chars
[Personal Brief AI] Calling OpenAI...
[Personal Brief AI] OpenAI response length: 890 chars
[Personal Brief AI] ✅ JSON parsed successfully
[Personal Brief AI] Priorities: 4
[Personal Brief AI] Timeline 1D: 2 critical
[Personal Brief AI] Timeline 7D: 3 milestones
[Personal Brief AI] Timeline 28D: 1 goals
```

---

## Summary

**✅ You're all set if you see:**
1. Startup log: "🚀 STARTED (interval: X minutes)"
2. Cycle logs every X minutes: "Cycle start: checking N canons"
3. Refresh logs: "✅ Refreshed! Added X items"
4. API returns populated timeline

**❌ Debug if you see:**
1. No startup log → Worker failed to start (check imports/APScheduler)
2. No cycle logs → Scheduler not running (check multiple processes)
3. "⚠️  OAuth failed" → Token expired (reconnect Gmail/Calendar)
4. "❌ errors" → Check stacktrace for specific error

**🔧 Tools:**
- `/api/debug/canon-worker/status` - Check if running
- `/api/debug/canon-worker/trigger` - Force manual cycle
- `CANON_WORKER_INTERVAL_MINUTES=1` - Debug mode (1min interval)
- `grep "Canon Worker" logs` - Filter worker logs

**📞 Need Help?**
- Check production logs for exact error message
- Use debug endpoints to verify worker status
- Manually trigger a cycle to see immediate results
- Verify OAuth tokens in database
