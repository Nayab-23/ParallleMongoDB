"""
Admin Timeline Debug API Endpoints
Provides detailed timeline generation diagnostics for platform admins.
"""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from database import get_db
from models import User, UserCanonicalPlan, CompletedBriefItem
from datetime import datetime
import uuid
import os
import re
import logging

from app.api.dependencies import require_platform_admin
from app.services.canon import _cache_key
from app.services import log_buffer
from app.services.event_emitter import emit_event
from app.services.event_emitter import emit_event
from app.api.admin.utils import admin_ok, admin_fail, sanitize_for_json

logger = logging.getLogger(__name__)

router = APIRouter()

C_CANON_STAGE_MAP = {
    "stage_0_input": "stage_0_input",
    "stage_1_filter": "stage_1_filter",
    "stage_2_guardrails": "stage_2_guardrails",
    "stage_3_ai": "stage_3_ai",
    "stage_4_semantic": "stage_4_semantic",
    "stage_4_semantic_dedup": "stage_4_semantic",
    "stage_final": "stage_final",
}


def _safe_json(value):
    """Recursively sanitize for JSON responses."""
    if isinstance(value, dict):
        return {k: _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(v) for v in value]
    return sanitize_for_json(value)


def _dedupe_stages(stage_list):
    """Ensure unique stages by stage_key, preserving order."""
    deduped = []
    seen = set()
    for stage in stage_list:
        key = stage.get("stage_key") or stage.get("label")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "stage_key": key,
                "label": stage.get("label", key),
                "input_count": stage.get("input_count"),
                "output_count": stage.get("output_count"),
                "removed_count": stage.get("removed_count"),
            }
        )
    return deduped


def _canonicalize_stage_key(key: str) -> str:
    if not key:
        return key
    return C_CANON_STAGE_MAP.get(key, key)


def _canonicalize_stages(stage_list: list[dict]) -> tuple[list[dict], dict]:
    """
    Returns (canonical_stage_list, mapping_dict).
    """
    mapping = {}
    result = []
    seen = set()
    for stage in stage_list:
        raw_key = stage.get("stage_key") or stage.get("label")
        canon = _canonicalize_stage_key(raw_key)
        if raw_key and canon and raw_key != canon:
            mapping[raw_key] = canon
        if not canon or canon in seen:
            continue
        seen.add(canon)
        result.append(
            {
                "stage_key": canon,
                "label": stage.get("label", canon),
                "input_count": stage.get("input_count"),
                "output_count": stage.get("output_count"),
                "removed_count": stage.get("removed_count"),
            }
        )
    return result, mapping


def count_timeline_items(timeline: dict) -> int:
    """Count total items across all timeframes."""
    count = 0
    for timeframe in ["1d", "7d", "28d"]:
        for priority in ["urgent", "normal"]:
            count += len(timeline.get(timeframe, {}).get(priority, []))
    return count


def build_stage_estimates(timeline: dict) -> dict:
    """
    Build estimated stage counts from current timeline when logs unavailable.
    """
    total = count_timeline_items(timeline)

    return {
        "stage_0_input": {"total_items": "unknown", "timestamp": None},
        "stage_final": {
            "total_items": total,
            "timestamp": datetime.now().isoformat()
        }
    }


