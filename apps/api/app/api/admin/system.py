from datetime import datetime, timedelta
import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from database import get_db
from models import (
    ChatInstance,
    Message,
    Notification,
    User,
    UserAction,
    UserCanonicalPlan,
)
from app.api.dependencies import require_platform_admin
from app.api.admin.utils import admin_ok, admin_fail

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/system-overview")
async def get_system_overview(
    request: Request,
    days: int = Query(7, ge=1, le=90, description="Number of days to analyze"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """
    Get system-wide overview metrics with debugging.
    Shows overall platform health, usage, and errors.
    Admin only.
    """
    try:
        # Validate parameters
        query_params = dict(request.query_params)
        requested_days = days
        if requested_days is None:
            days = 7
        days = max(1, min(days or 7, 90))

        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days)

        # USERS
        total_users = db.query(func.count(User.id)).scalar() or 0
        active_users = (
            db.query(func.count(func.distinct(UserAction.user_id)))
            .filter(UserAction.timestamp >= start_dt)
            .scalar()
            or 0
        )

        # TIMELINE GENERATION (updated canonical plans)
        timeline_refreshes = (
            db.query(func.count(UserCanonicalPlan.id))
            .filter(UserCanonicalPlan.updated_at >= start_dt)
            .scalar()
            or 0
        )

        # VSCODE ACTIVITY
        vscode_actions = (
            db.query(func.count(UserAction.id))
            .filter(
                and_(
                    UserAction.tool == "vscode",
                    UserAction.timestamp >= start_dt,
                )
            )
            .scalar()
            or 0
        )

        top_vscode_users = (
            db.query(User.email, func.count(UserAction.id).label("action_count"))
            .join(UserAction, User.id == UserAction.user_id)
            .filter(
                and_(
                    UserAction.tool == "vscode",
                    UserAction.timestamp >= start_dt,
                )
            )
            .group_by(User.email)
            .order_by(func.count(UserAction.id).desc())
            .limit(5)
            .all()
        )

        # CHATS & MESSAGES
        total_messages = (
            db.query(func.count(Message.id))
            .filter(Message.created_at >= start_dt)
            .scalar()
            or 0
        )

        total_chats = (
            db.query(func.count(ChatInstance.id))
            .filter(ChatInstance.created_at >= start_dt)
            .scalar()
            or 0
        )

        # NOTIFICATIONS
        total_notifications = (
            db.query(func.count(Notification.id))
            .filter(Notification.created_at >= start_dt)
            .scalar()
            or 0
        )

        urgent_notifications = (
            db.query(func.count(Notification.id))
            .filter(
                and_(
                    Notification.severity == "urgent",
                    Notification.created_at >= start_dt,
                )
            )
            .scalar()
            or 0
        )

        conflict_notifications = (
            db.query(func.count(Notification.id))
            .filter(
                and_(
                    Notification.source_type.in_(["conflict_file", "conflict_semantic"]),
                    Notification.created_at >= start_dt,
                )
            )
            .scalar()
            or 0
        )

        # FEATURE USAGE BREAKDOWN
        action_types = (
            db.query(UserAction.action_type, func.count(UserAction.id).label("count"))
            .filter(UserAction.timestamp >= start_dt)
            .group_by(UserAction.action_type)
            .all()
        )

        notification_types = (
            db.query(Notification.type, func.count(Notification.id).label("count"))
            .filter(Notification.created_at >= start_dt)
            .group_by(Notification.type)
            .all()
        )

        # DAILY ACTIVITY (for chart)
        daily_activity = []
        for day_offset in range(days):
            day_start = start_dt + timedelta(days=day_offset)
            day_end = day_start + timedelta(days=1)

            day_actions = (
                db.query(func.count(UserAction.id))
                .filter(
                    and_(
                        UserAction.timestamp >= day_start,
                        UserAction.timestamp < day_end,
                    )
                )
                .scalar()
                or 0
            )

            day_messages = (
                db.query(func.count(Message.id))
                .filter(
                    and_(
                        Message.created_at >= day_start,
                        Message.created_at < day_end,
                    )
                )
                .scalar()
                or 0
            )

            daily_activity.append(
                {
                    "date": day_start.strftime("%Y-%m-%d"),
                    "actions": day_actions,
                    "messages": day_messages,
                    "total": day_actions + day_messages,
                }
            )

        overview_data = {
            "date_range": {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "days": days,
            },
            "users": {
                "total": total_users,
                "active": active_users,
                "active_percentage": round(
                    (active_users / total_users * 100) if total_users > 0 else 0, 1
                ),
            },
            "timeline": {
                "refreshes": timeline_refreshes,
                "avg_per_user": round(
                    timeline_refreshes / active_users, 1
                ) if active_users > 0 else 0,
            },
            "vscode": {
                "total_actions": vscode_actions,
                "top_users": [
                    {"email": email, "action_count": count} for email, count in top_vscode_users
                ],
            },
            "communication": {
                "total_messages": total_messages,
                "total_chats": total_chats,
                "avg_messages_per_chat": round(
                    total_messages / total_chats, 1
                ) if total_chats > 0 else 0,
            },
            "notifications": {
                "total": total_notifications,
                "urgent": urgent_notifications,
                "conflicts": conflict_notifications,
                "by_type": {type_name: count for type_name, count in notification_types},
            },
            "feature_usage": {
                "action_types": {action_type or "unknown": count for action_type, count in action_types},
            },
            "daily_activity": daily_activity,
        }

        return admin_ok(
            request=request,
            data=overview_data,
            debug={
                "input": {
                    "query_params": query_params,
                    "requested_days": requested_days,
                    "days_applied": days,
                },
                "output": {
                    "users_count": total_users,
                    "active_users": active_users,
                    "messages_count": total_messages,
                    "notifications_count": total_notifications,
                    "daily_data_points": len(daily_activity),
                },
                "db": {
                    "tables_queried": [
                        "users",
                        "user_actions",
                        "user_canonical_plans",
                        "messages",
                        "chat_instances",
                        "notifications",
                    ]
                },
            }
        )

    except Exception as e:
        logger.exception("Failed to fetch system overview")
        return admin_fail(
            request=request,
            code="SYSTEM_OVERVIEW_FAILED",
            message="Failed to fetch system overview metrics",
            details={"exception": str(e)},
            debug={
                "input": {
                    "query_params": query_params,
                    "requested_days": requested_days,
                }
            },
            status_code=500
        )
