"""
Shared dependencies for API endpoints.
"""
from .auth import (
    get_current_user,
    maybe_persist_platform_admin,
    parse_admin_emails,
    require_platform_admin,
    is_platform_admin_user,
)

__all__ = [
    "get_current_user",
    "maybe_persist_platform_admin",
    "parse_admin_emails",
    "require_platform_admin",
    "is_platform_admin_user",
]
