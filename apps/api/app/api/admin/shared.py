"""
Shared admin endpoints and helpers (users endpoint).
"""
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from models import User
from app.api.dependencies import (
    require_platform_admin,
    is_platform_admin_user,
    parse_admin_emails,
)
from app.api.admin.utils import admin_ok, admin_fail
from app.services import log_buffer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/users")
async def get_all_users(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_platform_admin),
):
    """Get all users (admin only) for admin dropdowns with debugging."""
    try:
        query_params = dict(request.query_params)
        admin_emails = parse_admin_emails()
        users = db.query(User).order_by(User.email).all()

        users_data = [
            {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "org_id": getattr(user, "org_id", None),
                "is_platform_admin": is_platform_admin_user(user, admin_emails),
            }
            for user in users
        ]

        users_count = len(users_data)
        platform_admins_count = sum(1 for u in users_data if u["is_platform_admin"])

        return admin_ok(
            request=request,
            data={
                "users": users_data,
                "total_users": users_count,
            },
            debug={
                "input": {
                    "query_params": query_params,
                    "defaults_applied": {},
                },
                "output": {
                    "users_count": users_count,
                    "platform_admins_count": platform_admins_count,
                },
                "db": {"tables_queried": ["users"]},
            }
        )

    except Exception as e:
        logger.exception("Failed to fetch users for admin endpoint")
        return admin_fail(
            request=request,
            code="USERS_FETCH_FAILED",
            message="Failed to fetch users",
            details={"exception": str(e)},
            debug={"input": {"query_params": query_params}},
            status_code=500
        )
