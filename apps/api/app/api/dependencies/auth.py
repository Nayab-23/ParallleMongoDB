"""
Centralized authentication dependencies for FastAPI.

This module provides a single source of truth for authentication
and authorization across all API endpoints, especially admin routes.
"""
import logging
import os
from fastapi import Request, Depends, HTTPException, status
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from database import get_db
from models import User
from config import config

logger = logging.getLogger(__name__)

# Auth configuration (must match main.py)
SECRET_KEY = config.SECRET_KEY
ALGORITHM = "HS256"


def normalize_email(email: str | None) -> str | None:
    """Normalize an email for comparisons."""
    if email is None:
        return None
    normalized = email.strip().lower()
    return normalized or None


def parse_admin_emails() -> set[str]:
    """
    Parse ADMIN_EMAILS env var into a normalized set.

    Uses the raw env var to avoid stale values, with config as a fallback.
    """
    raw_emails = os.getenv("ADMIN_EMAILS", config.ADMIN_EMAILS_STR or "")
    if isinstance(raw_emails, str):
        return {
            normalized
            for normalized in (normalize_email(part) for part in raw_emails.split(","))
            if normalized
        }

    try:
        return {
            normalized
            for normalized in (normalize_email(part) for part in raw_emails)
            if normalized
        }
    except TypeError:
        return set()


def is_platform_admin_user(user: User, admin_emails: set[str] | None = None) -> bool:
    """
    Determine if a user is a platform admin via DB flag or allowlist.
    """
    admin_set = admin_emails if admin_emails is not None else parse_admin_emails()
    if getattr(user, "is_platform_admin", False):
        return True

    email_normalized = normalize_email(getattr(user, "email", None))
    return bool(email_normalized and email_normalized in admin_set)


def maybe_persist_platform_admin(
    user: User, db: Session, admin_emails: set[str] | None = None
) -> bool:
    """
    Persist platform admin flag when the email is on the allowlist.

    Returns True if the flag was updated, False otherwise.
    """
    admin_set = admin_emails if admin_emails is not None else parse_admin_emails()
    email_normalized = normalize_email(getattr(user, "email", None))
    allowlist_match = bool(email_normalized and email_normalized in admin_set)

    if allowlist_match and not getattr(user, "is_platform_admin", False):
        try:
            user.is_platform_admin = True
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(
                "Elevated user to platform admin based on ADMIN_EMAILS",
                extra={"user_id": getattr(user, "id", None), "email": user.email},
            )
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Failed to persist platform admin flag",
                extra={
                    "user_id": getattr(user, "id", None),
                    "email": user.email,
                    "error": str(exc),
                },
            )
            try:
                db.rollback()
            except Exception:
                pass
    return False


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """
    Extract and validate the current authenticated user from JWT cookie.

    This is the ONLY authentication dependency used across the application.
    All endpoints requiring authentication must use this function.

    Args:
        request: FastAPI request object (for cookie access)
        db: Database session

    Returns:
        User: Authenticated user object

    Raises:
        HTTPException: 401 if token is missing, invalid, or user not found
    """
    token = request.cookies.get("access_token")

    if not token:
        logger.debug("Authentication failed: No access_token cookie")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")

        if user_id is None:
            logger.warning("Authentication failed: No 'sub' in JWT payload")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
    except JWTError as e:
        logger.warning(f"Authentication failed: JWT decode error - {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user = db.get(User, user_id)

    if not user:
        logger.warning(f"Authentication failed: User ID {user_id} not found in database")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # PERFORMANCE FIX: Only persist admin flag if user is NOT already marked as admin
    # Previously: Called on EVERY authenticated request, causing DB write on every page load
    # Now: Only writes to DB once when user first becomes admin
    if not getattr(user, "is_platform_admin", False):
        admin_emails = parse_admin_emails()
        maybe_persist_platform_admin(user, db, admin_emails)

    return user


def require_platform_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Verify that the current user is a platform administrator.

    Use this dependency for all admin-only endpoints to ensure
    consistent authorization checks across the platform.

    Args:
        current_user: Authenticated user (injected via get_current_user)

    Returns:
        User: The authenticated admin user

    Raises:
        HTTPException: 403 if user is not a platform admin
    """
    admin_emails = parse_admin_emails()
    email_normalized = normalize_email(getattr(current_user, "email", None))
    allowlist_match = bool(email_normalized and email_normalized in admin_emails)

    if not is_platform_admin_user(current_user, admin_emails):
        logger.warning(
            "Admin access denied",
            extra={
                "user_id": getattr(current_user, "id", None),
                "email": current_user.email,
                "is_platform_admin": getattr(current_user, "is_platform_admin", False),
                "allowlist_match": allowlist_match,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    logger.debug(f"Admin access granted: {current_user.email}")
    return current_user