def parse_timeline_logs(user_email: str) -> dict:
    """
    Parse timeline_diagnostics.log for the user's latest refresh.
    Returns stage counts, recurring patterns, AI stats, etc.

    First checks in-memory cache, then falls back to log parsing.
    """
    # Check in-memory cache first
    from app.services.canon import TIMELINE_DEBUG_CACHE
    cache_key = _cache_key(user_email)

    if cache_key in TIMELINE_DEBUG_CACHE:
        cached_data = TIMELINE_DEBUG_CACHE[cache_key]
        return {
            "stages": cached_data.get("stages", {}),
            "stages_list": cached_data.get("stages_list", []),
            "stage_items": cached_data.get("stage_items", {}),
            "pipeline_totals": cached_data.get("pipeline_totals", {}),
            "email_stage_0": cached_data.get("email_stage_0", {}),
            "last_refresh_ts": cached_data.get("last_refresh_ts"),
            "recurring_patterns": cached_data.get("recurring_patterns", []),
            "ai_items_sent": cached_data.get("ai_items_sent"),
            "ai_excluded": cached_data.get("ai_excluded"),
            "validation_fixes": cached_data.get("validation_fixes", 0),
            "guardrails": cached_data.get("guardrails", {}),
            "source": "cache",
            "cache_timestamp": cached_data.get("timestamp")
        }

    # Fallback to parsing logs
    log_path = "/app/logs/timeline_diagnostics.log"
    if not os.path.exists(log_path):
        return {"source": "none", "error": "Log file not found"}

    try:
        # Read last 2000 lines
        with open(log_path, 'r') as f:
            lines = f.readlines()[-2000:]

        # Find lines for this user (look for email in logs)
        user_lines = [line for line in lines if user_email in line]

        if not user_lines:
            return {"source": "logs", "error": "No log entries found for user"}

        # Parse key metrics from logs
        result = {
            "source": "logs",
            "stages": {},
            "recurring_patterns": [],
            "ai_items_sent": None,
            "ai_excluded": None,
            "validation_fixes": 0,
            "guardrails": {}
        }

        # Extract stage counts
        for line in user_lines:
            # Stage counts: "[STAGE 0: Initial] Total: 528"
            stage_match = re.search(r'\[STAGE (\d+).*?\] Total: (\d+)', line)
            if stage_match:
                stage_num = stage_match.group(1)
                count = int(stage_match.group(2))
                result["stages"][f"stage_{stage_num}"] = {
                    "total_items": count,
                    "timestamp": None  # Could extract from log timestamp if needed
                }

            # Recurring patterns: "[Recurring Debug] === Checking recurring for 'Trade with Chase' ==="
            recurring_match = re.search(r"\[Recurring Debug\].*?Checking recurring for '([^']+)'", line)
            if recurring_match:
                title = recurring_match.group(1)
                if title not in result["recurring_patterns"]:
                    result["recurring_patterns"].append(title)

            # AI stats: "[AI Response] ✅ Restored deadline_raw to 5 events"
            ai_restore_match = re.search(r'\[AI Response\].*?Restored deadline_raw to (\d+)', line)
            if ai_restore_match:
                result["validation_fixes"] += int(ai_restore_match.group(1))

            # Guardrails: "[Guardrails] ✅ Force-filled 1d with 3 items"
            guardrail_match = re.search(r'\[Guardrails\].*?Force-filled (\w+) with (\d+)', line)
            if guardrail_match:
                timeframe = guardrail_match.group(1)
                count = int(guardrail_match.group(2))
                result["guardrails"][f"{timeframe}_backfill"] = count

        return result

    except Exception as e:
        return {"source": "logs", "error": f"Failed to parse logs: {str(e)}"}


