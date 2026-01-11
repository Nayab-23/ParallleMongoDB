# Deploy Canon Worker - Quick Guide

## What Changed

1. **Added 1-minute debug interval** in `.env`:
   ```bash
   CANON_WORKER_INTERVAL_MINUTES=1
   ```

2. **Fixed duplicate worker issue** in `app/workers/canon_worker.py`:
   - Added duplicate prevention check
   - Shows process ID in logs
   - Only first process starts the scheduler

## Deploy to Production

### Option 1: Via Render Dashboard

1. Go to Render Dashboard → Your Service → Environment
2. Add environment variable:
   - **Key**: `CANON_WORKER_INTERVAL_MINUTES`
   - **Value**: `1` (for debugging) or `15` (for production)
3. Click "Save Changes"
4. Render will automatically redeploy

### Option 2: Via Git Push

```bash
# Commit the changes
git add .env app/workers/canon_worker.py
git commit -m "Add 1-minute canon worker interval for debugging"
git push origin main
```

Render will auto-deploy from the git push.

## What to Expect in Logs

### On Startup (you'll see this ONCE now, not twice):

```
🔄 [Canon Worker] ════════════════════════════════════════
🔄 [Canon Worker] 🚀 STARTED (interval: 1 minutes)
🔄 [Canon Worker] 📅 Next run: 2025-12-23 01:25:56+00:00
🔄 [Canon Worker] 🔧 To debug, set CANON_WORKER_INTERVAL_MINUTES=1
🔄 [Canon Worker] ⚙️  Process ID: 12345
🔄 [Canon Worker] ════════════════════════════════════════
[Startup] ✅ Canon worker started successfully
```

**Note:** If you previously saw this message twice, you'll now see it only ONCE (duplicate prevention working).

### First Cycle (within 1 minute):

```
🔄 [Canon Worker] ════════════════════════════════════════
🔄 [Canon Worker] Cycle start: checking 3 canons at 2025-12-23T01:26:00
🔄 [Canon Worker] ════════════════════════════════════════
🔄 [Canon Worker] User sean@gmail.com: Never synced → REFRESHING
🔄 [Canon Worker]   📧 Fetched 12 emails, 📅 5 events
🔄 [Canon Worker]   ✅ Refreshed! Added 3 items to timeline
🔄 [Canon Worker] ════════════════════════════════════════
🔄 [Canon Worker] Cycle complete: ✅ 1 refreshed | ⏸️ 0 disabled | ⏭️ 2 too soon | ⚠️ 0 OAuth | ❌ 0 errors
🔄 [Canon Worker] ════════════════════════════════════════
```

### If OAuth Tokens Expired (common issue):

```
🔄 [Canon Worker] User sean@gmail.com: 45.2m since sync → REFRESHING
🔄 [Canon Worker]   ⚠️  OAuth failed: 401 {"error": "oauth_expired", ...}
```

**Fix:** User needs to reconnect Gmail/Calendar in Settings.

## Verify It's Working

### 1. Check Worker Status (via API)

```bash
curl "https://api.parallelos.ai/api/debug/canon-worker/status" \
  -H "Cookie: access_token=YOUR_TOKEN"
```

Expected response:
```json
{
  "status": "running",
  "next_run": "2025-12-23 01:26:00",
  "interval_minutes": 1
}
```

### 2. Manually Trigger a Cycle

```bash
curl -X POST "https://api.parallelos.ai/api/debug/canon-worker/trigger" \
  -H "Cookie: access_token=YOUR_TOKEN"
```

Response:
```json
{
  "status": "success",
  "message": "Canon worker cycle completed. Check logs for details."
}
```

### 3. Check Canon Content

```bash
curl "https://api.parallelos.ai/api/canon" \
  -H "Cookie: access_token=YOUR_TOKEN"
```

Should return populated timeline after 1-2 minutes.

## Troubleshooting

### Issue: "⚠️  OAuth failed"

**Cause:** Gmail/Calendar tokens expired

**Check:**
```sql
SELECT user_id, provider, expires_at, NOW() > expires_at as expired
FROM external_accounts
WHERE provider IN ('google_gmail', 'google_calendar');
```

**Fix:** User must reconnect Gmail/Calendar in Settings.

### Issue: Timeline still empty after 5 minutes

**Causes:**
1. OAuth tokens expired (see above)
2. User has no emails/events
3. AI generation failing

**Debug:**
- Check for "📧 Fetched 0 emails, 📅 0 events" → OAuth issue
- Check for "❌ Recommendation generation failed" → AI issue
- Look for OpenAI API errors in logs

### Issue: Worker never runs cycles

**Cause:** Multiple worker processes, only one has the scheduler

**Check logs for:**
```
⚠️  Scheduler already running, skipping duplicate
```

This is NORMAL in multi-worker setups. Only one process runs the scheduler.

## When to Change Interval

### Debug Mode (1 minute)
```bash
CANON_WORKER_INTERVAL_MINUTES=1
```
- Use this to test if worker is working
- See results within 1-2 minutes
- Don't leave this in production (too frequent)

### Production Mode (15 minutes)
```bash
CANON_WORKER_INTERVAL_MINUTES=15
```
- Runs 4 times per hour
- Balanced between freshness and API costs
- Recommended for production

### Hourly Mode (60 minutes)
```bash
CANON_WORKER_INTERVAL_MINUTES=60
```
- Runs once per hour
- Lower API costs
- Good for users who don't need real-time updates

## Current Status

✅ **Changes Made:**
- `.env`: Set `CANON_WORKER_INTERVAL_MINUTES=1`
- `app/workers/canon_worker.py`: Added duplicate prevention

⏳ **Next Steps:**
1. Deploy to production (git push or Render dashboard)
2. Watch logs for first cycle (within 1 minute)
3. Check canon via API to verify it populates
4. Once confirmed working, change interval to 15 minutes

## Support

For complete troubleshooting, see [CANON_WORKER_DEBUG_GUIDE.md](CANON_WORKER_DEBUG_GUIDE.md).
