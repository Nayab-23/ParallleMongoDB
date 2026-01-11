# Admin Observability Implementation Plan

**Status:** Infrastructure Created ✅
**Date:** 2026-01-05

## Overview

This document tracks the implementation of comprehensive debugging and observability for all admin endpoints.

---

## ✅ Infrastructure Complete

### Files Created:

1. **[app/api/admin/middleware.py](app/api/admin/middleware.py)** - Request tracking middleware
   - Generates `request_id` for every admin request
   - Tracks request duration
   - Captures user identity safely
   - Adds `X-Request-Id` and `X-Duration-Ms` headers

2. **[app/api/admin/responses.py](app/api/admin/responses.py)** - Standard response helpers
   - `admin_ok(request, data, debug={})` - Success responses
   - `admin_fail(request, code, message, details={})` - Error responses
   - `admin_exception_handler(request, exc)` - Crash handler

3. **[app/api/admin/selftest.py](app/api/admin/selftest.py)** - System validation
   - `GET /api/admin/_selftest` - Validates DB, tables, logging
   - `GET /api/admin/_routes` - Lists all admin routes
   - `GET /api/admin/_health` - Quick health check

---

## Standard Response Format

All admin endpoints now return:

```json
{
  "success": true,
  "request_id": "uuid-here",
  "duration_ms": 123,
  "data": { ... },
  "debug": {
    "input": { "limit": 100, "days": 7 },
    "output": { "count": 42, "newest_ts": "...", "oldest_ts": "..." },
    "notes": ["fallback to buffer", "no migrations applied"],
    "db": { "connected": true, "tables_queried": ["app_events"] }
  },
  "error": null
}
```

Error format:
```json
{
  "success": false,
  "request_id": "uuid-here",
  "duration_ms": 45,
  "data": null,
  "debug": { ... },
  "error": {
    "code": "MIGRATIONS_MISSING",
    "message": "app_events table missing; run alembic upgrade head",
    "details": { "tables_found": ["users", "rooms"], "tables_missing": ["app_events"] }
  }
}
```

---

##  TODO: Update Existing Endpoints

### Phase 1: Critical Endpoints (High Priority)

#### 1. app/api/admin/events.py
**Status:** ⏳ TODO

**Changes Needed:**
```python
from app.api.admin.responses import admin_ok, admin_fail
from sqlalchemy import inspect

@router.get("/events")
async def get_app_events(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Get application events with full debugging."""
    try:
        # Check if table exists
        inspector = inspect(db.bind)
        if "app_events" not in inspector.get_table_names():
            return admin_fail(
                request=request,
                code="MIGRATIONS_MISSING",
                message="app_events table missing; run alembic upgrade head",
                details={"available_tables": inspector.get_table_names()},
                status_code=503
            )

        # Query events
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        events = (
            db.query(AppEvent)
            .filter(AppEvent.created_at >= cutoff)
            .order_by(AppEvent.created_at.desc())
            .limit(limit)
            .all()
        )

        # Build response
        events_data = [
            {
                "id": e.id,
                "event_type": e.event_type,
                "source": e.source,
                "user_id": e.user_id,
                "created_at": e.created_at.isoformat(),
                "data": e.data,
            }
            for e in events
        ]

        return admin_ok(
            request=request,
            data={"events": events_data},
            debug={
                "input": {"days": days, "limit": limit},
                "output": {
                    "count": len(events),
                    "newest_ts": events[0].created_at.isoformat() if events else None,
                    "oldest_ts": events[-1].created_at.isoformat() if events else None,
                },
                "db": {"tables_queried": ["app_events"]},
            }
        )

    except Exception as e:
        logger.exception("Failed to fetch events")
        return admin_fail(
            request=request,
            code="DB_QUERY_FAILED",
            message="Failed to query events",
            details={"exception": str(e)},
            status_code=500
        )
```

#### 2. app/api/admin/diagnostics.py (Logs endpoint)
**Status:** ⏳ TODO

**Changes Needed:**
- Accept `source=all` as "no filter"
- Validate source parameter
- Return structured errors for invalid sources
- Add debug metadata showing filter applied

```python
@router.get("/logs")
async def get_logs(
    request: Request,
    source: str = Query("all"),
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(require_platform_admin),
):
    """Get application logs with debugging."""
    from app.services import log_buffer

    # Validate source
    valid_sources = ["all", "admin", "timeline", "notifications", "api", "system"]
    if source not in valid_sources:
        return admin_fail(
            request=request,
            code="INVALID_SOURCE",
            message=f"Invalid source: {source}",
            details={"allowed_sources": valid_sources, "provided": source},
            status_code=422
        )

    # Get logs
    filter_source = None if source == "all" else source
    logs = log_buffer.get_logs(source=filter_source, limit=limit)

    return admin_ok(
        request=request,
        data={"logs": logs},
        debug={
            "input": {"source": source, "limit": limit},
            "output": {"count": len(logs)},
            "notes": [f"filter: {filter_source or 'none (all sources)'}"],
        }
    )
```

#### 3. app/api/admin/timeline.py
**Status:** ⏳ TODO

**Changes Needed:**
- Wrap all endpoints in try/except
- Use admin_ok/admin_fail
- Add debug metadata showing:
  - Which stage was requested
  - If data came from DB or fallback
  - Counts of items returned
  - Date range of data

#### 4. app/api/admin/collaboration.py
**Status:** ⏳ TODO