@router.get("/timeline-debug/{user_email}")
async def get_timeline_debug(
    request: Request,
    user_email: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin)
):
    """
    Get detailed timeline generation debug info for a specific user.
    Admin only.

    Frontend calls: GET /api/admin/timeline-debug/{user_email}

    Returns:
    - Stage-by-stage processing counts
    - Recurring event consolidation patterns
    - AI processing stats
    - Guardrail activations
    - Current timeline state
    - Recent completions (for deletion filter context)
    """
    request_id = str(uuid.uuid4())
    try:
        logger.info(f"[Timeline Debug] 🔍 GET /timeline-debug/{user_email} called by {current_user.email}")

        logger.debug(f"[Timeline Debug] ✅ Admin access verified for {current_user.email}")

        # STEP 2: Find target user
        logger.debug(f"[Timeline Debug] Querying user: {user_email}")
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            logger.error(f"[Timeline Debug] ❌ User not found: {user_email}")
            return admin_fail(
                request=request,
                code="NOT_FOUND",
                message=f"User {user_email} not found",
                details={"user_email": user_email},
                debug={"input": {"query_params": dict(request.query_params)}},
                status_code=404,
            )

        logger.debug(f"[Timeline Debug] ✅ Found user: {user.email} (ID: {user.id})")

        # STEP 3: Get current timeline
        logger.debug(f"[Timeline Debug] Querying UserCanonicalPlan for user {user.id}")
        canonical_plan = db.query(UserCanonicalPlan).filter(
            UserCanonicalPlan.user_id == user.id
        ).first()

        if not canonical_plan:
            logger.warning(f"[Timeline Debug] ⚠️  No timeline found for user {user_email}")
            return admin_fail(
                request=request,
                code="NOT_FOUND",
                message="No timeline found for this user",
                details={"user_email": user_email},
                debug={"input": {"query_params": dict(request.query_params)}},
                status_code=404,
            )

        logger.debug(f"[Timeline Debug] ✅ Found timeline (last updated: {canonical_plan.updated_at})")

        # STEP 4: Parse timeline data
        timeline = canonical_plan.approved_timeline or {}
        total_items = count_timeline_items(timeline)
        logger.debug(f"[Timeline Debug] Timeline has {total_items} total items")

        # STEP 5: Get completed items (for deletion filter context)
        logger.debug(f"[Timeline Debug] Querying completed items...")
        completed_items = db.query(CompletedBriefItem).filter(
            CompletedBriefItem.user_id == user.id
        ).order_by(CompletedBriefItem.completed_at.desc()).limit(50).all()
        logger.debug(f"[Timeline Debug] Found {len(completed_items)} completed items")

        # STEP 6: Parse timeline logs or get cached data
        logger.debug(f"[Timeline Debug] Parsing timeline logs/cache for {user_email}")
        log_data = parse_timeline_logs(user_email)
        logger.info(f"[Timeline Debug] Data source: {log_data.get('source', 'unknown')}")

        # Get email filtering data from cache
        from app.services.canon import TIMELINE_DEBUG_CACHE, _cache_key
        email_filtering_data = {}
        cache_key = _cache_key(user_email)
        if cache_key in TIMELINE_DEBUG_CACHE:
            email_filtering_data = TIMELINE_DEBUG_CACHE[cache_key].get("email_filtering", {})

        # STEP 7: Build response
        email_stage_0 = log_data.get("email_stage_0") or {
            "total_emails_loaded": email_filtering_data.get("emails_kept", 0) + email_filtering_data.get("emails_dropped_deletion_filter", 0),
            "filtered_out_count": email_filtering_data.get("emails_dropped_deletion_filter", 0),
            "filter_reasons_breakdown": email_filtering_data.get("drop_reasons", {}),
            "sample_ids": [s.get("id") for s in email_filtering_data.get("drop_samples", []) if isinstance(s, dict) and s.get("id")],
        }

        stage_list_raw = log_data.get("stages_list") or []
        stages_map_raw = log_data.get("stages", build_stage_estimates(timeline))
        if not stage_list_raw and stages_map_raw:
            for key, val in stages_map_raw.items():
                stage_list_raw.append(
                    {
                        "stage_key": key,
                        "label": key,
                        "input_count": val.get("total_items"),
                        "output_count": val.get("total_items"),
                        "removed_count": 0,
                    }
                )
        stage_list_raw = _dedupe_stages(stage_list_raw)
        stage_list, key_map = _canonicalize_stages(stage_list_raw)
        stages_map = { _canonicalize_stage_key(k): v for k, v in stages_map_raw.items() } if isinstance(stages_map_raw, dict) else {}
        missing_keys = [
            (k.get("stage_key") or k.get("label"))
            for k in stage_list_raw
            if (k.get("stage_key") or k.get("label")) not in stages_map
        ]

        pipeline_totals = log_data.get("pipeline_totals") or {}
        if not pipeline_totals:
            pipeline_totals = {
                "input_total": stages_map.get("stage_0", {}).get("total_items", count_timeline_items(timeline)),
                "final_total": count_timeline_items(timeline),
            }
        else:
            pipeline_totals.setdefault("input_total", count_timeline_items(timeline))
            pipeline_totals.setdefault("final_total", count_timeline_items(timeline))

        response = {
            "user": user_email,
            "user_id": user.id,
            "last_refresh": log_data.get("last_refresh_ts") or (canonical_plan.updated_at.isoformat() if canonical_plan.updated_at else None),

            # Data source (cache, logs, or estimates)
            "data_source": log_data.get("source", "estimates"),

            # Stage data (array + map for compatibility)
            "stages": stage_list,
            "stages_map": stages_map,
            "pipeline_totals": pipeline_totals,

            # Email observability (NEW)
            "email_stage_0": email_stage_0,
            "email_drop_reasons": email_filtering_data.get("drop_reasons", {}),
            "email_drop_samples": email_filtering_data.get("drop_samples", []),

            # Recurring consolidation info
            "recurring_consolidation": {
                "patterns_detected": log_data.get("recurring_patterns", []),
                "pattern_count": len(log_data.get("recurring_patterns", []))
            },

            # AI processing
            "ai_processing": {
                "items_sent": log_data.get("ai_items_sent", "unknown"),
                "items_returned": count_timeline_items(timeline),
                "excluded": log_data.get("ai_excluded", "unknown"),
                "validation_fixes": log_data.get("validation_fixes", 0)
            },

            # Guardrails
            "guardrails": log_data.get("guardrails", {
                "1d_before": "unknown",
                "1d_after": len(timeline.get("1d", {}).get("urgent", [])) + len(timeline.get("1d", {}).get("normal", [])),
                "7d_before": "unknown",
                "7d_after": len(timeline.get("7d", {}).get("urgent", [])) + len(timeline.get("7d", {}).get("normal", [])),
                "backfill_triggered": "unknown"
            }),

            # Current timeline state
            "current_timeline": {
                "1d": {
                    "urgent": timeline.get("1d", {}).get("urgent", []),
                    "normal": timeline.get("1d", {}).get("normal", [])
                },
                "7d": {
                    "urgent": timeline.get("7d", {}).get("urgent", []),
                    "normal": timeline.get("7d", {}).get("normal", [])
                },
                "28d": {
                    "urgent": timeline.get("28d", {}).get("urgent", []),
                    "normal": timeline.get("28d", {}).get("normal", [])
                },
                "total_items": count_timeline_items(timeline)
            },

            # Completed items (for context on deletion filter)
            "recent_completions": [
                {
                    "title": item.title,
                    "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                    "signature": item.signature
                }
                for item in completed_items[:10]
            ],
            "total_completions": len(completed_items),
            "request_id": request_id,
        }

        snapshot_ts = log_data.get("cache_timestamp") or log_data.get("last_refresh_ts")
        snapshot_dt = None
        try:
            if snapshot_ts:
                snapshot_dt = datetime.fromisoformat(snapshot_ts)
        except Exception:
            snapshot_dt = None
        snapshot_age = None
        if snapshot_dt:
            snapshot_age = (datetime.now(snapshot_dt.tzinfo) - snapshot_dt).total_seconds()

        snapshot_ts = log_data.get("cache_timestamp") or log_data.get("last_refresh_ts")
        snapshot_dt = None
        try:
            if snapshot_ts:
                snapshot_dt = datetime.fromisoformat(snapshot_ts)
        except Exception:
            snapshot_dt = None
        snapshot_age = None
        if snapshot_dt:
            snapshot_age = (datetime.now(snapshot_dt.tzinfo) - snapshot_dt).total_seconds()

        # Persist snapshot info on request for middleware headers
        request.state.timeline_snapshot_info = {
            "snapshot_key": cache_key,
            "snapshot_age_seconds": snapshot_age,
        }

        logger.info(
            {
                "kind": "timeline_snapshot",
                "request_id": request_id,
                "user_email": user_email,
                "snapshot_source": log_data.get("source", "unknown"),
                "snapshot_key": cache_key,
                "snapshot_timestamp": snapshot_ts,
                "snapshot_age_seconds": snapshot_age,
                "worker_last_write_ts": log_data.get("last_refresh_ts"),
                "stage_keys": [s.get("stage_key") for s in stage_list],
                "pipeline_totals": pipeline_totals,
            }
        )

        logger.info(f"[Timeline Debug] ✅ Returning debug data for {user_email} (data_source: {response['data_source']}, total_items: {total_items})")
        return admin_ok(
            request=request,
            data=_safe_json(response),
            debug={
                "input": {"query_params": dict(request.query_params), "user_email": user_email},
                "output": {
                    "data_source": response.get("data_source"),
                    "total_items": total_items,
                    "stages_count": len(stage_list),
                    "completions": len(completed_items),
                    "pipeline_totals": pipeline_totals,
                    "key_mapping_applied": key_map,
                },
                "db": {"tables_queried": ["users", "user_canonical_plans", "completed_brief_items"]},
                "timeline_snapshot": {
                    "snapshot_source": log_data.get("source", "unknown"),
                    "snapshot_key": cache_key,
                    "snapshot_timestamp": snapshot_ts,
                    "snapshot_age_seconds": snapshot_age,
                    "worker_last_write_ts": log_data.get("last_refresh_ts"),
                    "worker_last_run_id": log_data.get("run_id"),
                },
                "stage_counts": {
                    "missing_keys": missing_keys if isinstance(missing_keys, list) else [],
                    "reason": "not_in_snapshot" if missing_keys else None,
                },
            },
        )
    except Exception as exc:
        logger.exception("Timeline debug failed", extra={"request_id": request_id})
        log_buffer.log_event("error", "admin", "Timeline debug failed", {"request_id": request_id, "error": str(exc)})
        return admin_fail(
            request=request,
            code="TIMELINE_DEBUG_ERROR",
            message="Failed to fetch timeline debug",
            details={"error": str(exc)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=500,
        )


@router.get("/timeline-debug/{user_email}/last-payload")
async def get_last_timeline_payload(
    request: Request,
    user_email: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin)
):
    """
    Get the last timeline payload that was computed/saved for this user.
    Useful for comparing what backend saved vs what frontend received.
    Admin only.

    Frontend calls: GET /api/admin/timeline-debug/{user_email}/last-payload
    """
    logger.info(f"[Timeline Payload] 🔍 GET /timeline-debug/{user_email}/last-payload called by {current_user.email}")

    # Find target user
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        logger.error(f"[Timeline Payload] ❌ User not found: {user_email}")
        return admin_fail(
            request=request,
            code="NOT_FOUND",
            message=f"User {user_email} not found",
            details={"user_email": user_email},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=404,
        )

    # Get canonical plan
    canonical_plan = db.query(UserCanonicalPlan).filter(
        UserCanonicalPlan.user_id == user.id
    ).first()

    if not canonical_plan:
        logger.warning(f"[Timeline Payload] ⚠️  No timeline found for user {user_email}")
        return admin_fail(
            request=request,
            code="NOT_FOUND",
            message="No timeline found for this user",
            details={"user_email": user_email},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=404,
        )

    timeline = canonical_plan.approved_timeline or {}

    # Count items in each bucket
    bucket_counts = {}
    for tf in ['1d', '7d', '28d']:
        bucket_counts[tf] = {}
        tf_data = timeline.get(tf, {})
        if isinstance(tf_data, dict):
            for priority in ['urgent', 'normal']:
                items = tf_data.get(priority, [])
                bucket_counts[tf][priority] = len(items) if isinstance(items, list) else 0
        else:
            bucket_counts[tf]['urgent'] = 0
            bucket_counts[tf]['normal'] = 0

    logger.info(f"[Timeline Payload] ✅ Returning last saved payload for {user_email}")

    data = {
        "user": user_email,
        "user_id": user.id,
        "last_updated": canonical_plan.updated_at.isoformat() if canonical_plan.updated_at else None,
        "timeline": timeline,
        "bucket_counts": bucket_counts,
        "total_items": sum(bucket_counts[tf][pr] for tf in ['1d', '7d', '28d'] for pr in ['urgent', 'normal'])
    }

    logger.info(f"[Timeline Payload] ✅ Returning last saved payload for {user_email}")
    return admin_ok(
        request=request,
        data=_safe_json(data),
        debug={
            "input": {"query_params": dict(request.query_params)},
            "output": {
                "bucket_counts": bucket_counts,
                "total_items": data["total_items"],
            },
            "db": {"tables_queried": ["users", "user_canonical_plans"]},
        },
    )


