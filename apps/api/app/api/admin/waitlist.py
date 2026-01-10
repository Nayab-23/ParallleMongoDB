import logging
import uuid
from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_

from database import get_db
from models import WaitlistSubmission, User
from app.api.dependencies import require_platform_admin
from app.api.admin.utils import admin_ok, admin_fail

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/waitlist")
async def admin_waitlist_list(
    request: Request,
    limit: int = Query(200, ge=1, le=500),
    cursor: Optional[str] = Query(None, description="Cursor of form <iso>|<id>"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    try:
        query = db.query(WaitlistSubmission)
        if cursor and "|" in cursor:
            ts_str, cid = cursor.split("|", 1)
            try:
                ts = datetime.fromisoformat(ts_str)
                query = query.filter(
                    or_(
                        WaitlistSubmission.created_at < ts,
                        and_(WaitlistSubmission.created_at == ts, WaitlistSubmission.id < cid),
                    )
                )
            except Exception:
                pass

        rows = (
            query.order_by(WaitlistSubmission.created_at.desc(), WaitlistSubmission.id.desc())
            .limit(limit + 1)
            .all()
        )
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last.created_at.isoformat()}|{last.id}" if last.created_at else None
            rows = rows[:limit]

        data = [
            {
                "id": row.id,
                "name": row.name,
                "email": row.email,
                "notes": row.notes,
                "source": row.source,
                "metadata": row.meta or {},
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
        return admin_ok(
            request=request,
            data={"items": data, "count": len(data), "next_cursor": next_cursor},
            debug={
                "input": {"query_params": dict(request.query_params)},
                "db": {"tables_queried": ["waitlist_submissions"]},
            },
        )
    except Exception as exc:
        logger.exception("Failed to fetch waitlist", extra={"admin": getattr(current_user, "email", None)})
        return admin_fail(
            request=request,
            code="WAITLIST_FETCH_ERROR",
            message="Failed to fetch waitlist submissions",
            details={"error": str(exc)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=500,
        )


@router.get("/waitlist/stats")
async def admin_waitlist_stats(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    try:
        now = datetime.utcnow()
        last_24h = now - timedelta(hours=24)
        last_7d = now - timedelta(days=7)
        total = db.query(func.count(WaitlistSubmission.id)).scalar() or 0
        cnt_24h = (
            db.query(func.count(WaitlistSubmission.id))
            .filter(WaitlistSubmission.created_at >= last_24h)
            .scalar()
            or 0
        )
        cnt_7d = (
            db.query(func.count(WaitlistSubmission.id))
            .filter(WaitlistSubmission.created_at >= last_7d)
            .scalar()
            or 0
        )
        return admin_ok(
            request=request,
            data={"total": total, "last_24h": cnt_24h, "last_7d": cnt_7d},
            debug={"input": {"query_params": dict(request.query_params)}},
        )
    except Exception as exc:
        logger.exception("Failed to fetch waitlist stats", extra={"admin": getattr(current_user, "email", None)})
        return admin_fail(
            request=request,
            code="WAITLIST_STATS_ERROR",
            message="Failed to fetch waitlist stats",
            details={"error": str(exc)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=500,
        )


@router.delete("/waitlist/{submission_id}")
async def admin_waitlist_delete(
    request: Request,
    submission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    try:
        row = db.query(WaitlistSubmission).filter(WaitlistSubmission.id == submission_id).first()
        if not row:
            return admin_fail(
                request=request,
                code="NOT_FOUND",
                message="Submission not found",
                details={"submission_id": submission_id},
                debug={"input": {"path_params": {"submission_id": submission_id}}},
                status_code=404,
            )
        db.delete(row)
        db.commit()
        return admin_ok(
            request=request,
            data={"deleted": True, "submission_id": submission_id},
            debug={"input": {"path_params": {"submission_id": submission_id}}},
        )
    except Exception as exc:
        logger.exception("Failed to delete waitlist submission", extra={"submission_id": submission_id})
        return admin_fail(
            request=request,
            code="WAITLIST_DELETE_ERROR",
            message="Failed to delete submission",
            details={"error": str(exc), "submission_id": submission_id},
            debug={"input": {"path_params": {"submission_id": submission_id}}},
            status_code=500,
        )
