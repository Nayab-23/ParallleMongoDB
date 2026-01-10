"""
Compatibility endpoints for legacy frontend calls.

The frontend calls /api/v1/rooms and /api/v1/users which don't exist in the v1 API.
These endpoints provide aliases to the correct v1 endpoints.
"""
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.api.v1.workspaces import WorkspaceOut, list_workspaces
from models import User

router = APIRouter()


@router.get("/rooms", response_model=List[WorkspaceOut])
def list_rooms_alias(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Alias for /workspaces endpoint.
    Frontend calls /api/v1/rooms but v1 API uses 'workspaces' terminology.
    """
    return list_workspaces(current_user=current_user, db=db)


@router.get("/users")
def list_users_alias(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return list of users in the current user's organization.
    Used by frontend for @mentions and team management.
    """
    import logging

    logger = logging.getLogger(__name__)

    logger.info(f"[USERS] Fetching users for org {current_user.org_id}")

    # Get users in the same org
    from models import User as UserORM

    if not current_user.org_id:
        logger.info("[USERS] No org_id on current user; returning empty list")
        return []

    users = (
        db.query(UserORM)
        .filter(UserORM.org_id == current_user.org_id)
        .all()
    )

    logger.info(f"[USERS] Found {len(users)} users")

    result = [
        {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "org_id": user.org_id
        }
        for user in users
    ]

    logger.info(f"[USERS] Returning {len(result)} user objects")
    return result