**Changes Needed:**
- Use standard envelope
- Add debug showing:
  - User count
  - Chat interaction count
  - Notification count
  - Date range

#### 5. app/api/admin/system.py
**Status:** ⏳ TODO

**Changes Needed:**
- `/system-overview` should use admin_ok
- Add debug metadata for all stats returned

---

### Phase 2: Integration (Medium Priority)

#### 6. Register Middleware
**File:** `main.py`
**Status:** ⏳ TODO

```python
from app.api.admin.middleware import AdminDebugMiddleware

# Add middleware
app.add_middleware(AdminDebugMiddleware)
```

#### 7. Register Selftest Router
**File:** `app/api/admin/__init__.py`
**Status:** ⏳ TODO

```python
from app.api.admin import selftest

# Include selftest router
router.include_router(selftest.router, tags=["admin-system"])
```

---

### Phase 3: Timeline Event Emission (Low Priority)

**Goal:** Ensure timeline pipeline emits events and logs for observability.

**Locations to instrument:**
1. `app/services/timeline_service.py` (if exists)
2. `app/services/notifications.py` (if exists)
3. Any background jobs or celery tasks

**Events to emit:**
- `timeline_refresh_started`
- `timeline_refresh_finished`
- `timeline_stage_computed`
- `notification_sent`
- `room_activity_detected`

**Example:**
```python
from models import AppEvent
from app.services import log_buffer

# At start of timeline refresh
event = AppEvent(
    event_type="timeline_refresh_started",
    source="timeline",
    user_id=user_id,
    data={"request_id": request_id, "email": user_email}
)
db.add(event)

log_buffer.log_event(
    level="info",
    source="timeline",
    message=f"Timeline refresh started for {user_email}",
    data={"request_id": request_id}
)

# At end
event = AppEvent(
    event_type="timeline_refresh_finished",
    source="timeline",
    user_id=user_id,
    data={
        "request_id": request_id,
        "duration_ms": duration,
        "stages_computed": len(stages),
    }
)
db.add(event)
```

---

## Testing Checklist

Once implemented, test with these curl commands:

```bash
# 1. Health check
curl -H "Cookie: session=..." https://api.parallelos.ai/api/admin/_health

# Expected: success=true, database=connected

# 2. Self-test
curl -H "Cookie: session=..." https://api.parallelos.ai/api/admin/_selftest

# Expected: success=true, tests_passed >= 4, tests_failed=0

# 3. List routes
curl -H "Cookie: session=..." https://api.parallelos.ai/api/admin/_routes

# Expected: success=true, data.count >= 10

# 4. Get events
curl -H "Cookie: session=..." "https://api.parallelos.ai/api/admin/events?days=7&limit=50"

# Expected: success=true, data.events array, debug.input.days=7

# 5. Get logs (all sources)
curl -H "Cookie: session=..." "https://api.parallelos.ai/api/admin/logs?source=all&limit=100"

# Expected: success=true, data.logs array, debug.notes mentions "no filter"

# 6. Get logs (invalid source)
curl -H "Cookie: session=..." "https://api.parallelos.ai/api/admin/logs?source=invalid"

# Expected: success=false, error.code="INVALID_SOURCE", status=422

# 7. Timeline debug
curl -H "Cookie: session=..." "https://api.parallelos.ai/api/admin/timeline-debug/user@example.com"

# Expected: success=true, debug metadata with counts

# 8. Collaboration debug
curl -H "Cookie: session=..." "https://api.parallelos.ai/api/admin/collaboration-debug?users=user1@example.com&days=7"

# Expected: success=true, debug.input.users array, debug.output counts
```

---

## Response Headers

All admin responses now include:
- `X-Request-Id`: Unique request identifier
- `X-Duration-Ms`: Request processing time in milliseconds

---

## Error Codes Reference

| Code | Status | Meaning |
|------|--------|---------|
| `MIGRATIONS_MISSING` | 503 | Required database table doesn't exist |
| `INVALID_SOURCE` | 422 | Invalid filter parameter provided |
| `DB_QUERY_FAILED` | 500 | Database query failed |
| `INTERNAL_ERROR` | 500 | Unexpected exception occurred |
| `NOT_FOUND` | 404 | Resource not found |
| `UNAUTHORIZED` | 401 | Not authenticated |
| `FORBIDDEN` | 403 | Not authorized (not admin) |

---

## Implementation Priority

1. **High (Do First):**
   - Register middleware ✅ (created)
   - Register selftest router ⏳
   - Update events endpoint ⏳
   - Update logs endpoint ⏳

2. **Medium (Do Next):**
   - Update timeline endpoints ⏳
   - Update collaboration endpoint ⏳
   - Update system overview ⏳

3. **Low (Do Later):**
   - Add event emission to timeline pipeline ⏳
   - Add event emission to notifications ⏳

---

## Next Steps

To continue implementation:

1. Register the middleware in `main.py`
2. Register the selftest router in `app/api/admin/__init__.py`
3. Update each endpoint file to use `admin_ok` and `admin_fail`
4. Test with the curl commands above
5. Deploy and verify in production

**Estimated effort:** 2-4 hours for all endpoints

---

## Notes

- All new code avoids leaking secrets (tokens, cookies, raw SQLAlchemy objects)
- Debug info is "safe": counts, IDs, timestamps, query params, not sensitive data
- Never 500 for common issues - always return structured errors
- Admin pages can now distinguish "empty" vs "broken" states