@router.post("/timeline-debug/{user_email}/refresh")
async def trigger_timeline_refresh(
    request: Request,
    user_email: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin)
):
    """
    Manually trigger timeline refresh for a user (admin only).

    Frontend calls: POST /api/admin/timeline-debug/{user_email}/refresh

    This will generate a fresh timeline by:
    1. Fetching latest calendar events
    2. Fetching latest emails
    3. Running full deduplication pipeline
    4. Consolidating recurring events
    5. Sending to AI for categorization
    6. Applying guardrails
    7. Saving to database
    """
    request_id = str(uuid.uuid4())
    logger.info(f"[Timeline Refresh] 🔄 POST /timeline-debug/{user_email}/refresh called by {current_user.email}")

    logger.debug(f"[Timeline Refresh] ✅ Admin access verified for {current_user.email}")

    # STEP 2: Find target user
    logger.debug(f"[Timeline Refresh] Querying user: {user_email}")
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        logger.error(f"[Timeline Refresh] ❌ User not found: {user_email}")
        return admin_fail(
            request=request,
            code="NOT_FOUND",
            message=f"User {user_email} not found",
            details={"user_email": user_email},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=404,
        )

    logger.debug(f"[Timeline Refresh] ✅ Found user: {user.email} (ID: {user.id})")

    # STEP 3: Import and call the timeline refresh function
    from app.services.canon import generate_recommendations

    try:
        logger.info(f"[Timeline Refresh] 🚀 Starting timeline generation for {user_email}...")
        log_buffer.log_event(
            "info",
            "timeline",
            "timeline_refresh_start",
            {"request_id": request_id, "target_email": user_email, "admin_email": current_user.email},
        )

        # Call timeline generation (note: generate_recommendations is synchronous)
        result = generate_recommendations(user, [], [], None, db, is_manual_refresh=True)

        logger.info(f"[Timeline Refresh] ✅ Timeline refresh completed successfully for {user_email}")
        log_buffer.log_event(
            "info",
            "timeline",
            "timeline_refresh_done",
            {"request_id": request_id, "target_email": user_email, "admin_email": current_user.email},
        )
        emit_event(
            "timeline_refresh",
            user_email=current_user.email,
            target_email=user.email,
            metadata={"user_id": user.id},
            request_id=request_id,
            db=db,
        )

        data = {
            "user": user_email,
            "message": "Timeline refresh triggered successfully",
            "timestamp": datetime.now().isoformat(),
            "result": "Timeline generated",
        }
        return admin_ok(
            request=request,
            data=_safe_json(data),
            debug={
                "input": {"query_params": dict(request.query_params)},
                "output": {"result": data["result"]},
            },
        )
    except Exception as e:
        import traceback
        logger.error(f"[Timeline Refresh] ❌ Timeline refresh failed for {user_email}: {str(e)}", exc_info=True)
        log_buffer.log_event(
            "error",
            "timeline",
            "timeline_refresh_error",
            {"request_id": request_id, "target_email": user_email, "admin_email": current_user.email, "error": str(e)},
        )
        emit_event(
            "timeline_refresh",
            user_email=current_user.email,
            target_email=user.email if 'user' in locals() and user else None,
            metadata={"error": str(e)},
            request_id=request_id,
            db=db,
        )

        return admin_fail(
            request=request,
            code="TIMELINE_REFRESH_FAILED",
            message="Timeline refresh failed",
            details={
                "user_email": user_email,
                "error": str(e),
                "traceback": traceback.format_exc(),
            },
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=500,
        )


