"""
Code Events API - Track code changes for agent visibility.

Provides endpoints for:
- Recording code change events (edit, save, commit, etc.)
- Querying recent activity in a repo
- Detecting potential conflicts based on systems touched
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from models import CodeEvent, User, AgentCursor

router = APIRouter(prefix="/code-events", tags=["code-events"])
logger = logging.getLogger(__name__)


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class CodeEventCreate(BaseModel):
    device_id: str = Field(..., description="Device identifier (e.g., vscode-<uuid>)")
    repo_id: str = Field(..., description="Repository identifier")
    branch: Optional[str] = Field(None, description="Git branch name")
    head_sha_before: Optional[str] = Field(None, description="SHA before change")
    head_sha_after: Optional[str] = Field(None, description="SHA after change")
    event_type: str = Field(..., description="Event type: edit|save|commit|apply_patch|checkout|merge")
    files_touched: Optional[List[str]] = Field(None, description="List of file paths touched")
    systems_touched: Optional[List[str]] = Field(None, description="List of system names affected")
    tags: Optional[List[str]] = Field(None, description="Tags like 'refactor', 'bugfix', etc.")
    summary: Optional[str] = Field(None, description="Human-readable summary")
    details: Optional[str] = Field(None, description="Longer explanation of why/what the change accomplishes")
    impact_tags: Optional[List[str]] = Field(None, description="Infrastructure impact tags: db_schema, api_contract, auth_flow, config, deps")


class CodeEventOut(BaseModel):
    id: str
    org_id: str
    user_id: str
    device_id: str
    repo_id: str
    branch: Optional[str]
    head_sha_before: Optional[str]
    head_sha_after: Optional[str]
    event_type: str
    files_touched: Optional[List[str]]
    systems_touched: Optional[List[str]]
    tags: Optional[List[str]]
    summary: Optional[str]
    details: Optional[str]
    impact_tags: Optional[List[str]]
    created_at: datetime

    class Config:
        from_attributes = True


class RecentEventsResponse(BaseModel):
    ok: bool
    events: List[CodeEventOut]
    count: int
    repo_id: str
    time_window_minutes: int


class ConflictEventsResponse(BaseModel):
    ok: bool
    events: List[CodeEventOut]
    count: int
    repo_id: str
    systems_queried: List[str]
    time_window_minutes: int


class RelevantUpdateOut(BaseModel):
    """Compact event representation for updates feed."""
    id: str
    user_id: str
    device_id: str
    branch: Optional[str]
    head_sha_after: Optional[str]
    event_type: str
    systems_touched: Optional[List[str]]
    impact_tags: Optional[List[str]]
    files_touched: Optional[List[str]]  # Limited to 10 in response
    summary: Optional[str]  # Limited to 300 chars in response
    details: Optional[str]  # Limited to 1000 chars in response
    created_at: datetime


class RelevantUpdatesResponse(BaseModel):
    ok: bool
    repo_id: str
    since: str
    count: int
    events: List[RelevantUpdateOut]


class CursorResponse(BaseModel):
    ok: bool
    repo_id: str
    cursor_name: str
    last_seen_at: Optional[datetime]
    last_seen_event_id: Optional[str]


class CursorUpsertRequest(BaseModel):
    repo_id: str
    cursor_name: Optional[str] = Field("code_events", description="Cursor name")
    last_seen_at: Optional[datetime] = Field(None, description="ISO timestamp")
    last_seen_event_id: Optional[str] = Field(None, description="Last seen code_event id")


class UpdatesSinceCursorResponse(BaseModel):
    ok: bool
    repo_id: str
    cursor_name: str
    since: str
    count: int
    events: List[RelevantUpdateOut]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _error_response(request: Request, status_code: int, error_code: str, message: str) -> JSONResponse:
    """Standard error response format."""
    req_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "error_code": error_code,
            "message": message,
            "request_id": req_id,
        },
    )


def _serialize_event(event: CodeEvent) -> CodeEventOut:
    """Convert CodeEvent model to response schema."""
    return CodeEventOut(
        id=str(event.id),
        org_id=event.org_id,
        user_id=event.user_id,
        device_id=event.device_id,
        repo_id=event.repo_id,
        branch=event.branch,
        head_sha_before=event.head_sha_before,
        head_sha_after=event.head_sha_after,
        event_type=event.event_type,
        files_touched=event.files_touched or [],
        systems_touched=event.systems_touched or [],
        tags=event.tags or [],
        summary=event.summary,
        created_at=event.created_at,
    )


def _fetch_updates(
    *,
    db: Session,
    org_id: str,
    repo_id: str,
    cutoff: datetime,
    limit: int,
    focus_systems_list: List[str],
    focus_files_list: List[str],
    focus_impacts_list: List[str],
):
    query = db.query(CodeEvent).filter(
        CodeEvent.org_id == org_id,
        CodeEvent.repo_id == repo_id,
        CodeEvent.created_at > cutoff,
    )

    if focus_systems_list or focus_files_list or focus_impacts_list:
        filter_conditions = []
        if focus_systems_list:
            filter_conditions.append(CodeEvent.systems_touched.op("&&")(focus_systems_list))
        if focus_files_list:
            filter_conditions.append(CodeEvent.files_touched.op("&&")(focus_files_list))
        if focus_impacts_list:
            filter_conditions.append(CodeEvent.impact_tags.op("&&")(focus_impacts_list))
        query = query.filter(or_(*filter_conditions))

    events = (
        query
        .order_by(CodeEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return events


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("", status_code=201)
def create_code_event(
    request: Request,
    payload: CodeEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Record a code change event.

    This endpoint allows VS Code extensions to report code changes
    for agent visibility into development activity.

    Events include: edit, save, commit, apply_patch, checkout, merge

    Returns:
        {"ok": true, "id": "<event-uuid>"}
    """
    if not current_user.org_id:
        return _error_response(
            request,
            403,
            "ORG_REQUIRED",
            "User must belong to an organization to record code events"
        )

    # Validate event_type
    valid_types = {"edit", "save", "commit", "apply_patch", "checkout", "merge", "rebase", "cherry_pick"}
    if payload.event_type not in valid_types:
        return _error_response(
            request,
            400,
            "INVALID_EVENT_TYPE",
            f"event_type must be one of: {', '.join(valid_types)}"
        )

    # Validate and sanitize impact_tags (optional)
    impact_tags = None
    if payload.impact_tags:
        # Trim each tag to max 32 chars and limit to 10 tags
        impact_tags = [tag.strip()[:32] for tag in payload.impact_tags if tag.strip()][:10]

    # Validate and sanitize details (optional)
    details = None
    if payload.details:
        # Cap details length to 4000 chars
        details = payload.details[:4000]

    # Create event record
    event = CodeEvent(
        id=uuid.uuid4(),
        org_id=current_user.org_id,
        user_id=current_user.id,
        device_id=payload.device_id,
        repo_id=payload.repo_id,
        branch=payload.branch,
        head_sha_before=payload.head_sha_before,
        head_sha_after=payload.head_sha_after,
        event_type=payload.event_type,
        files_touched=payload.files_touched or [],
        systems_touched=payload.systems_touched or [],
        tags=payload.tags or [],
        summary=payload.summary,
        details=details,
        impact_tags=impact_tags or [],
        created_at=datetime.now(timezone.utc),
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    logger.info(
        "[CodeEvent] Created event_id=%s user=%s repo=%s type=%s",
        event.id,
        current_user.email,
        payload.repo_id,
        payload.event_type,
    )

    return {
        "ok": True,
        "id": str(event.id),
    }


@router.get("/recent", response_model=RecentEventsResponse)
def get_recent_events(
    request: Request,
    repo_id: str = Query(..., description="Repository ID to query"),
    minutes: int = Query(60, ge=1, le=10080, description="Time window in minutes (max 1 week)"),
    limit: int = Query(100, ge=1, le=1000, description="Max events to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get recent code events in a repository.

    Returns events from the same org within the specified time window.
    Useful for agents to understand recent activity before making changes.

    Query params:
    - repo_id: Repository identifier
    - minutes: Look back this many minutes (default 60, max 1 week)
    - limit: Max events to return (default 100, max 1000)

    Returns:
        List of recent code events, newest first
    """
    if not current_user.org_id:
        return _error_response(
            request,
            403,
            "ORG_REQUIRED",
            "User must belong to an organization"
        )

    # Calculate time cutoff
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    # Query events
    events = (
        db.query(CodeEvent)
        .filter(
            CodeEvent.org_id == current_user.org_id,
            CodeEvent.repo_id == repo_id,
            CodeEvent.created_at >= cutoff,
        )
        .order_by(CodeEvent.created_at.desc())
        .limit(limit)
        .all()
    )

    logger.info(
        "[CodeEvent] Query recent: repo=%s minutes=%d found=%d",
        repo_id,
        minutes,
        len(events),
    )

    return RecentEventsResponse(
        ok=True,
        events=[_serialize_event(e) for e in events],
        count=len(events),
        repo_id=repo_id,
        time_window_minutes=minutes,
    )


@router.get("/conflicts", response_model=ConflictEventsResponse)
def get_conflict_events(
    request: Request,
    repo_id: str = Query(..., description="Repository ID to query"),
    systems: str = Query(..., description="Comma-separated system names (e.g., 'auth,billing')"),
    minutes: int = Query(1440, ge=1, le=10080, description="Time window in minutes (default 24h, max 1 week)"),
    limit: int = Query(100, ge=1, le=1000, description="Max events to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get events that might conflict with planned changes.

    Finds recent events that touched the same systems you're about to modify.
    Helps agents detect potential conflicts and stale branches.

    Query params:
    - repo_id: Repository identifier
    - systems: Comma-separated system names (e.g., "auth,billing,api")
    - minutes: Look back this many minutes (default 24h, max 1 week)
    - limit: Max events to return (default 100, max 1000)

    Returns:
        Events touching the specified systems, newest first
    """
    if not current_user.org_id:
        return _error_response(
            request,
            403,
            "ORG_REQUIRED",
            "User must belong to an organization"
        )

    # Parse systems list
    systems_list = [s.strip() for s in systems.split(",") if s.strip()]
    if not systems_list:
        return _error_response(
            request,
            400,
            "INVALID_SYSTEMS",
            "Must provide at least one system name"
        )

    # Calculate time cutoff
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    # Query events with array overlap
    # PostgreSQL's && operator checks if arrays have any elements in common
    events = (
        db.query(CodeEvent)
        .filter(
            CodeEvent.org_id == current_user.org_id,
            CodeEvent.repo_id == repo_id,
            CodeEvent.created_at >= cutoff,
            CodeEvent.systems_touched.op("&&")(systems_list),  # Array overlap operator
        )
        .order_by(CodeEvent.created_at.desc())
        .limit(limit)
        .all()
    )

    logger.info(
        "[CodeEvent] Query conflicts: repo=%s systems=%s minutes=%d found=%d",
        repo_id,
        systems_list,
        minutes,
        len(events),
    )

    return ConflictEventsResponse(
        ok=True,
        events=[_serialize_event(e) for e in events],
        count=len(events),
        repo_id=repo_id,
        systems_queried=systems_list,
        time_window_minutes=minutes,
    )


@router.get("/updates", response_model=RelevantUpdatesResponse)
def get_relevant_updates(
    request: Request,
    repo_id: str = Query(..., description="Repository ID to query"),
    since: Optional[str] = Query(None, description="ISO timestamp - fetch events after this time (default: now-60min)"),
    limit: int = Query(25, ge=1, le=100, description="Max events to return (default 25, max 100)"),
    focus_systems: Optional[str] = Query(None, description="Comma-separated system names to filter by"),
    focus_files: Optional[str] = Query(None, description="Comma-separated file paths to filter by (exact match)"),
    focus_impacts: Optional[str] = Query(None, description="Comma-separated impact tags to filter by"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get relevant code updates since a cursor timestamp.

    Designed for extension agents to fetch updates filtered by their current work focus.
    Returns events matching ANY of the focus criteria (OR logic).

    Query params:
    - repo_id: Repository identifier (required)
    - since: ISO timestamp - only return events after this time (default: now-60min)
    - limit: Max events to return (default 25, max 100)
    - focus_systems: CSV system names (e.g., "auth,billing")
    - focus_files: CSV file paths for exact match (e.g., "src/auth/login.py,src/api/routes.py")
    - focus_impacts: CSV impact tags (e.g., "db_schema,api_contract")

    Filter logic (OR):
    - Include event if systems_touched overlaps focus_systems
    - OR files_touched overlaps focus_files
    - OR impact_tags overlaps focus_impacts
    - If no focus params provided, return all events since timestamp

    Returns:
        Compact event list with bounded payload (files_touched max 10, summary max 300 chars, details max 1000 chars)
    """
    if not current_user.org_id:
        return _error_response(
            request,
            403,
            "ORG_REQUIRED",
            "User must belong to an organization"
        )

    # Parse since timestamp
    if since:
        try:
            cutoff = datetime.fromisoformat(since.replace('Z', '+00:00'))
        except Exception:
            return _error_response(
                request,
                400,
                "INVALID_SINCE",
                "since must be a valid ISO timestamp"
            )
    else:
        # Default: 60 minutes ago
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=60)

    # Parse focus filters
    focus_systems_list = [s.strip() for s in (focus_systems or "").split(",") if s.strip()]
    focus_files_list = [f.strip() for f in (focus_files or "").split(",") if f.strip()]
    focus_impacts_list = [i.strip() for i in (focus_impacts or "").split(",") if i.strip()]

    events = _fetch_updates(
        db=db,
        org_id=current_user.org_id,
        repo_id=repo_id,
        cutoff=cutoff,
        limit=limit,
        focus_systems_list=focus_systems_list,
        focus_files_list=focus_files_list,
        focus_impacts_list=focus_impacts_list,
    )

    logger.info(
        "[CodeEvent] Query updates: repo=%s since=%s focus_systems=%s focus_files=%s focus_impacts=%s found=%d",
        repo_id,
        cutoff.isoformat(),
        focus_systems_list,
        focus_files_list,
        focus_impacts_list,
        len(events),
    )

    # Build compact response with bounded payloads
    compact_events = [
        RelevantUpdateOut(
            id=str(event.id),
            user_id=event.user_id,
            device_id=event.device_id,
            branch=event.branch,
            head_sha_after=event.head_sha_after,
            event_type=event.event_type,
            systems_touched=event.systems_touched or [],
            impact_tags=event.impact_tags or [],
            files_touched=(event.files_touched or [])[:10],  # Max 10 files
            summary=(event.summary or "")[:300] if event.summary else None,  # Max 300 chars
            details=(event.details or "")[:1000] if event.details else None,  # Max 1000 chars
            created_at=event.created_at,
        )
        for event in events
    ]

    return RelevantUpdatesResponse(
        ok=True,
        repo_id=repo_id,
        since=cutoff.isoformat(),
        count=len(compact_events),
        events=compact_events,
    )


@router.get("/cursor", response_model=CursorResponse)
def get_code_event_cursor(
    request: Request,
    repo_id: str = Query(..., description="Repository ID to query"),
    cursor_name: str = Query("code_events", description="Cursor name"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.org_id:
        return _error_response(request, 403, "ORG_REQUIRED", "User must belong to an organization")

    cursor = (
        db.query(AgentCursor)
        .filter(
            AgentCursor.org_id == current_user.org_id,
            AgentCursor.user_id == current_user.id,
            AgentCursor.repo_id == repo_id,
            AgentCursor.cursor_name == cursor_name,
        )
        .first()
    )
    return {
        "ok": True,
        "repo_id": repo_id,
        "cursor_name": cursor_name,
        "last_seen_at": cursor.last_seen_at if cursor else None,
        "last_seen_event_id": str(cursor.last_seen_event_id) if cursor and cursor.last_seen_event_id else None,
    }


@router.post("/cursor", response_model=CursorResponse)
def upsert_code_event_cursor(
    request: Request,
    payload: CursorUpsertRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.org_id:
        return _error_response(request, 403, "ORG_REQUIRED", "User must belong to an organization")

    cursor_name = payload.cursor_name or "code_events"
    last_seen_event_id = None
    if payload.last_seen_event_id:
        try:
            last_seen_event_id = uuid.UUID(str(payload.last_seen_event_id))
        except Exception:
            return _error_response(request, 400, "INVALID_EVENT_ID", "last_seen_event_id must be a valid UUID")

    cursor = (
        db.query(AgentCursor)
        .filter(
            AgentCursor.org_id == current_user.org_id,
            AgentCursor.user_id == current_user.id,
            AgentCursor.repo_id == payload.repo_id,
            AgentCursor.cursor_name == cursor_name,
        )
        .first()
    )

    now_ts = datetime.now(timezone.utc)
    if cursor:
        cursor.last_seen_at = payload.last_seen_at
        cursor.last_seen_event_id = last_seen_event_id
        cursor.updated_at = now_ts
    else:
        cursor = AgentCursor(
            org_id=current_user.org_id,
            user_id=current_user.id,
            repo_id=payload.repo_id,
            cursor_name=cursor_name,
            last_seen_at=payload.last_seen_at,
            last_seen_event_id=last_seen_event_id,
            updated_at=now_ts,
        )
        db.add(cursor)

    db.commit()
    db.refresh(cursor)

    return {
        "ok": True,
        "repo_id": payload.repo_id,
        "cursor_name": cursor_name,
        "last_seen_at": cursor.last_seen_at,
        "last_seen_event_id": str(cursor.last_seen_event_id) if cursor.last_seen_event_id else None,
    }


@router.get("/updates-since-cursor", response_model=UpdatesSinceCursorResponse)
def get_updates_since_cursor(
    request: Request,
    repo_id: str = Query(..., description="Repository ID to query"),
    cursor_name: str = Query("code_events", description="Cursor name"),
    limit: int = Query(25, ge=1, le=100, description="Max events to return"),
    focus_systems: Optional[str] = Query(None, description="Comma-separated system names to filter by"),
    focus_files: Optional[str] = Query(None, description="Comma-separated file paths to filter by (exact match)"),
    focus_impacts: Optional[str] = Query(None, description="Comma-separated impact tags to filter by"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.org_id:
        return _error_response(request, 403, "ORG_REQUIRED", "User must belong to an organization")

    cursor = (
        db.query(AgentCursor)
        .filter(
            AgentCursor.org_id == current_user.org_id,
            AgentCursor.user_id == current_user.id,
            AgentCursor.repo_id == repo_id,
            AgentCursor.cursor_name == cursor_name,
        )
        .first()
    )
    since_dt = cursor.last_seen_at if cursor and cursor.last_seen_at else datetime.now(timezone.utc) - timedelta(minutes=60)

    # Parse focus filters
    focus_systems_list = [s.strip() for s in (focus_systems or "").split(",") if s.strip()]
    focus_files_list = [f.strip() for f in (focus_files or "").split(",") if f.strip()]
    focus_impacts_list = [i.strip() for i in (focus_impacts or "").split(",") if i.strip()]

    events = _fetch_updates(
        db=db,
        org_id=current_user.org_id,
        repo_id=repo_id,
        cutoff=since_dt,
        limit=limit,
        focus_systems_list=focus_systems_list,
        focus_files_list=focus_files_list,
        focus_impacts_list=focus_impacts_list,
    )

    compact_events = [
        RelevantUpdateOut(
            id=str(event.id),
            user_id=event.user_id,
            device_id=event.device_id,
            branch=event.branch,
            head_sha_after=event.head_sha_after,
            event_type=event.event_type,
            systems_touched=event.systems_touched or [],
            impact_tags=event.impact_tags or [],
            files_touched=(event.files_touched or [])[:10],
            summary=(event.summary or "")[:300] if event.summary else None,
            details=(event.details or "")[:1000] if event.details else None,
            created_at=event.created_at,
        )
        for event in events
    ]

    logger.info(
        "[CodeEvent] Updates since cursor: repo=%s cursor=%s since=%s found=%d",
        repo_id,
        cursor_name,
        since_dt.isoformat(),
        len(compact_events),
    )

    return {
        "ok": True,
        "repo_id": repo_id,
        "cursor_name": cursor_name,
        "since": since_dt.isoformat(),
        "count": len(compact_events),
        "events": compact_events,
    }
