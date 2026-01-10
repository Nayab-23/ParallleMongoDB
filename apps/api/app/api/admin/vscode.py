"""
Admin VSCode Debug API Endpoints
Provides VSCode integration monitoring and activity diagnostics for platform admins.
"""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from database import get_db
from models import User, UserAction, Message, Notification
from datetime import datetime, timedelta
from typing import Optional
import json
import logging

from app.api.dependencies import require_platform_admin
from app.api.admin.utils import admin_ok, admin_fail, sanitize_for_json

logger = logging.getLogger(__name__)

router = APIRouter()


def _safe_json(value):
    if isinstance(value, dict):
        return {k: _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(v) for v in value]
    return sanitize_for_json(value)


@router.get("/vscode-debug/{user_email}")
async def get_vscode_debug(
    request: Request,
    user_email: str,
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin)
):
    """
    Get VSCode activity debug info for a specific user.
    Admin only.

    Frontend calls: GET /api/admin/vscode-debug/{user_email}?start_date=...&end_date=...

    Returns:
    - VSCode link status
    - Activity summary (edits, commits, debug sessions)
    - Recent activity timeline
    - Context requests
    - Conflicts detected
    - Notifications sent
    """
    logger.info(f"[VSCode Debug] 🔍 GET /vscode-debug/{user_email} called by {current_user.email}")

    logger.debug(f"[VSCode Debug] ✅ Admin access verified for {current_user.email}")

    # STEP 2: Find target user
    logger.debug(f"[VSCode Debug] Querying user: {user_email}")
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        logger.error(f"[VSCode Debug] ❌ User not found: {user_email}")
        return admin_fail(
            request=request,
            code="NOT_FOUND",
            message=f"User {user_email} not found",
            details={"user_email": user_email},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=404,
        )

    logger.debug(f"[VSCode Debug] ✅ Found user: {user.email} (ID: {user.id})")

    # STEP 3: Parse date range (default to last 7 days)
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except Exception as e:
            logger.error(f"[VSCode Debug] ❌ Invalid end_date format: {end_date}")
            return admin_fail(
                request=request,
                code="VALIDATION_ERROR",
                message=f"Invalid end_date format: {str(e)}",
                details={"end_date": end_date},
                debug={"input": {"query_params": dict(request.query_params)}},
                status_code=400,
            )
    else:
        end_dt = datetime.now()

    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        except Exception as e:
            logger.error(f"[VSCode Debug] ❌ Invalid start_date format: {start_date}")
            return admin_fail(
                request=request,
                code="VALIDATION_ERROR",
                message=f"Invalid start_date format: {str(e)}",
                details={"start_date": start_date},
                debug={"input": {"query_params": dict(request.query_params)}},
                status_code=400,
            )
    else:
        start_dt = end_dt - timedelta(days=7)

    logger.info(f"[VSCode Debug] Date range: {start_dt.date()} to {end_dt.date()} ({(end_dt - start_dt).days} days)")

    # STEP 4: Get VSCode activity (UserAction with tool='vscode')
    logger.debug(f"[VSCode Debug] Querying VSCode actions...")
    vscode_actions = db.query(UserAction).filter(
        and_(
            UserAction.user_id == user.id,
            UserAction.tool == 'vscode',
            UserAction.timestamp >= start_dt,
            UserAction.timestamp <= end_dt
        )
    ).order_by(UserAction.timestamp.desc()).all()

    logger.info(f"[VSCode Debug] Found {len(vscode_actions)} VSCode actions")

    # STEP 5: Get VSCode-related chat messages
    logger.debug(f"[VSCode Debug] Querying VSCode-related chats...")
    vscode_chats = db.query(Message).filter(
        and_(
            Message.user_id == user.id,
            Message.created_at >= start_dt,
            Message.created_at <= end_dt
        )
    ).filter(
        or_(
            Message.content.ilike('%vscode%'),
            Message.content.ilike('%code%'),
            Message.content.ilike('%file%')
        )
    ).order_by(Message.created_at.desc()).limit(50).all()

    logger.debug(f"[VSCode Debug] Found {len(vscode_chats)} VSCode-related chat messages")

    # STEP 6: Get conflict notifications
    logger.debug(f"[VSCode Debug] Querying conflict notifications...")
    conflict_notifications = db.query(Notification).filter(
        and_(
            Notification.user_id == user.id,
            Notification.source_type.in_(['conflict_file', 'conflict_semantic']),
            Notification.created_at >= start_dt,
            Notification.created_at <= end_dt
        )
    ).order_by(Notification.created_at.desc()).all()

    logger.info(f"[VSCode Debug] Found {len(conflict_notifications)} conflict notifications")

    # STEP 7: Aggregate statistics
    logger.debug(f"[VSCode Debug] Aggregating statistics...")
    total_actions = len(vscode_actions)
    action_types = {}
    files_edited = set()
    projects = set()

    for action in vscode_actions:
        # Count by action type
        action_type = action.action_type or 'unknown'
        action_types[action_type] = action_types.get(action_type, 0) + 1

        # Extract files and projects from action_data
        if action.action_data:
            try:
                data = action.action_data if isinstance(action.action_data, dict) else json.loads(action.action_data)

                # Files
                if 'file_path' in data:
                    files_edited.add(data['file_path'])
                if 'files' in data and isinstance(data['files'], list):
                    files_edited.update(data['files'])

                # Projects
                if 'project_name' in data:
                    projects.add(data['project_name'])
            except Exception as e:
                logger.debug(f"[VSCode Debug] Could not parse action_data for action {action.id}: {e}")

    logger.info(f"[VSCode Debug] Statistics: {total_actions} actions, {len(files_edited)} files, {len(projects)} projects")

    # STEP 8: Build response
    response = {
        "user": user_email,
        "date_range": {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat()
        },
        "vscode_linked": total_actions > 0,
        "last_activity": vscode_actions[0].timestamp.isoformat() if vscode_actions else None,

        "activity_summary": {
            "total_actions": total_actions,
            "total_edits": action_types.get('code_edit', 0) + action_types.get('file_save', 0),
            "total_commits": action_types.get('git_commit', 0),
            "total_debug_sessions": action_types.get('debug_session', 0),
            "files_edited": list(files_edited),
            "files_count": len(files_edited),
            "projects": list(projects),
            "action_types": action_types
        },

        "recent_activity": [
            {
                "id": action.id,
                "timestamp": action.timestamp.isoformat(),
                "event_type": action.action_type,
                "action_data": action.action_data,
                "session_id": action.session_id
            }
            for action in vscode_actions[:20]  # Last 20 actions
        ],

        "context_requests": [
            {
                "timestamp": chat.created_at.isoformat(),
                "type": "chat",
                "content": chat.content[:200],  # First 200 chars
                "role": chat.role
            }
            for chat in vscode_chats
        ],

        "conflicts_detected": [
            {
                "id": notif.id,
                "timestamp": notif.created_at.isoformat(),
                "conflict_type": "file" if notif.source_type == "conflict_file" else "semantic",
                "title": notif.title,
                "message": notif.message,
                "notification_sent": True,
                "read": notif.is_read,
                "data": notif.data
            }
            for notif in conflict_notifications
        ],

        "notifications": {
            "smart_team_updates": db.query(func.count(Notification.id)).filter(
                and_(
                    Notification.user_id == user.id,
                    Notification.type == 'smart_team_update',
                    Notification.created_at >= start_dt
                )
            ).scalar() or 0,
            "conflict_notifications": len(conflict_notifications),
            "last_conflict_at": conflict_notifications[0].created_at.isoformat() if conflict_notifications else None
        }
    }

    logger.info(f"[VSCode Debug] ✅ Returning VSCode debug data for {user_email} (vscode_linked: {response['vscode_linked']}, actions: {total_actions})")
    try:
        return admin_ok(
            request=request,
            data=_safe_json(response),
            debug={
                "input": {"query_params": dict(request.query_params)},
                "output": {
                    "total_actions": total_actions,
                    "conflict_notifications": len(conflict_notifications),
                    "vscode_linked": response["vscode_linked"],
                },
                "db": {"tables_queried": ["users", "user_actions", "messages", "notifications"]},
            },
        )
    except Exception as exc:
        logger.exception("Failed to return VSCode debug data", exc_info=True)
        return admin_fail(
            request=request,
            code="VSCODE_DEBUG_ERROR",
            message="Failed to fetch VSCode debug data",
            details={"error": str(exc)},
            debug={"input": {"query_params": dict(request.query_params)}},
            status_code=500,
        )