@router.get("/timeline-debug/{user_email}/stage/{stage_key}")
async def get_timeline_stage_detail(
    request: Request,
    user_email: str,
    stage_key: str,
    limit: int = Query(default=50, ge=1, le=200),
    page: int = Query(default=1, ge=1, le=1000),
    current_user: User = Depends(require_platform_admin),
):
    request_id = str(uuid.uuid4())
    try:
        data = parse_timeline_logs(user_email)
        cache_key = _cache_key(user_email)
        stage_items_map = data.get("stage_items", {}) or {}
        available_keys_raw = list(stage_items_map.keys() or [])
        normalized_stage_key = _canonicalize_stage_key(stage_key)
        available_keys = list({_canonicalize_stage_key(k) for k in available_keys_raw if k})
        stage_items = stage_items_map.get(stage_key) or stage_items_map.get(normalized_stage_key) or []

        # Fallback: consider stages_list if stage_items map is empty
        if not stage_items and not available_keys:
            available_keys = [_canonicalize_stage_key(s.get("stage_key")) for s in data.get("stages_list", []) if s.get("stage_key")]

        if normalized_stage_key not in (available_keys or []) and not stage_items:
            return admin_fail(
                request=request,
                code="INVALID_STAGE_KEY",
                message="Unknown stage key",
                details={"stage_key": stage_key, "available_stage_keys": available_keys},
                debug={
                    "input": {"query_params": dict(request.query_params)},
                    "output": {"items_count": 0},
                },
                status_code=400,
            )

        offset = (page - 1) * limit
        sliced = stage_items[offset : offset + limit] if isinstance(stage_items, list) else []
        stage_meta = next((s for s in data.get("stages_list", []) if _canonicalize_stage_key(s.get("stage_key")) == normalized_stage_key), {})
        decision_reasons = stage_meta.get("removed_reasons") or {}
        has_more = False
        if isinstance(stage_items, list):
            has_more = len(stage_items) > offset + limit

        claimed_count = stage_meta.get("output_count")
        if (claimed_count and claimed_count > 0) and not stage_items:
            return admin_fail(
                request=request,
                code="TIMELINE_SNAPSHOT_INCONSISTENT",
                message="Stage claims items but none were found in snapshot",
                details={
                    "stage_key": stage_key,
                    "normalized_stage_key": normalized_stage_key,
                    "claimed_output_count": claimed_count,
                    "items_found_count": 0,
                    "available_stage_keys": available_keys,
                },
                debug={"input": {"query_params": dict(request.query_params)}},
                status_code=500,
            )

        sample_ids = []
        try:
            sample_ids = [i.get("id") for i in sliced if isinstance(i, dict) and i.get("id")][:5]
        except Exception:
            sample_ids = []

        return admin_ok(
            request=request,
            data=_safe_json(
                {
                    "stage_key": stage_key,
                    "items": sliced,
                    "decision_reasons": decision_reasons,
                    "page": page,
                    "limit": limit,
                    "has_more": has_more,
                    "last_refresh_ts": data.get("last_refresh_ts"),
                }
            ),
            debug={
                "input": {
                    "query_params": dict(request.query_params),
                    "stage_key": stage_key,
                    "normalized_stage_key": normalized_stage_key,
                    "page": page,
                    "limit": limit,
                },
                "output": {
                    "items_count": len(sliced),
                    "has_more": has_more,
                    "data_source": data.get("source"),
                    "cache_key_used": cache_key,
                    "items_found_count": len(stage_items) if isinstance(stage_items, list) else 0,
                    "available_stage_keys": available_keys,
                    "sample_item_ids": sample_ids,
                },
            },
        )
    except Exception as exc:
        logger.exception("Failed to fetch stage detail", extra={"request_id": request_id})
        log_buffer.log_event(
            "error",
            "admin",
            "Failed to fetch stage detail",
            {"request_id": request_id, "error": str(exc)},
        )
        return admin_fail(
            request=request,
            code="STAGE_DETAIL_ERROR",
            message="Failed to fetch stage detail",
            details={"error": str(exc)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=500,
        )


@router.post("/timeline/probe")
async def timeline_probe(
    request: Request,
    user_email: str = Query(...),
    force_refresh: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """
    Probe timeline snapshot consistency. Optionally trigger a refresh first.
    """
    request_id = str(uuid.uuid4())
    try:
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            return admin_fail(
                request=request,
                code="NOT_FOUND",
                message=f"User {user_email} not found",
                details={"user_email": user_email},
                debug={"input": {"query_params": dict(request.query_params)}},
                status_code=404,
            )

        if force_refresh:
            try:
                from app.services.canon import generate_recommendations
                generate_recommendations(user, [], [], None, db, is_manual_refresh=True)
            except Exception as exc:
                logger.exception("Probe refresh failed", extra={"request_id": request_id})
                return admin_fail(
                    request=request,
                    code="REFRESH_FAILED",
                    message="Force refresh failed",
                    details={"error": str(exc)},
                    debug={"input": {"query_params": dict(request.query_params)}},
                    status_code=500,
                )

        log_data = parse_timeline_logs(user_email)
        canonical_plan = db.query(UserCanonicalPlan).filter(UserCanonicalPlan.user_id == user.id).first()
        timeline = canonical_plan.approved_timeline or {}
        total_items = count_timeline_items(timeline)

        stage_list_raw = log_data.get("stages_list") or []
        stages_map_raw = log_data.get("stages", build_stage_estimates(timeline))
        stage_list_raw = _dedupe_stages(stage_list_raw)
        stage_list, key_map = _canonicalize_stages(stage_list_raw)
        stages_map = { _canonicalize_stage_key(k): v for k, v in stages_map_raw.items() } if isinstance(stages_map_raw, dict) else {}
        pipeline_totals = log_data.get("pipeline_totals") or {}
        pipeline_totals.setdefault("input_total", stages_map.get("stage_0", {}).get("total_items", total_items))
        pipeline_totals.setdefault("final_total", count_timeline_items(timeline))

        # Consistency checks
        bucket_total = total_items
        stage_final_total = stages_map.get("stage_final", {}).get("total_items")
        inconsistencies = []
        if stage_final_total is not None and stage_final_total != bucket_total:
            inconsistencies.append("stage_final_vs_timeline_mismatch")
        if pipeline_totals.get("final_total") != bucket_total:
            inconsistencies.append("pipeline_total_vs_timeline_mismatch")

        snapshot_ts = log_data.get("cache_timestamp") or log_data.get("last_refresh_ts")
        snapshot_dt = None
        try:
            if snapshot_ts:
                snapshot_dt = datetime.fromisoformat(snapshot_ts)
        except Exception:
            snapshot_dt = None
        snapshot_age = None
        if snapshot_dt:
            snapshot_age = (datetime.now(snapshot_dt.tzinfo) - snapshot_dt).total_seconds()

        data = {
            "user": user_email,
            "data_source": log_data.get("source", "unknown"),
            "stages": stage_list,
            "stages_map": stages_map,
            "pipeline_totals": pipeline_totals,
            "current_timeline_total": bucket_total,
            "consistency": {
                "bucket_total": bucket_total,
                "stage_final_total": stage_final_total,
                "pipeline_final_total": pipeline_totals.get("final_total"),
                "inconsistencies": inconsistencies,
            },
        }

        return admin_ok(
            request=request,
            data=_safe_json(data),
            debug={
                "input": {"query_params": dict(request.query_params)},
                "timeline_snapshot": {
                    "snapshot_source": log_data.get("source", "unknown"),
                    "snapshot_key": _cache_key(user_email),
                    "snapshot_timestamp": snapshot_ts,
                    "snapshot_age_seconds": snapshot_age,
                    "worker_last_write_ts": log_data.get("last_refresh_ts"),
                    "worker_last_run_id": log_data.get("run_id"),
                },
                "stage_counts": {
                    "stage_keys": [s.get("stage_key") for s in stage_list],
                    "key_mapping_applied": key_map,
                },
                "consistency": data["consistency"],
            },
        )
    except Exception as exc:
        logger.exception("Timeline probe failed", extra={"request_id": request_id})
        return admin_fail(
            request=request,
            code="TIMELINE_PROBE_ERROR",
            message="Timeline probe failed",
            details={"error": str(exc)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=500,
        )
