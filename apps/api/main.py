import os, re, uuid, json, asyncio, secrets, base64, time, sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Literal
import pytz

_IMPORT_START = time.perf_counter()
_startup_timings: dict[str, float] = {}

from fastapi import FastAPI, Request, Response, Depends, HTTPException, status, APIRouter, BackgroundTasks, Body, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from pydantic import BaseModel
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy import func, event, or_, desc
from sqlalchemy.orm.attributes import flag_modified
from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request as StarletteRequest
import inspect, httpx

from starlette.middleware.sessions import SessionMiddleware

from database import SessionLocal, Base, engine
from models import (
    User,
    User as UserORM,
    UserCredential as UserCredentialORM,
    Organization as OrganizationORM,
    Room as RoomORM,
    ChatInstance as ChatInstanceORM,
    Message as MessageORM,
    InboxTask as InboxTaskORM,
    Notification as NotificationORM,
    MemoryRecord as MemoryORM,
    AgentProfile as AgentORM,
    Task as TaskORM,
    RoomMember as RoomMemberORM,
    ExternalAccount as ExternalAccountORM,
    DailyBrief as DailyBriefORM,
    EventLog as EventLogORM,
    CompletedBriefItem,
    UserCanonicalPlan,
    CreateUserRequest,
    AuthLoginRequest,
    InboxCreateRequest,
    NotificationOut,
    RoleUpdate,
    TaskIn,
    TaskOut,
    TaskUpdate,
    CreateRoomRequest,
    CreateRoomResponse,
    CreateChatInstanceRequest,
    MemoryQueryRequest,
    MessageOut,
    ChatInstanceOut,
    OrgOut,
    OrgMemberOut,
    UserOut,
    ActivateRequest,
    Permissions,
    RoomOut,
    RoomMemberOut,
    RoomMemberCreate,
    InboxTaskOut,
    InboxUpdateRequest,
    UserContextStore,
    UserAction,
    WaitlistSubmission,
)

from openai import OpenAI
from PIL import Image  # for potential image processing on uploads
from config import config, OPENAI_MODEL, openai_client, COOKIE_SECURE
from app.core.settings import get_settings
from urllib.parse import urlencode
from app.api import org_graph, org_stats, outbound, admin, demo
from app.api import oauth as oauth_router_module
from app.api.v1 import router as api_v1_router
from app.api.v1 import graphs as graphs_router
from app.api.v1 import notifications as v1_notifications
from app.api.v1.chats import (
    dispatch_chat_message as v1_dispatch_chat_message,
    DispatchRequest as V1DispatchRequest,
    DispatchResponse as V1DispatchResponse,
)
from app.api.v1.deps import (
    get_current_user as v1_get_current_user,
    get_db as v1_get_db,
    require_scope as v1_require_scope,
)
from app.services import log_buffer
from app.api.admin.middleware import AdminDebugMiddleware
from app.api.dependencies.auth import get_current_user
from app.api.dependencies.auth import (
    is_platform_admin_user,
    maybe_persist_platform_admin,
    parse_admin_emails,
    normalize_email,
)

from app.services.rag import get_relevant_context, build_rag_context
from app.services.conflict_detector import find_conflicts
from app.services.rag import get_relevant_context

import logging
import json

logger = logging.getLogger("parallel-backend")
logger.setLevel(logging.INFO)

MAX_CONTEXT_MESSAGES = 30  # last 30 messages per chat instance
FAST_PATH_SIMPLE = os.getenv("FAST_PATH_SIMPLE", "0").lower() not in {"0", "false", "no", "off"}
FAST_PATH_MAX_INPUT = 200
MAX_RAG_ITEMS = 8
MAX_RAG_ITEM_CHARS = 350
MAX_RAG_TOTAL_CHARS = 2500
CONFLICT_FALLBACK_THROTTLE_SECONDS = 60
_conflict_fallback_last_run: dict[str, datetime] = {}
UNIFIED_RAG_SCOPE = os.getenv("UNIFIED_RAG_SCOPE", "room").lower()
SEMANTIC_CONFLICT_THRESHOLD = float(os.getenv("SEMANTIC_CONFLICT_THRESHOLD", "0.75"))
INTEGRATION_FALLBACK_TAGGING = os.getenv("INTEGRATION_FALLBACK_TAGGING", "1")
ENABLE_CONFLICT_FALLBACK_ON_WRITE = os.getenv("ENABLE_CONFLICT_FALLBACK_ON_WRITE", "0")
INTEGRATION_FALLBACK_TAGGING_BOOL = str(INTEGRATION_FALLBACK_TAGGING).lower() not in {"0", "false", "no", "off"}
ENABLE_CONFLICT_FALLBACK_BOOL = str(ENABLE_CONFLICT_FALLBACK_ON_WRITE).lower() not in {"0", "false", "no", "off"}
OPENAI_TIMEOUT_S = float(os.getenv("OPENAI_TIMEOUT_S", "20"))
EMBED_TIMEOUT_S = float(os.getenv("OPENAI_EMBED_TIMEOUT_S", "10"))
FAST_PATH_HINT_PARAM = "fast_path_hint"


def _initialize_logging() -> None:
    """Attach in-app log handler once to avoid duplicate handlers on reload."""
    if getattr(_initialize_logging, "_initialized", False):
        return
    log_buffer.attach_in_app_log_handler()
    _initialize_logging._initialized = True


def _record_timing(key: str, start_time: float) -> None:
    """Store a startup timing metric in milliseconds."""
    try:
        _startup_timings[key] = (time.perf_counter() - start_time) * 1000
    except Exception:
        # Timing should never break startup
        return


def _get_build_revision() -> str | None:
    return os.getenv("VITE_GIT_SHA") or os.getenv("BACKEND_REV") or os.getenv("GIT_SHA")


def _log_startup_marker() -> None:
    """Log a concise startup marker for release tracking."""
    rev = _get_build_revision()
    parts = [
        f"pid={os.getpid()}",
        f"env={settings.env if 'settings' in globals() else 'unknown'}",
        f"python={sys.version.split()[0]}",
    ]
    if rev:
        parts.append(f"git_rev={rev}")
    logger.info("[STARTUP MARKER] %s", " ".join(parts))


def _log_startup_timings() -> None:
    """Emit collected startup timing metrics."""
    if not _startup_timings:
        return
    for key, value in _startup_timings.items():
        logger.info("[StartupTiming] %s=%.2fms", key, value)


_initialize_logging()


def _env_bool(val: str, default: bool = False) -> bool:
    if val is None:
        return default
    return str(val).lower() in {"1", "true", "yes", "on"}

def _json_log(obj: dict, level=logging.INFO):
    try:
        logging.getLogger("parallel-backend").log(level, json.dumps(obj))
    except Exception:
        logging.getLogger("parallel-backend").log(level, obj)


logger.info(
    "[StartupConfig] conflict_fallback=%s rag_scope=%s fallback_tagging=%s semantic_threshold=%s rag_caps(items=%s,item_chars=%s,total_chars=%s) throttle_s=%s fast_path=%s",
    1 if _env_bool(ENABLE_CONFLICT_FALLBACK_ON_WRITE, False) else 0,
    UNIFIED_RAG_SCOPE,
    1 if _env_bool(INTEGRATION_FALLBACK_TAGGING, True) else 0,
    SEMANTIC_CONFLICT_THRESHOLD,
    MAX_RAG_ITEMS,
    MAX_RAG_ITEM_CHARS,
    MAX_RAG_TOTAL_CHARS,
    CONFLICT_FALLBACK_THROTTLE_SECONDS,
    1 if FAST_PATH_SIMPLE else 0,
)

# Reduce access log noise for common GET endpoints
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

CONTEXT_WINDOW_SIZE = 20
MAX_CONTEXT_TOKENS = 8000  # rough estimate; 1 token ~= 4 chars

FORMATTING_INSTRUCTIONS = """
CRITICAL FORMATTING RULES:

1. CODE BLOCKS:
   - Always use ```language syntax (e.g., ```python, ```javascript, ```bash)
   - Specify the language for proper syntax highlighting
   - Include brief comments for clarity
   - Format with proper indentation

2. INLINE CODE:
   - Use `backticks` for:
     * Variable names: `user_id`
     * Function names: `fetch()`
     * Commands: `npm install`
     * File names: `main.py`
     * Short code snippets

3. TEXT FORMATTING:
   - Use **bold** for key concepts or emphasis
   - Use bullet points for lists
   - Use numbered lists for sequential steps
   - Keep responses clear and well-structured

4. WHEN ANALYZING CODE FILES:
   - Reference specific line numbers
   - Explain what the code does
   - Suggest improvements with code examples
   - Use proper formatting for all code snippets

5. WHEN ANALYZING IMAGES:
   - Describe what you see clearly
   - If it's a screenshot of code, transcribe it with proper formatting
- If it's a diagram, explain the structure
"""

# Embedding helper for pgvector semantic search
def generate_embedding(text: str) -> list[float] | None:
    """Generate embedding for text using OpenAI."""
    if not text or len(text.strip()) < 10:
        return None
    try:
        client = openai_client or OpenAI()  # Uses OPENAI_API_KEY from env
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text[:8000],  # Truncate to model limit
            timeout=EMBED_TIMEOUT_S,
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"[Embedding] Failed to generate: {e}")
        return None


def get_or_generate_message_summary(message, db: Session) -> str:
    """
    Get cached summary or generate new one with caching.
    Deterministic - same message always returns same summary.
    Reduces OpenAI API costs by 95%+ for team activity endpoint.
    """
    # Check if we need to add cached_summary column
    if not hasattr(message, 'cached_summary'):
        logger.warning("[Activity] Message model missing cached_summary column - using uncached summarization")
        text = (message.content or "").strip()
        if not text:
            return "[No content]"
        if len(text) <= 50:
            return text
        # Fallback: truncate without caching
        return text[:50] + ("..." if len(text) > 50 else "")

    # Return cached if exists
    if message.cached_summary:
        return message.cached_summary

    # Generate summary
    text = (message.content or "").strip()

    # Skip empty messages
    if not text:
        summary = "[No content]"
    else:
        # Generate AI summary for ALL messages (deterministic with temp=0)
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=20,
                temperature=0,  # Deterministic (same input = same output)
                messages=[{
                    "role": "user",
                    "content": f"Summarize this activity in under 10 words: {text}"
                }]
            )
            summary = response.choices[0].message.content.strip()
            logger.debug(f"[Activity] Generated summary for message {message.id}: '{summary}'")
        except Exception as e:
            logger.error(f"[Activity] LLM summary failed for message {message.id}: {e}")
            # Fallback: truncate intelligently
            summary = text[:50] + ("..." if len(text) > 50 else "")

    # Cache it in database
    try:
        message.cached_summary = summary
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(message, "cached_summary")
        db.commit()
        logger.debug(f"[Activity] Cached summary for message {message.id}")
    except Exception as e:
        logger.warning(f"[Activity] Failed to cache summary: {e}")
        # Continue without caching

    return summary


def summarize_activity_message(message: str, max_length: int = 60) -> str:
    """
    Use AI to intelligently summarize activity messages.
    Falls back to truncation on errors.

    Examples:
    - "Discussing: I specifically want to make the UX very nice..." → "Improving UX design"
    - "LeetCode offers coding challenges..." → "Shared LeetCode resource"
    - "hi — 07:34 PM" → "Greeting team"
    """
    if not message or message.strip() == "":
        return "[No recent activity]"

    message = message.strip()

    # Quick checks for very short messages
    if len(message) < 10:
        if message.lower() in ["hi", "hello", "hey", "yo"]:
            return "Greeting team"
        return message

    # If already short enough, return as-is
    if len(message) <= max_length:
        return message

    # Use AI for intelligent summarization
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=20,
            temperature=0.3,  # Lower temperature for consistent summaries
            messages=[{
                "role": "user",
                "content": f"""Summarize this team activity message in 3-5 words. Be concise and action-oriented.

Message: "{message}"

Requirements:
- Maximum 5 words
- Use present tense verbs (e.g., "Working on", "Discussing", "Sharing")
- Focus on the action, not details
- Be professional

Examples:
- "Discussing: I want to make the UX really nice and apple-ish" → "Improving UX design"
- "LeetCode offers coding challenges for technical interviews" → "Sharing LeetCode resource"
- "Can someone review my PR?" → "Requesting code review"
- "Just pushed the auth changes" → "Updating authentication"

Summary:"""
            }]
        )

        summary = response.choices[0].message.content.strip()

        # Validate length
        if len(summary) > max_length:
            summary = summary[:max_length].rsplit(' ', 1)[0] + "..."

        logger.debug(f"[AI Summary] '{message[:50]}...' → '{summary}'")
        return summary

    except Exception as e:
        logger.warning(f"[AI Summary] Failed to summarize message: {e}")
        # Fallback to intelligent truncation
        if len(message) > max_length:
            truncated = message[:max_length]
            last_space = truncated.rfind(" ")
            if last_space > max_length // 2:
                return truncated[:last_space] + "..."
            return truncated + "..."
        return message


# ============================================================


# App + CORS


def _is_admin_path(request: Request) -> bool:
    try:
        return request.url.path.startswith("/api/admin")
    except Exception:
        return False


def _admin_fail_response(
    request: Request,
    *,
    code: str,
    message: str,
    status_code: int,
    details: dict | None = None,
    debug: dict | None = None,
):
    """Return admin_fail if available, otherwise fallback to JSONResponse."""
    debug_payload = debug or {}
    try:
        from app.api.admin.utils import admin_fail

        return admin_fail(
            request=request,
            code=code,
            message=message,
            details=details or {},
            debug=debug_payload,
            status_code=status_code,
        )
    except Exception:
        request_id = getattr(request.state, "request_id", None)
        start_time = getattr(request.state, "_start_time", None)
        duration_ms = int((time.time() - start_time) * 1000) if start_time else None
        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "request_id": request_id,
                "duration_ms": duration_ms,
                "data": None,
                "debug": debug_payload,
                "error": {
                    "code": code,
                    "message": message,
                    "details": details or {},
                },
            },
        )


_app_create_start = time.perf_counter()
app = FastAPI(title="Parallel Workspace — Clean Rebuild")
_record_timing("app_create_ms", _app_create_start)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    client_req_id = request.headers.get("X-Client-Request-Id")
    req_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    request.state.request_id = req_id
    request.state.client_request_id = client_req_id
    request.state._start_time = time.perf_counter()
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        # Let exception handlers handle logging/response
        raise exc
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-Id"] = req_id
    if client_req_id:
        response.headers["X-Client-Request-Id"] = client_req_id
    logger.debug(
        "[Request] id=%s path=%s method=%s duration_ms=%.2f",
        req_id,
        request.url.path,
        request.method,
        duration_ms,
    )
    return response

api_router = APIRouter(prefix="/api")

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://localhost:5175",
    "http://localhost:5176",
    "http://localhost:3000",
]
extra_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "").split(",")
    if origin.strip()
]
for origin in extra_origins:
    if origin not in origins:
        origins.append(origin)

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---- auth config (unchanged) ----
SECRET_KEY = config.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

_middleware_setup_start = time.perf_counter()
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,              # same key you already use for JWTs
    same_site=config.COOKIE_SAMESITE,   # align with cookie policy
    https_only=config.COOKIE_SECURE,    # allow HTTP in local dev
)

app.add_middleware(AdminDebugMiddleware)

# ---- middleware ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
_record_timing("middleware_setup_ms", _middleware_setup_start)


@app.exception_handler(Exception)
async def json_exception_handler(request: Request, exc: Exception):
    req_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    user_id = getattr(getattr(request, "user", None), "id", None)
    duration_ms = None
    try:
        start_time = getattr(request.state, "_start_time", None)
        if start_time:
            duration_ms = (time.time() - start_time) * 1000
    except Exception:
        duration_ms = None

    error_code = "UNKNOWN_500"
    if isinstance(exc, HTTPException):
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            error_code = "AUTH_401"
        elif exc.status_code == status.HTTP_403_FORBIDDEN:
            error_code = "AUTH_403"
        elif exc.status_code >= 500:
            error_code = "INTERNAL_ERROR"
    elif isinstance(exc, RequestValidationError):
        error_code = "VALIDATION_ERROR"

    _json_log(
        {
            "at": "error",
            "request_id": req_id,
            "path": request.url.path,
            "method": request.method,
            "user": user_id,
            "duration_ms": duration_ms,
            "error_code": error_code,
            "exc_type": type(exc).__name__,
            "message": str(exc),
        },
        level=logging.ERROR,
    )
    status_code = getattr(exc, "status_code", 500)
    return JSONResponse(
        status_code=status_code if status_code < 600 else 500,
        content={
            "ok": False,
            "error_code": error_code,
            "message": "Request failed" if status_code >= 500 else str(exc),
            "request_id": req_id,
        },
        media_type="application/json",
    )


@app.exception_handler(RequestValidationError)
async def admin_request_validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return admin envelope for validation errors on admin routes; otherwise fallback to default handler."""
    if not _is_admin_path(request):
        return await request_validation_exception_handler(request, exc)

    debug = {"input": {"query_params": dict(request.query_params)}}
    return _admin_fail_response(
        request,
        code="VALIDATION_ERROR",
        message="Invalid request parameters",
        status_code=status.HTTP_400_BAD_REQUEST,
        details={"errors": exc.errors()},
        debug=debug,
    )


@app.exception_handler(HTTPException)
async def admin_http_exception_handler(request: Request, exc: HTTPException):
    """Return admin envelope for HTTPExceptions on admin routes; otherwise fallback to default handler."""
    if not _is_admin_path(request):
        return await http_exception_handler(request, exc)

    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        code = "UNAUTHORIZED"
    elif exc.status_code == status.HTTP_403_FORBIDDEN:
        code = "FORBIDDEN"
    elif exc.status_code == status.HTTP_404_NOT_FOUND:
        code = "NOT_FOUND"
    else:
        code = "HTTP_ERROR"

    debug = {"input": {"query_params": dict(request.query_params)}}
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    details = {"detail": exc.detail} if exc.detail is not None else {}
    details["status_code"] = exc.status_code

    return _admin_fail_response(
        request,
        code=code,
        message=message,
        status_code=exc.status_code,
        details=details,
        debug=debug,
    )


@app.exception_handler(Exception)
async def admin_generic_exception_handler(request: Request, exc: Exception):
    """Return admin envelope for unexpected exceptions on admin routes; otherwise fall back to default 500."""
    if not _is_admin_path(request):
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    debug = {"input": {"query_params": dict(request.query_params)}}
    return _admin_fail_response(
        request,
        code="INTERNAL_ERROR",
        message="An unexpected error occurred",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details={"exception": str(exc)},
        debug=debug,
    )


@app.on_event("startup")
async def validate_rag_mode():
    """
    Fail fast if semantic RAG is requested on an unsupported backend.
    """
    if settings.rag_enabled and settings.is_sqlite:
        raise RuntimeError(
            "RAG_ENABLED=true requires Postgres + pgvector. "
            "Set DATABASE_URL to Postgres or disable RAG for SQLite/dev."
        )
    if not settings.rag_enabled and settings.is_sqlite:
        logger.info(
            "RAG disabled for SQLite/dev mode; semantic search will use keyword + recency only."
        )

# Allowed user roles (short-term); can override via env
ROLE_OPTIONS = [
    r.strip()
    for r in os.getenv("ROLE_OPTIONS", "").split(",")
    if r.strip()
]

# Mock GitHub repo data (until real integration is wired)
GITHUB_MOCK_FILES = [
    {"path": "README.md", "type": "file"},
    {"path": "docs/plan.md", "type": "file"},
    {"path": "src/app.py", "type": "file"},
    {"path": "src/api/routes.py", "type": "file"},
]
GITHUB_MOCK_CONTENT = {
    "README.md": "# Mock Repo\n\nConnect GitHub to see real content.\n",
    "docs/plan.md": "# Plan\n\n- [ ] Hook up GitHub OAuth\n- [ ] List files from API\n- [ ] Edit and commit\n",
    "src/app.py": "print('hello from mock repo')\n",
    "src/api/routes.py": "# routes placeholder\n",
}

# ============================================================


# Models + classes


# ============================================================

class AskModeRequest(BaseModel):
    user_id: str
    user_name: str
    content: str
    mode: Literal["self", "teammate", "team"] = "self"
    target_agent: Optional[str] = None
    include_context_preview: Optional[bool] = False


class ChatAskRequest(BaseModel):
    message: Optional[str] = None
    content: Optional[str] = None
    mode: Optional[str] = "self"
    include_context_preview: Optional[bool] = False

class RoomResponse(BaseModel):
    room_id: str
    room_name: str
    active_chat_id: Optional[str] = None
    active_chat_name: Optional[str] = None
    project_summary: str
    memory_summary: str
    memory_count: int
    messages: List[MessageOut]
    context_preview: Optional[dict] = None

    class Config:
        from_attributes = True


class ChatMessagesResponse(BaseModel):
    chat: ChatInstanceOut
    messages: List[MessageOut]
    context_preview: Optional[dict] = None


def get_context_window(
    db: Session,
    chat_id: str,
    max_messages: int = CONTEXT_WINDOW_SIZE,
    max_tokens: int = MAX_CONTEXT_TOKENS,
) -> List[MessageORM]:
    """
    Fetch recent chat messages for context window, respecting an approximate token budget.
    """
    msgs = (
        db.query(MessageORM)
        .filter(
            MessageORM.chat_instance_id == chat_id,
            MessageORM.role.in_(["user", "assistant"]),
        )
        .order_by(MessageORM.created_at.desc())
        .limit(max_messages)
        .all()
    )

    msgs = list(reversed(msgs))  # chronological
    total_chars = 0
    included: List[MessageORM] = []
    for msg in msgs:
        msg_chars = len(msg.content or "")
        if total_chars + msg_chars > max_tokens * 4:
            logger.info(f"[Context Window] Stopping at {len(included)} messages (token limit approx)")
            break
        included.append(msg)
        total_chars += msg_chars
    return included


def _should_include_context_preview(request: Request, body_data: Optional[dict] = None) -> bool:
    qp = request.query_params.get("include_context_preview")
    if isinstance(qp, str) and qp.lower() in {"1", "true", "yes"}:
        return True
    if body_data:
        val = body_data.get("include_context_preview")
        if isinstance(val, bool):
            return val
        if isinstance(val, str) and val.lower() in {"1", "true", "yes"}:
            return True
    return False


def _get_user_room_ids(db: Session, user_id: str) -> list[str]:
    return [rid for (rid,) in db.query(RoomMemberORM.room_id).filter(RoomMemberORM.user_id == user_id).all()]


def _maybe_conflict_fallback(db: Session, user_action: Optional[UserAction], user: UserORM) -> None:
    """
    Best-effort semantic conflict detection when worker may not be running.
    Bounded by throttle + top matches.
    """
    if not user_action or user_action.activity_embedding is None:
        return
    if not ENABLE_CONFLICT_FALLBACK_BOOL:
        return

    now = datetime.now(timezone.utc)
    last = _conflict_fallback_last_run.get(user.id)
    if last and (now - last).total_seconds() < CONFLICT_FALLBACK_THROTTLE_SECONDS:
        return

    threshold = SEMANTIC_CONFLICT_THRESHOLD
    try:
        conflicts = find_conflicts(
            db=db,
            activity=user_action,
            file_conflict_window_hours=0,  # skip file for fallback
            semantic_similarity_threshold=threshold,
            semantic_window_days=7,
        )
    except Exception as e:
        logger.error("[ConflictFallback] error=%s", e, exc_info=True)
        return

    created = 0
    matches = len(conflicts)
    for conflict in conflicts[:3]:
        try:
            affected_user_id = conflict.get("affected_user_id")
            conflict_type = conflict.get("conflict_type")
            if not affected_user_id or conflict_type != "semantic":
                continue
            now_ts = now
            recent_cutoff = now_ts - timedelta(hours=1)
            existing = db.query(NotificationORM).filter(
                NotificationORM.user_id == affected_user_id,
                NotificationORM.source_type == "conflict_semantic",
                NotificationORM.created_at >= recent_cutoff,
                NotificationORM.data["related_user_id"].astext == user_action.user_id,
            ).first()
            if existing:
                continue

            similarity_pct = int(conflict.get("similarity", 0) * 100)
            title = f"Related Work: {user.name}"
            message = (
                f"{user.name} is working on something similar ({similarity_pct}% match). "
                f"Their activity: \"{(user_action.activity_summary or '')[:100]}...\""
            )
            notif = NotificationORM(
                id=str(uuid.uuid4()),
                user_id=affected_user_id,
                type="conflict",
                severity="normal",
                source_type="conflict_semantic",
                title=title,
                message=message,
                created_at=now_ts,
                is_read=False,
                data={
                    "conflict_type": "semantic",
                    "related_user_id": user_action.user_id,
                    "related_user_name": user.name,
                    "related_activity_id": user_action.id,
                    "similarity": conflict.get("similarity", 1.0),
                    "files": conflict.get("files", []),
                    "activity_summary": user_action.activity_summary,
                },
            )
            db.add(notif)
            created += 1
        except Exception as e:
            logger.error("[ConflictFallback] failed to create notif: %s", e, exc_info=True)
            continue

    if created:
        db.commit()
    _conflict_fallback_last_run[user.id] = now
    logger.info(
        "[ConflictFallback] enabled=1 created=%s matches=%s user_id=%s room_id=%s",
        created,
        matches,
        user_action.user_id,
        user_action.room_id,
    )

class InboxUpdateRequest(BaseModel):
    status: Literal["open", "done", "archived"]
    priority: Optional[str] = None

class InboxTaskOut(BaseModel):
    id: str
    content: str
    status: str
    priority: Optional[str]
    room_id: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class NotificationCreate(BaseModel):
    title: str
    message: Optional[str] = None
    room_id: Optional[str] = None
    source_message_id: Optional[str] = None
    priority: Optional[str] = None
    tags: List[str] = []
    type: Optional[str] = "task"
    task_id: Optional[str] = None

class WaitlistSubmissionPayload(BaseModel):
    name: Optional[str] = None
    email: str
    company: Optional[str] = None
    teamSize: Optional[str] = None
    role: Optional[str] = None
    problems: Optional[str] = None
    notes: Optional[str] = None
    source: Optional[str] = None
    metadata: Optional[dict] = None

# ============================================================


# Utilities


# ============================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user = db.get(UserORM, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    admin_emails = parse_admin_emails()
    maybe_persist_platform_admin(user, db, admin_emails)

    return user


def summarize_event_detail(raw_detail: str) -> str:
    """
    Condense event detail to keep the activity feed scannable.
    Uses OpenAI gpt-4o-mini; falls back to raw text on failure.
    """
    text = (raw_detail or "").strip()
    if not text:
        return ""

    prompt = f"Summarize this activity in under 10 words: {text}"
    client = openai_client
    if not client:
        return text

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=50,
        )
        summary = (resp.choices[0].message.content or "").strip()
        if summary:
            words = summary.split()
            if len(words) > 10:
                summary = " ".join(words[:10])
            return summary
    except Exception as e:
        logger.exception("Failed to summarize event detail: %s", e)

    # Fallback: return original text truncated to 10 words if no summary
    words = text.split()
    return " ".join(words[:10])


@event.listens_for(EventLogORM, "before_insert")
def _summarize_event_detail_before_insert(mapper, connection, target):
    """
    Ensure event log detail is summarized before persisting.
    """
    try:
        target.detail = summarize_event_detail(getattr(target, "detail", ""))
    except Exception as e:
        logger.exception("Failed to summarize event log detail before insert: %s", e)


def create_notification_safe(
    db: Session,
    *,
    user_id: str,
    title: str,
    message: str,
    notif_type: str = "task",
    task_id: Optional[str] = None,
) -> Optional[NotificationORM]:
    """
    Safely create a notification, skipping invalid task references and rolling back on errors.
    """
    try:
        task_ref = task_id
        if task_ref:
            exists = (
                db.query(TaskORM.id)
                .filter(TaskORM.id == task_ref)
                .first()
            )
            if not exists:
                logger.warning("Skipping notification: task %s not found", task_ref)
                task_ref = None

        notif = NotificationORM(
            id=str(uuid.uuid4()),
            user_id=user_id,
            type=notif_type or "task",
            title=title,
            message=message,
            task_id=task_ref,
            created_at=datetime.now(timezone.utc),
            is_read=False,
        )
        db.add(notif)
        db.flush()
        return notif
    except Exception as e:
        logger.exception("Failed to create notification: %s", e)
        db.rollback()
        return None

from textwrap import dedent

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
ALLOWED_INTEGRATION_PROVIDERS = {"google_gmail", "google_calendar"}
SELF_REMINDER_PATTERNS = [
    r"\bremind me to (.+)",
    r"\bremind myself to (.+)",
    r"\bdon't let me forget to (.+)",
    r"\bmake sure i (.+)",
]
TEAMMATE_REMINDER_PATTERNS = [
    r"\bremind\s+(?P<name>[A-Z][a-z]+)\s+to\s+(?P<body>.+)",
    r"\bnotify\s+(?P<name>[A-Z][a-z]+)\s+to\s+(?P<body>.+)",
    r"\btell\s+(?P<name>[A-Z][a-z]+)\s+to\s+(?P<body>.+)",
    r"\bping\s+(?P<name>[A-Z][a-z]+)\s+to\s+(?P<body>.+)",
]

def build_system_context(
    db: Session,
    room: RoomORM,
    chat_instance: ChatInstanceORM | None = None,
) -> str:
    """
    Super minimal context:
    - Only messages from THIS room / chat instance.
    - No org-wide summaries.
    - No teammate activity blobs.
    """

    query = db.query(MessageORM).filter(MessageORM.room_id == room.id)
    if chat_instance:
        query = query.filter(MessageORM.chat_instance_id == chat_instance.id)

    messages = (
        query.order_by(MessageORM.created_at.asc())
        .limit(MAX_CONTEXT_MESSAGES)
        .all()
    )

    # Format as simple chat transcript
    lines = []
    for m in messages:
        who = m.sender_name or m.sender_id or "Unknown"
        role = m.role or "user"
        content = (m.content or "").strip()
        # keep it short in case of huge messages
        if len(content) > 1200:
            content = content[:1200] + " ...[truncated]"
        lines.append(f"{who} ({role}): {content}")

    transcript = "\n".join(lines) if lines else "(no prior messages in this room yet)"

    chat_label = ""
    if chat_instance:
        chat_label = f"\n- chat_id: {chat_instance.id}\n- chat_name: {chat_instance.name}"

    ctx = dedent(
        f"""
        You are inside a shared project room.

        Room metadata:
        - room_id: {room.id}
        - room_name: {room.name or "(unnamed room)"}
        {chat_label}

        Below is the recent message history for THIS room/chat only:

        --- ROOM MESSAGES START ---
        {transcript}
        --- ROOM MESSAGES END ---
        """
    ).strip()

    return ctx

def build_team_activity_context(
    db: Session,
    room: RoomORM,
    current_user: UserORM,
    max_messages: int = 50,
) -> str:
    """
    Provide a light-weight view of recent teammate activity in this room.
    Uses the most recent message per teammate (excluding the current user)
    across all chats in the room.
    """
    recent_messages = (
        db.query(MessageORM)
        .join(ChatInstanceORM, ChatInstanceORM.id == MessageORM.chat_instance_id)
        .filter(
            ChatInstanceORM.room_id == room.id,
            MessageORM.role == "user",
            MessageORM.sender_id.like("user:%"),
        )
        .order_by(MessageORM.created_at.desc())
        .limit(max_messages)
        .all()
    )

    latest_by_user: dict[str, MessageORM] = {}
    for msg in recent_messages:
        sender = msg.sender_id or ""
        if not sender.startswith("user:"):
            continue
        uid = sender.replace("user:", "", 1)
        if uid == current_user.id:
            continue
        if uid not in latest_by_user:
            latest_by_user[uid] = msg

    if not latest_by_user:
        return ""

    user_map = {
        u.id: u
        for u in db.query(UserORM).filter(UserORM.id.in_(latest_by_user.keys())).all()
    }

    parts = ["Recent team activity (latest per teammate):"]
    for uid, msg in sorted(
        latest_by_user.items(),
        key=lambda item: item[1].created_at or datetime.min,
        reverse=True,
    ):
        user_obj = user_map.get(uid)
        display_name = user_obj.name if user_obj and getattr(user_obj, "name", None) else uid
        content = msg.content or ""
        if len(content) > 120:
            content = content[:117] + "..."
        ts = msg.created_at.isoformat() if msg.created_at else ""
        parts.append(f"- {display_name}: {content} ({ts})")

    return "\n".join(parts)

def upsert_external_account(
    db: Session,
    user_id: str,
    provider: str,
    access_token: str,
    refresh_token: Optional[str],
    expires_at: Optional[datetime],
    scopes: List[str],
) -> ExternalAccountORM:
    acct = (
        db.query(ExternalAccountORM)
        .filter(
            ExternalAccountORM.user_id == user_id,
            ExternalAccountORM.provider == provider,
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if not acct:
        acct = ExternalAccountORM(
            id=str(uuid.uuid4()),
            user_id=user_id,
            provider=provider,
            created_at=now,
        )
        db.add(acct)

    acct.access_token = access_token
    acct.refresh_token = refresh_token
    acct.expires_at = expires_at
    acct.scopes = scopes or []
    acct.updated_at = now
    db.commit()
    db.refresh(acct)
    return acct

def get_valid_access_token(
    db: Session, user_id: str, provider: str
) -> Optional[str]:
    acct = (
        db.query(ExternalAccountORM)
        .filter(
            ExternalAccountORM.user_id == user_id,
            ExternalAccountORM.provider == provider,
        )
        .first()
    )
    if not acct:
        return None
    now = datetime.now(timezone.utc)
    if acct.expires_at and acct.expires_at > now:
        return acct.access_token

    if not acct.refresh_token:
        return None

    data = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "grant_type": "refresh_token",
        "refresh_token": acct.refresh_token,
    }
    resp = httpx.post(GOOGLE_TOKEN_URL, data=data, timeout=10)
    if resp.status_code != 200:
        # refresh failed; invalidate tokens
        acct.access_token = None
        acct.expires_at = None
        db.add(acct)
        db.commit()
        return None
    payload = resp.json()
    expires_in = payload.get("expires_in", 0)
    acct.access_token = payload.get("access_token")
    acct.expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    acct.updated_at = datetime.now(timezone.utc)
    db.add(acct)
    db.commit()
    db.refresh(acct)
    return acct.access_token

class MissingIntegrationsError(Exception):
    def __init__(self, missing: List[str]):
        super().__init__("missing_integrations")
        self.missing = missing

def _check_brief_integrations(db: Session, user_id: str):
    missing = []
    gmail = (
        db.query(ExternalAccountORM)
        .filter(
            ExternalAccountORM.user_id == user_id,
            ExternalAccountORM.provider == "google_gmail",
            ExternalAccountORM.access_token.isnot(None),
        )
        .first()
    )
    cal = (
        db.query(ExternalAccountORM)
        .filter(
            ExternalAccountORM.user_id == user_id,
            ExternalAccountORM.provider == "google_calendar",
            ExternalAccountORM.access_token.isnot(None),
        )
        .first()
    )
    if not gmail:
        missing.append("gmail")
    if not cal:
        missing.append("calendar")
    if missing:
        raise MissingIntegrationsError(missing)

def generate_daily_brief(user: UserORM, db: Session) -> dict:
    logger.info(f"=" * 80)
    logger.info(f"DAILY BRIEF GENERATION START - User: {user.email} (ID: {user.id})")
    logger.info(f"=" * 80)
    
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    
    # Import your services
    from app.services.gmail import fetch_unread_emails
    from app.services.calendar import fetch_upcoming_events
    
    # Fetch REAL data
    try:
        logger.info("📧 Fetching Gmail data...")
        emails = fetch_unread_emails(user, db)
        logger.info(f"✅ Fetched {len(emails)} emails")
        if emails:
            logger.info(f"Sample email: {emails[0].get('subject', 'No subject')[:50]}")
    except Exception as e:
        logger.error(f"❌ Gmail fetch failed: {e}")
        emails = []
    
    try:
        logger.info("📅 Fetching Calendar data...")
        calendar_events = fetch_upcoming_events(user, db)
        logger.info(f"✅ Fetched {len(calendar_events)} calendar events")
        if calendar_events:
            logger.info(f"Sample event: {calendar_events[0].get('summary', 'No title')[:50]}")
    except Exception as e:
        logger.error(f"❌ Calendar fetch failed: {e}")
        calendar_events = []
    
    # Check if we have data to process
    if not emails and not calendar_events:
        logger.warning("⚠️ No emails or calendar events - returning empty brief")
        return {
            "date": today,
            "generated_at": now.isoformat(),
            "personal": {
                "priorities": [],
                "unread_emails": [],
                "upcoming_meetings": [],
                "calendar": [],
                "mentions": [],
                "actions": [],
            },
            "org": {"activity": [], "fires": [], "statuses": [], "bottlenecks": [], "risks": []},
            "outbound": {"at_risk_clients": [], "opportunities": [], "external_triggers": [], "sentiment_alerts": []},
        }
    
    # AI Processing
    logger.info("🤖 Starting AI processing...")
    personal = _generate_personal_brief_with_ai(user, emails, calendar_events, db)
    logger.info(f"✅ Personal brief generated: {len(personal.get('priorities', []))} priorities, {len(personal.get('unread_emails', []))} emails")
    
    logger.info("👥 Starting org brief generation...")
    org = _generate_org_brief_with_ai(user, db)
    logger.info(f"✅ Org brief generated: {len(org.get('activity', []))} activities")
    
    outbound = {
        "at_risk_clients": [],
        "opportunities": [],
        "external_triggers": [],
        "sentiment_alerts": [],
    }
    
    result = {
        "date": today,
        "generated_at": now.isoformat(),
        "personal": personal,
        "org": org,
        "outbound": outbound,
    }
    
    logger.info(f"=" * 80)
    logger.info(f"DAILY BRIEF GENERATION COMPLETE")
    logger.info(f"=" * 80)
    
    return result


def fetch_emails_since(user: UserORM, db: Session, since: datetime) -> list:
    """
    Fetch emails from Gmail API only since a specific datetime.
    Similar to fetch_unread_emails() but with time filter.
    """
    from app.services.gmail import fetch_unread_emails_raw, _get_valid_token

    access_token = _get_valid_token(user, db)
    if not access_token:
        logger.warning("[Brief] No valid Gmail access token for user %s", user.id)
        return []

    try: 
        import time
        ts = int(time.mktime(since.timetuple()))
        query = f"after:{ts}"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"q": query, "maxResults": 50}
        base = "https://www.googleapis.com/gmail/v1/users/me/messages"

        import httpx # asas

        resp = httpx.get(base, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            logger.warning("[Brief] Gmail API returned %s", resp.status_code)
            return []

        messages = resp.json().get("messages", []) or []
        results = []
        for msg in messages:
            mid = msg.get("id")
            if not mid:
                continue
            detail = httpx.get(f"{base}/{mid}", headers=headers, timeout=10)
            if detail.status_code != 200:
                continue
            body = detail.json()
            snippet = body.get("snippet") or ""
            payload = body.get("payload") or {}
            headers_list = payload.get("headers") or []
            header_map = {h.get("name"): h.get("value") for h in headers_list if h.get("name")}
            email_link = f"https://mail.google.com/mail/u/0/#all/{mid}"
            results.append({
                "id": mid,
                "thread_id": body.get("threadId"),
                "from": header_map.get("From", "Unknown"),
                "subject": header_map.get("Subject", "No subject"),
                "snippet": snippet,
                "received_at": body.get("internalDate"),
                "date": header_map.get("Date", ""),
                "link": email_link,
            })
        return results
    except Exception as e:
        logger.exception("[Brief] Error fetching emails since %s: %s", since, e)
        return []


def fetch_events_since(user: UserORM, db: Session, since: datetime) -> list:
    """
    Fetch calendar events only since a specific datetime.
    Similar to fetch_upcoming_events() but with time filter.
    """
    from app.services.calendar import _get_valid_token
    access_token = _get_valid_token(user, db)
    if not access_token:
        logger.warning("[Brief] No valid Calendar access token for user %s", user.id)
        return []

    headers = {"Authorization": f"Bearer {access_token}"}
    now = since
    end = now + timedelta(days=7)

    params = {
        "timeMin": now.isoformat(),
        "timeMax": end.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 50,
    }

    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

    try:
        import httpx
        resp = httpx.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            logger.warning("[Brief] Calendar API returned %s", resp.status_code)
            return []

        data = resp.json()
        events = data.get("items", []) or []
        normalized = []

        for ev in events:
            start_at = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
            end_at = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date")
            link = ev.get("htmlLink") or f"https://calendar.google.com/calendar/event?eid={ev.get('id')}"
            logger.info(f"[Calendar Link] ID: {ev.get('id')} htmlLink: {ev.get('htmlLink')} Link: {link}")
            normalized.append({
                "id": ev.get("id"),
                "summary": ev.get("summary", "No title"),
                "title": ev.get("summary", "No title"),
                "start": start_at,
                "start_time": start_at,
                "end": end_at,
                "end_time": end_at,
                "location": ev.get("location", ""),
                "is_all_day": bool(ev.get("start", {}).get("date")),
                "description": (ev.get("description") or "")[:200],
                "link": link,
            })
        return normalized
    except Exception as e:
        logger.exception("[Brief] Error fetching events since %s: %s", since, e)
        return []
 # NEWEWEW

def merge_and_dedupe(existing: list, new: list) -> list:
    """
    Merge new items into existing, removing duplicates by ID.
    Keep most recent version if duplicate found.
    """
    by_id = {}
    for item in existing + new:
        item_id = item.get("id")
        if not item_id:
            continue
        prev = by_id.get(item_id)
        if not prev:
            by_id[item_id] = item
        else:
            # Prefer the one with a newer date if available
            prev_date = prev.get("date") or prev.get("start") or ""
            new_date = item.get("date") or item.get("start") or ""
            if new_date > prev_date:
                by_id[item_id] = item
    merged = list(by_id.values())
    merged.sort(key=lambda x: (x.get("date") or x.get("start") or ""), reverse=True)
    return merged


def generate_item_signature(item: dict) -> str:
    """
    Generate a stable hash from item title and source.
    Used for tracking completed items.
    """
    import hashlib
    text_val = f"{item.get('title', '')}:{item.get('source_id', '')}"
    return hashlib.md5(text_val.encode()).hexdigest()


def generate_timeline_signature(timeframe: str, priority: str, title: str) -> str:
    """
    Generate a stable hash for a timeline item using timeframe/priority/title.
    """
    import hashlib
    canonical_string = f"{timeframe}|{priority}|{(title or '').strip().lower()}"
    return hashlib.md5(canonical_string.encode()).hexdigest()


def parse_mentions(text: str) -> List[str]:
    """
    Extract @mentions from text, returning the token after '@'.
    """
    if not text:
        return []
    mentions = re.findall(r'@(\w+(?:\.\w+)*(?:@\w+(?:\.\w+)*)?)', text)
    return mentions


def find_mentioned_users(text: str, org_id: Optional[str], db: Session) -> List[UserORM]:
    """
    Resolve mentioned users by matching email or name within the same org.
    """
    if not text or not org_id:
        return []
    tokens = parse_mentions(text)
    if not tokens:
        return []
    found = []
    for tok in tokens:
        user = (
            db.query(UserORM)
            .filter(
                UserORM.org_id == org_id,
                or_(
                    func.lower(UserORM.email).like(f"%{tok.lower()}%"),
                    func.lower(UserORM.name).like(f"%{tok.lower()}%"),
                ),
            )
            .first()
        )
        if user:
            found.append(user)
    return found


def handle_mention_notifications_and_tasks(
    task_data: dict,
    current_user: UserORM,
    signature: str,
    action: str,
    db: Session,
):
    """
    Handle @mentions: send notifications and (for new tasks) add to mentioned user's timeline.
    action: "task_created" or "task_completed"
    """
    if not task_data:
        return
    item_title = task_data.get("title", "")
    item_description = task_data.get("description", "") or task_data.get("detail", "")
    task_text = f"{item_title} {item_description}"
    if "@" not in task_text:
        return

    mentioned_users = find_mentioned_users(task_text, current_user.org_id, db)
    for m_user in mentioned_users:
        if m_user.id == current_user.id:
            continue

        notif = NotificationORM(
            id=str(uuid.uuid4()),
            user_id=m_user.id,
            type="agent_message",
            title=f"🤖 {current_user.name}'s agent",
            message=f"{'New task' if action == 'task_created' else 'Task completed'}: {item_title[:80]}",
            data={
                "from_user": current_user.name,
                "from_user_id": current_user.id,
                "task_title": item_title,
                "task_signature": signature,
                "notification_type": "agent_coordination",
                "action": action,
            },
            task_id=None,
            created_at=datetime.now(timezone.utc),
            is_read=False,
        )
        db.add(notif)

        if action == "task_created":
            mentioned_canon = get_or_create_canonical_plan(m_user.id, db)
            timeline = mentioned_canon.approved_timeline or {}
            tf_key = "today"
            timeline.setdefault(tf_key, {})
            timeline[tf_key].setdefault("high", [])
            import hashlib

            task_signature = hashlib.md5(f"{item_title}:assigned_by_{current_user.id}".encode()).hexdigest()
            assigned_task = {
                "title": item_title,
                "description": f"Assigned by {current_user.name}. {item_description}",
                "signature": task_signature,
                "source": "team_assignment",
                "source_id": f"assignment_{current_user.id}_{signature}",
                "assigned_by": current_user.name,
                "assigned_by_id": current_user.id,
                "priority": "high",
                "timeframe": tf_key,
                "section": "high",
            }
            existing_sigs = [t.get("signature") for t in timeline[tf_key]["high"]]
            if task_signature not in existing_sigs:
                timeline[tf_key]["high"].append(assigned_task)
                mentioned_canon.approved_timeline = timeline
                flag_modified(mentioned_canon, "approved_timeline")
                db.add(mentioned_canon)
                logger.info(f"[TASK ASSIGNMENT] {current_user.name} → {m_user.name}: {item_title}")

    if mentioned_users:
        db.commit()


def filter_completed_items(items: list, user_id: str, db: Session) -> list:
    """
    Remove items that user has marked as completed.
    """
    from models import CompletedBriefItem

    if not items:
        return []

    completed = db.query(CompletedBriefItem).filter(
        CompletedBriefItem.user_id == user_id
    ).all()

    completed_signatures = {c.item_signature for c in completed}
    logger.info(f"[Filter] Found {len(completed_signatures)} completed signatures in DB")
    logger.info(f"[Filter] First 5 sigs: {list(completed_signatures)[:5]}")
    logger.info(f"[Filter] Checking {len(items)} items")

    filtered = []
    removed = []
    for item in items:
        sig = generate_item_signature(item)
        if sig not in completed_signatures:
            filtered.append(item)
        else:
            removed.append(sig)

    if removed:
        logger.info(f"[Filter] Removed {len(removed)} items")
    else:
        logger.debug("[Filter] No completed/deleted items removed")

    return filtered


def filter_timeline_by_signatures(timeline_data, completed_signatures):
    """
    Remove items whose signatures are in completed_signatures set without mutating originals.
    """
    if not completed_signatures:
        return timeline_data

    if isinstance(timeline_data, dict):
        filtered = {}
        for timeframe, priorities in timeline_data.items():
            if not isinstance(priorities, dict):
                filtered[timeframe] = priorities
                continue
            filtered[timeframe] = {}
            for priority, items in priorities.items():
                if isinstance(items, list):
                    filtered[timeframe][priority] = [
                        item for item in items
                        if item.get("signature") not in completed_signatures
                    ]
                else:
                    filtered[timeframe][priority] = items
        return filtered
    if isinstance(timeline_data, list):
        return [
            item for item in timeline_data
            if item.get("signature") not in completed_signatures
        ]
    return timeline_data


def count_timeline_items(timeline: dict) -> int:
    """
    Count total items across timeframe/priority buckets.
    """
    if not isinstance(timeline, dict):
        return 0

    total = 0
    for sections in timeline.values():
        if not isinstance(sections, dict):
            continue
        for items in sections.values():
            if isinstance(items, list):
                total += len(items)
    return total


def _filter_canon_with_completed(canon: UserCanonicalPlan, completed_sigs: set) -> dict:
    """
    Filter canonical timeline/recommendations by completed signatures without mutation.
    """
    timeline = canon.approved_timeline or {}
    filtered_timeline = {}
    for timeframe in ["1d", "7d", "28d"]:
        if timeframe not in timeline:
            continue
        filtered_timeline[timeframe] = {}
        for priority in ["critical", "high", "medium", "low", "normal", "high_priority"]:
            items = timeline.get(timeframe, {}).get(priority, [])
            if not isinstance(items, list):
                continue
            filtered_timeline[timeframe][priority] = [
                item for item in items if item.get("signature") not in completed_sigs
            ]

    filtered_recs = [
        rec for rec in (canon.pending_recommendations or [])
        if rec.get("signature") not in completed_sigs
    ]

    return {
        "timeline": filtered_timeline,
        "priorities": canon.active_priorities or [],
        "recommendations": filtered_recs,
        "last_ai_sync": canon.last_ai_sync.isoformat() if canon.last_ai_sync else None,
        "last_user_modification": canon.last_user_modification.isoformat() if canon.last_user_modification else None,
    }


def prune_plan_item(plan: UserCanonicalPlan, signature: str):
    """Remove items matching signature from canon timeline and pending recs."""
    timeline = plan.approved_timeline or {}
    changed = False
    for tf, sections in list(timeline.items()):
        if not isinstance(sections, dict):
            continue
        for sec, items in list(sections.items()):
            if not isinstance(items, list):
                continue
            new_items = []
            for it in items:
                sig = it.get("signature") or generate_item_signature(it)
                if sig == signature:
                    changed = True
                    continue
                new_items.append(it)
            sections[sec] = new_items
        timeline[tf] = sections
    if changed:
        plan.approved_timeline = timeline

    recs = plan.pending_recommendations or []
    new_recs = []
    for rec in recs:
        if rec.get("signature") == signature:
            changed = True
            continue
        new_recs.append(rec)
    if changed:
        plan.pending_recommendations = new_recs


def hard_remove_signature_from_canon(plan: UserCanonicalPlan, signatures):
    """
    Force-remove items by any matching signature from canon timeline, priorities, and pending recs, marking JSON fields modified.
    """
    from sqlalchemy.orm.attributes import flag_modified

    sig_set = {s for s in ([signatures] if isinstance(signatures, str) else signatures) if s}
    if not sig_set:
        return False

    timeline = plan.approved_timeline or {}
    removed = False
    priorities_removed = False
    for tf, sections in list(timeline.items()):
        if not isinstance(sections, dict):
            continue
        for pr, items in list(sections.items()):
            if not isinstance(items, list):
                continue
            new_items = []
            for it in items:
                sig = it.get("signature") or generate_item_signature(it)
                if sig in sig_set:
                    removed = True
                    continue
                new_items.append(it)
            sections[pr] = new_items
        timeline[tf] = sections
    if removed:
        plan.approved_timeline = timeline
        flag_modified(plan, "approved_timeline")

    # Also remove from priorities list if present
    priorities = plan.active_priorities or []
    new_priorities = []
    for it in priorities:
        sig = it.get("signature") or generate_item_signature(it)
        if sig in sig_set:
            priorities_removed = True
            continue
        new_priorities.append(it)
    if priorities_removed:
        plan.active_priorities = new_priorities
        flag_modified(plan, "active_priorities")

    # Also remove from pending recommendations
    recs = plan.pending_recommendations or []
    new_recs = [rec for rec in recs if rec.get("signature") not in sig_set]
    if len(new_recs) != len(recs):
        plan.pending_recommendations = new_recs
        flag_modified(plan, "pending_recommendations")

    return removed or priorities_removed or (len(new_recs) != len(recs))



def get_or_create_canonical_plan(user_id: str, db: Session):
    """
    Get or create the user's canonical plan (approved items vs recommendations).
    """
    default_timeline = {
        "1d": {"critical": [], "high": [], "normal": []},
        "7d": {"milestones": [], "goals": []},
        "28d": {"objectives": [], "projects": []},
    }
    disable_autofill = os.getenv("DISABLE_CANON_AUTOFILL", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    plan = (
        db.query(UserCanonicalPlan)
        .filter(UserCanonicalPlan.user_id == user_id)
        .first()
    )

    if not plan:
        approved_timeline = default_timeline
        active_priorities = []
        now_ts = datetime.now(timezone.utc)

        if not disable_autofill:
            try:
                user = db.query(UserORM).filter(UserORM.id == user_id).first()
                from app.services.gmail import fetch_unread_emails
                from app.services.calendar import fetch_upcoming_events

                if user:
                    emails = fetch_unread_emails(user, db)
                    events = fetch_upcoming_events(user, db)
                    ai_result = _generate_personal_brief_with_ai(user, emails, events, db)
                    approved_timeline = ai_result.get("timeline", default_timeline)
                    active_priorities = ai_result.get("priorities", [])
            except Exception as e:
                logger.warning(f"[Canon] Failed to auto-populate canonical plan: {e}")
                db.rollback()
                approved_timeline = default_timeline
                active_priorities = []

        plan = UserCanonicalPlan(
            id=str(uuid.uuid4()),
            user_id=user_id,
            approved_timeline=approved_timeline,
            active_priorities=active_priorities,
            pending_recommendations=[],
            dismissed_items=[],
            last_ai_sync=now_ts,
            last_user_modification=now_ts,
        )
        db.add(plan)
        try:
            db.commit()
            db.refresh(plan)
            logger.info(f"[Canon] Created canonical plan for user {user_id}")
        except Exception as e:
            logger.warning(f"[Canon] Failed to persist canonical plan: {e}")
            db.rollback()

    return plan


def should_regenerate_recommendations(canonical_plan: UserCanonicalPlan) -> bool:
    """
    Determine if we should regenerate recommendations.
    """
    if not canonical_plan.last_ai_sync:
        return True
    age = datetime.now(timezone.utc) - canonical_plan.last_ai_sync
    return age.total_seconds() > 3600


def generate_recommendations(user, emails, events, canonical_plan, db, completed_signatures=None, is_manual_refresh=False):
    """
    Generate recommendations for NEW items only.
    
    is_manual_refresh: If True, can suggest reprioritization of existing items.
                      If False (background), only suggest NEW items.
    """
    approved_timeline = canonical_plan.approved_timeline or {
        "1d": {"critical": [], "high": [], "normal": []},
        "7d": {"milestones": [], "goals": []},
        "28d": {"objectives": [], "projects": []}
    }
    approved_priorities = canonical_plan.active_priorities or []
    dismissed_signatures = {
        generate_item_signature(item) 
        for item in (canonical_plan.dismissed_items or [])
    }
    if completed_signatures is None:
        completed_signatures = {
            c.item_signature for c in db.query(CompletedBriefItem).filter(CompletedBriefItem.user_id == user.id).all()
        }
    else:
        completed_signatures = set(completed_signatures)
    if completed_signatures:
        logger.info(f"[Recs] Completed/deleted signatures to skip: {list(completed_signatures)[:5]}")
    if dismissed_signatures:
        logger.info(f"[Recs] Dismissed signatures to skip: {list(dismissed_signatures)[:5]}")
    
    # Store existing recommendations to avoid duplicates
    existing_rec_signatures = {
        rec.get('signature') 
        for rec in (canonical_plan.pending_recommendations or [])
        if rec.get('signature')
    }
    
    # Generate full brief with AI (as before)
    ai_result = _generate_personal_brief_with_ai(user, emails, events, db)
    
    # Extract NEW items that aren't in approved plan or dismissed
    recommendations = []
    
    # Check timeline items
    for timeframe in ['1d', '7d', '28d']:
        ai_timeframe = ai_result.get('timeline', {}).get(timeframe, {})
        approved_timeframe = approved_timeline.get(timeframe, {})
        
        for section_key, section_items in ai_timeframe.items():
            if not isinstance(section_items, list):
                continue
            
            approved_section = approved_timeframe.get(section_key, [])
            
            for item in section_items:
                sig = item.get("signature") or generate_item_signature(item)
                
                # Skip if already in approved plan
                is_approved = any(
                    (approved.get("signature") or generate_item_signature(approved)) == sig
                    for approved in approved_section
                )
                
                # Skip if dismissed
                is_dismissed = sig in dismissed_signatures
                # Skip if completed/deleted history
                if sig in completed_signatures:
                    continue
                
                # Skip if already recommended
                already_recommended = sig in existing_rec_signatures
                
                if not is_approved and not is_dismissed and not already_recommended:
                    recommendations.append({
                        "item": item,
                        "reason": f"New {section_key} item detected",
                        "timeframe": timeframe,
                        "section": section_key,
                        "type": "timeline_addition",
                        "signature": sig
                    })

    logger.info(f"[Recs] Generated {len(recommendations)} new rec candidates (after skips).")

    return recommendations


def build_assistant_context(user_id: str, chat_id: str, db: Session) -> str:
    """
    Build context string for the personal assistant system prompt.
    """
    plan = get_or_create_canonical_plan(user_id, db)

    # Canonical plan pieces
    timeline = plan.approved_timeline or {}
    priorities = plan.active_priorities or []
    recs = plan.pending_recommendations or []

    # Log timeline data for debugging
    monthly_urgent = (timeline.get("28d") or {}).get("urgent") or []
    monthly_normal = (timeline.get("28d") or {}).get("normal") or []
    logger.warning(f"[CHAT CONTEXT] Building context for user {user_id[:8]}...")
    logger.warning(f"[CHAT CONTEXT] Monthly urgent: {len(monthly_urgent)} items")
    logger.warning(f"[CHAT CONTEXT] Monthly normal: {len(monthly_normal)} items")
    for item in monthly_normal:
        logger.warning(f"[CHAT CONTEXT]   - {item.get('title', 'NO TITLE')}")

    # Condense recommendations (top 3)
    top_recs = []
    for rec in recs[:3]:
        item = rec.get("item", {})
        title = item.get("title") or item.get("subject") or "Untitled"
        timeframe = rec.get("timeframe", "")
        section = rec.get("section", "")
        top_recs.append(f"- {title} ({timeframe}/{section})")

    # Recent context from cache
    context_store = db.query(UserContextStore).filter(UserContextStore.user_id == user_id).first()
    emails = (context_store.emails_recent if context_store else []) or []
    events = (context_store.calendar_recent if context_store else []) or []

    def fmt_email(e):
        return f"From: {e.get('from', 'Unknown')} | Subject: {e.get('subject', 'No subject')} | Snippet: {(e.get('snippet') or '')[:120]} | Link: {e.get('link', '')}"

    def fmt_event(ev):
        start = ev.get("start") or ev.get("start_time") or ""
        return f"Title: {ev.get('summary', ev.get('title', 'Untitled'))} | When: {start} | Link: {ev.get('link', '')}"

    email_lines = [fmt_email(e) for e in emails[:5]]
    event_lines = [fmt_event(ev) for ev in events[:5]]

    def fmt_timeline_section(tf: str, key: str):
        section = (timeline.get(tf) or {}).get(key) or []
        lines = []
        for item in section[:5]:
            title = item.get("title") or item.get("subject") or "Untitled"
            deadline = item.get("deadline") or item.get("due") or ""
            if deadline:
                lines.append(f"- {title} (deadline: {deadline})")
            else:
                lines.append(f"- {title}")
        return lines

    system_parts = [
        "You are the ParallelOS personal assistant. You help the user reason about their timeline, priorities, and communication.",
        "\n=== USER'S CURRENT PLAN (CANONICAL) ===",
        "Today (1D) - Urgent:",
        *fmt_timeline_section("1d", "urgent"),
        "Today (1D) - Normal:",
        *fmt_timeline_section("1d", "normal"),
        "\nThis Week (7D) - Urgent:",
        *fmt_timeline_section("7d", "urgent"),
        "This Week (7D) - Normal:",
        *fmt_timeline_section("7d", "normal"),
        "\nThis Month (28D) - Urgent:",
        *fmt_timeline_section("28d", "urgent"),
        "This Month (28D) - Normal:",
        *fmt_timeline_section("28d", "normal"),
        "\nActive priorities:",
        *(f"- {p.get('title', 'Untitled')}" for p in priorities[:10]),
        f"\nPending AI recommendations ({len(recs)} total, showing up to 3):",
        *top_recs,
        "\n=== RECENT EMAILS ===",
        *(f"{i+1}) {line}" for i, line in enumerate(email_lines)),
        "\n=== UPCOMING EVENTS ===",
        *(f"{i+1}) {line}" for i, line in enumerate(event_lines)),
        "\nRules:",
        "- Ground responses in the provided context.",
        "- When suggesting schedule changes, refer to canonical plan items by name.",
        "- Do not invent meetings, emails, or tasks not present here.",
    ]

    # Remove empty lines
    system_parts = [line for line in system_parts if line is not None]
    return "\n".join(system_parts)


def _format_canon_summary(plan: UserCanonicalPlan) -> tuple[str, int, list[str]]:
    """Produce a short canon/timeline summary without timestamps."""
    timeline = plan.approved_timeline or {}
    priorities = plan.active_priorities or []
    recs = plan.pending_recommendations or []

    lines = ["Canon / Current Priorities:"]
    total_items = 0
    items_out: list[str] = []

    def add_section(label: str, items: list[dict]):
        nonlocal total_items
        if not items:
            return
        for item in items[:5]:
            title = item.get("title") or item.get("subject") or "Untitled"
            lines.append(f"- {label}: {title}")
            items_out.append(f"{label}: {title}")
            total_items += 1

    for tf_key in ["1d", "7d", "28d"]:
        sections = (timeline.get(tf_key) or {}).items()
        for name, items in sections:
            add_section(f"{tf_key}/{name}", items if isinstance(items, list) else [])

    if priorities:
        for p in priorities[:5]:
            title = p.get("title") or "Untitled priority"
            lines.append(f"- Priority: {title}")
            items_out.append(f"Priority: {title}")
            total_items += 1

    if recs:
        for rec in recs[:3]:
            item = rec.get("item", {})
            title = item.get("title") or item.get("subject") or "Recommendation"
            lines.append(f"- Recommendation: {title}")
            items_out.append(f"Recommendation: {title}")
            total_items += 1

    if total_items == 0:
        lines.append("- No canon items available yet.")

    return "\n".join(lines), total_items, items_out


def _infer_integration_source(tool: str, source: str, action_type: str, action_data: dict) -> str:
    tool = (tool or "").lower()
    source = (source or "").lower()
    action_type = (action_type or "").lower()
    if tool:
        return tool
    if source:
        return source
    # Heuristics
    if "email" in action_type or any(k in (action_data or {}) for k in ["subject", "from", "snippet"]):
        return "gmail"
    if "event" in action_type or any(k in (action_data or {}) for k in ["start", "end", "location"]):
        return "calendar"
    if any(k in (action_data or {}) for k in ["files", "file_path", "diff", "repo"]):
        return "vscode"
    if "chat" in action_type:
        return "chat"
    return "unknown"


def _build_integration_summaries(db: Session, user: UserORM, days: int = 7, max_items: int = 10) -> tuple[str, int, list[str], dict]:
    """Summaries from user_actions for integrations (gmail/calendar/vscode); no timestamps."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    allowed_tools = {"gmail", "calendar", "vscode"}
    fallback_enabled = INTEGRATION_FALLBACK_TAGGING_BOOL
    actions = (
        db.query(UserAction)
        .filter(
            UserAction.user_id == user.id,
            UserAction.timestamp >= cutoff,
            UserAction.activity_summary.isnot(None),
        )
        .order_by(UserAction.timestamp.desc())
        .all()
    )

    summaries = []
    counts_by_source: dict[str, int] = {}
    last_summary = None
    seen_skip_log = False
    max_per_source = 4
    for action in actions:
        tool = (action.tool or "").lower() if getattr(action, "tool", None) else ""
        source = ""
        if action.action_data and isinstance(action.action_data, dict):
            source = (action.action_data.get("source") or "").lower()

        if not tool and not source:
            if not fallback_enabled:
                if not seen_skip_log:
                    logger.info("[UnifiedContext] skipped integration item (no tool/source) user_id=%s action_id=%s", user.id, action.id)
                    seen_skip_log = True
                continue

        inferred = _infer_integration_source(tool, source, getattr(action, "action_type", ""), action.action_data if isinstance(action.action_data, dict) else {})
        if inferred not in allowed_tools and inferred != "unknown":
            # allow chat/web/etc. but cap by max_per_source
            pass
        if inferred not in allowed_tools and not fallback_enabled:
            continue
        if inferred not in counts_by_source:
            counts_by_source[inferred] = 0
        if counts_by_source[inferred] >= max_per_source:
            continue

        summary_text = (action.activity_summary or "").strip()
        if not summary_text:
            continue
        if summary_text == last_summary:
            continue
        last_summary = summary_text
        label = inferred or tool or source or "integration"
        summaries.append(f"- [{label}] {summary_text}")
        counts_by_source[label] = counts_by_source.get(label, 0) + 1
        if len(summaries) >= max_items:
            break

    if not summaries:
        summaries.append("- No recent integration updates.")

    return "\n".join(["Integration updates:"] + summaries), len(summaries), summaries, counts_by_source


def build_unified_assistant_context(
    db: Session,
    user: UserORM,
    room: RoomORM,
    chat_instance: ChatInstanceORM,
    user_query: Optional[str] = None,
    *,
    return_preview: bool = False,
    fast_path: bool = False,
    request_id: Optional[str] = None,
) -> tuple[str, dict] | str:
    """
    Unified context for all chats:
    - Canon/timeline
    - Integration summaries (gmail/calendar/vscode via user_actions)
    - Teammate summaries (shared rooms)
    - RAG (current room)
    - Chat transcript (current chat)
    """
    # Canon
    plan = get_or_create_canonical_plan(user.id, db)
    canon_block, canon_count, canon_items = _format_canon_summary(plan)

    # Integrations
    integ_block, integ_count, integ_items, integ_counts_by_source = _build_integration_summaries(db, user, max_items=1 if fast_path else 10)

    # Teammates
    teammate_block, teammate_ids = build_teammate_activity_summaries(db, user) if not fast_path else build_teammate_activity_summaries(db, user, max_per_user=1)
    teammate_count = len(teammate_ids)

    # RAG
    rag_block = ""
    rag_items = 0
    rag_preview_items: list[str] = []
    rag_scope = UNIFIED_RAG_SCOPE if not fast_path else "room"
    viewer_room_ids = _get_user_room_ids(db, user.id)
    room_ids_for_rag = [room.id] if rag_scope != "all_rooms" else viewer_room_ids
    rag_section_label = "Relevant past context (this room)" if rag_scope != "all_rooms" else "Relevant past context (across your rooms)"
    if user_query:
        try:
            relevant_context = [] if fast_path else (get_relevant_context(
                db=db,
                query=user_query,
                room_ids=room_ids_for_rag,
                viewer_room_ids=viewer_room_ids,
                limit=MAX_RAG_ITEMS,
            ) or [])
            deduped = []
            total_chars = 0
            seen_ids = set()
            for ctx in relevant_context:
                doc_id = ctx.get("id") or ctx.get("doc_id") or ctx.get("source_id")
                text = (ctx.get("text") or ctx.get("content") or "").strip()
                if not text:
                    continue
                if doc_id and doc_id in seen_ids:
                    continue
                excerpt = text[:MAX_RAG_ITEM_CHARS]
                if total_chars + len(excerpt) > MAX_RAG_TOTAL_CHARS:
                    break
                deduped.append({**ctx, "text": excerpt})
                total_chars += len(excerpt)
                if doc_id:
                    seen_ids.add(doc_id)
            rag_items = len(deduped)
            if deduped:
                rag_block = rag_section_label + "\n" + build_rag_context(deduped, user.name)
                for ctx in deduped[:MAX_RAG_ITEMS]:
                    rag_preview_items.append((ctx.get("text") or "")[:MAX_RAG_ITEM_CHARS])
        except Exception as e:
            logger.error("RAG retrieval failed: %s request_id=%s", e, request_id)

    # Transcript
    transcript_block = build_system_context(db, room, chat_instance)
    transcript_msgs = transcript_block.count("):") if transcript_block else 0

    # Existing headers/persona
    system_header = """
SYSTEM_VERSION_TAG: PARALLEL_V2_WITH_RAG

You are ONLY allowed to use information that appears in the sections below:
- Canon / current priorities
- Integration updates
- Teammate summaries (shared rooms only)
- Relevant past context (RAG)
- Current chat transcript

You DO NOT have access to hidden logs or other rooms. If asked about a teammate and you lack info here, say you do not know.
""".strip()

    rep_block = f"""
You are the dedicated AI representative for this human.

- name: {user.name or "Unknown"}
- id: {user.id}
- role: {user.role or "(none specified)"}

You speak as their assistant. When you say "you", you are talking only to this human. Do not invent teammate activity beyond the summaries provided.
""".strip()

    mode_block = f"""
Current interaction mode: self.

Answer clearly and concisely using the provided sections.
""".strip()

    parts = [
        system_header,
        FORMATTING_INSTRUCTIONS,
        canon_block,
        integ_block,
        teammate_block or "Teammate summaries: (none)",
    ]
    if rag_block:
        parts.append(rag_block)
    else:
        parts.append("Relevant past context: (none)")
    parts.append("Current chat transcript:\n" + transcript_block)
    parts.extend([rep_block, mode_block])
    prompt = "\n\n".join(parts).strip()

    meta = {
        "canon_items": canon_count,
        "integration_items": integ_count,
        "teammate_users": teammate_ids,
        "rag_items": rag_items,
        "transcript_msgs": transcript_msgs,
    }
    if not return_preview:
        return prompt, meta

    preview = {
        "sections": [
            {"key": "canon", "title": "Canon and priorities", "items": canon_items[:8]},
            {"key": "integrations", "title": "Recent integration summaries", "items": integ_items[:10]},
            {"key": "teammates", "title": "Teammate activity summaries", "items": teammate_block.splitlines()[1:] if teammate_block else []},
            {"key": "rag", "title": "Relevant past context", "items": rag_preview_items[:8]},
            {"key": "transcript", "title": "Current chat transcript", "meta": {"message_count": transcript_msgs}},
        ],
        "meta": meta,
    }
    # Log integration counts by source for observability
    logger.info(
        "[UnifiedContext] integ_by_source=%s rag_scope=%s rag_room_ids_count=%s request_id=%s",
        integ_counts_by_source,
        rag_scope,
        len(room_ids_for_rag),
        request_id,
    )
    return prompt, preview


def send_proactive_message(user_id: str, text: str, trigger: str, context: dict, db: Session):
    """
    Insert a proactive assistant message into the user's personal chat.
    Stores context as a meta marker inside content for simple dedup.
    """
    personal_room = get_or_create_personal_room(user_id, db)
    personal_chat = get_or_create_personal_assistant_chat(user_id, db)

    meta_id = context.get("email_id") or context.get("item_signature") or context.get("id") or context.get("signature") or str(uuid.uuid4())
    meta_blob = json.dumps({"type": "proactive", "trigger": trigger, "context": context})
    content = f"{text}\n\n[meta:{trigger}:{meta_id}] {meta_blob}"

    msg = MessageORM(
        id=str(uuid.uuid4()),
        room_id=personal_room.id,
        chat_instance_id=personal_chat.id,
        sender_id="assistant",
        sender_name="Parallel",
        role="assistant",
        content=content,
        user_id=user_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    personal_chat.last_message_at = msg.created_at
    db.commit()
    logger.info(f"[Proactive] Sent {trigger} message to user {user_id}")


def has_recent_proactive(chat_id: str, trigger: str, meta_id: str, db: Session, within_minutes: int = 60) -> bool:
    """Check if a proactive message with the same meta id was sent recently."""
    since = datetime.now(timezone.utc) - timedelta(minutes=within_minutes)
    marker = f"[meta:{trigger}:{meta_id}]"
    existing = (
        db.query(MessageORM)
        .filter(
            MessageORM.chat_instance_id == chat_id,
            MessageORM.content.contains(marker),
            MessageORM.created_at >= since,
        )
        .first()
    )
    return existing is not None


def check_approaching_deadlines_for_user(user_id: str, db: Session, window_minutes: int = 45):
    """
    Scan canonical plan for items due soon and send proactive reminders.
    """
    plan = get_or_create_canonical_plan(user_id, db)
    timeline = plan.approved_timeline or {}

    def parse_dt(val):
        if not val:
            return None
        try:
            if isinstance(val, datetime):
                return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
            if isinstance(val, str):
                if val.endswith("Z"):
                    val = val.replace("Z", "+00:00")
                return datetime.fromisoformat(val)
        except Exception:
            return None
        return None

    now = datetime.now(timezone.utc)
    soon = now + timedelta(minutes=window_minutes)

    for tf_sections in timeline.values():
        if not isinstance(tf_sections, dict):
            continue
        for items in tf_sections.values():
            if not isinstance(items, list):
                continue
            for item in items:
                deadline = parse_dt(item.get("deadline") or item.get("due") or item.get("start") or item.get("start_time"))
                if not deadline:
                    continue
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                if now <= deadline <= soon:
                    sig = item.get("signature") or generate_item_signature(item)
                    personal_chat = get_or_create_personal_assistant_chat(user_id, db)
                    if has_recent_proactive(personal_chat.id, "approaching_deadline", sig, db, within_minutes=60):
                        continue
                    when_str = deadline.isoformat()
                    title = item.get("title") or "Upcoming item"
                    send_proactive_message(
                        user_id=user_id,
                        text=f"Reminder: \"{title}\" is due soon at {when_str}.",
                        trigger="approaching_deadline",
                        context={"item_signature": sig, "due": when_str},
                        db=db,
                    )


def build_teammate_activity_summaries(
    db: Session,
    current_user: UserORM,
    days: int = 7,
    max_per_user: int = 3,
) -> tuple[str, list[str]]:
    """
    Return a text block of recent teammate activity summaries (from user_actions) for users
    who share at least one room with the requester. No timestamps included.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    room_ids = [rid for (rid,) in db.query(RoomMemberORM.room_id).filter(RoomMemberORM.user_id == current_user.id).all()]
    if not room_ids:
        return "", []

    teammate_ids = {
        uid
        for (uid,) in db.query(RoomMemberORM.user_id).filter(RoomMemberORM.room_id.in_(room_ids)).all()
        if uid and uid != current_user.id
    }
    if not teammate_ids:
        return "", []

    actions = (
        db.query(UserAction)
        .filter(
            UserAction.user_id.in_(teammate_ids),
            UserAction.timestamp >= cutoff,
            UserAction.activity_summary.isnot(None),
        )
        .order_by(UserAction.user_id.asc(), UserAction.timestamp.desc())
        .all()
    )
    if not actions:
        return "", []

    user_map = {
        u.id: u
        for u in db.query(UserORM).filter(UserORM.id.in_(teammate_ids)).all()
    }

    summaries: dict[str, list[str]] = {}
    for action in actions:
        uid = action.user_id
        if uid not in summaries:
            summaries[uid] = []
        if len(summaries[uid]) >= max_per_user:
            continue
        summary_text = (action.activity_summary or "").strip()
        if not summary_text:
            continue
        # Avoid duplicate consecutive summaries for same user
        if summaries[uid] and summary_text == summaries[uid][-1]:
            continue
        summaries[uid].append(summary_text)

    if not summaries:
        logger.info(
            "[TeamActivitySummaries] requester=%s shared_rooms=%s teammates=%s actions_scanned=%s summaries_included=0 users_included=[]",
            current_user.id,
            len(room_ids),
            len(teammate_ids),
            len(actions),
        )
        return "", []

    lines = ["Team activity (summaries):"]
    included_user_ids: list[str] = []
    for uid, items in summaries.items():
        if not items:
            continue
        display_name = user_map.get(uid).name if user_map.get(uid) else uid
        included_user_ids.append(uid)
        for item in items:
            lines.append(f"- {display_name}: {item}")

    logger.info(
        "[TeamActivitySummaries] requester=%s shared_rooms=%s teammates=%s actions_scanned=%s summaries_included=%s users_included=%s",
        current_user.id,
        len(room_ids),
        len(teammate_ids),
        len(actions),
        sum(len(v) for v in summaries.values()),
        included_user_ids,
    )
    return "\n".join(lines), included_user_ids

def get_or_create_personal_room(user_id: str, db: Session):
    """
    Get or create a special personal room for the user's 1:1 with AI.
    """
    from models import Room as RoomORM, RoomMember as RoomMemberORM, Organization as OrganizationORM

    # Ensure we have the user handy for org linkage
    user = db.query(UserORM).filter(UserORM.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    personal_room = (
        db.query(RoomORM)
        .join(RoomMemberORM, RoomMemberORM.room_id == RoomORM.id)
        .filter(RoomMemberORM.user_id == user_id, RoomORM.name == "Personal")
        .first()
    )
    if personal_room:
        return personal_room

    # Determine org_id (required). Prefer user's org, else first org, else create one.
    org_id = user.org_id
    if not org_id:
        existing_org = db.query(OrganizationORM).first()
        if existing_org:
            org_id = existing_org.id
            user.org_id = org_id
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            invite = secrets.token_urlsafe(8)
            try:
                invite = generate_invite_code()
            except NameError:
                pass
            org = OrganizationORM(
                id=str(uuid.uuid4()),
                name=f"{user.name}'s Organization" if getattr(user, "name", None) else "Personal Org",
                owner_user_id=user.id,
                invite_code=invite,
                created_at=datetime.now(timezone.utc),
            )
            db.add(org)
            db.commit()
            db.refresh(org)
            org_id = org.id
            user.org_id = org_id
            db.add(user)
            db.commit()
            db.refresh(user)

    personal_room = RoomORM(
        id=str(uuid.uuid4()),
        org_id=org_id,
        name="Personal",
        project_summary="",
        memory_summary="",
        created_at=datetime.now(timezone.utc),
    )
    db.add(personal_room)
    db.flush()

    member = RoomMemberORM(
        id=str(uuid.uuid4()),
        room_id=personal_room.id,
        user_id=user_id,
    )
    db.add(member)
    db.commit()
    db.refresh(personal_room)

    logger.info(f"[Assistant] Created personal room for user {user_id}")
    return personal_room


def get_or_create_personal_assistant_chat(user_id: str, db: Session):
    """
    Get or create the chat instance for the personal assistant within the personal room.
    """
    from models import ChatInstance as ChatInstanceORM, Message as MessageORM

    personal_room = get_or_create_personal_room(user_id, db)

    assistant_chat = (
        db.query(ChatInstanceORM)
        .filter(
            ChatInstanceORM.room_id == personal_room.id,
            ChatInstanceORM.name == "Parallel Assistant",
        )
        .first()
    )
    if assistant_chat:
        return assistant_chat

    assistant_chat = ChatInstanceORM(
        id=str(uuid.uuid4()),
        name="Parallel Assistant",
        room_id=personal_room.id,
        created_by_user_id=user_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(assistant_chat)
    db.flush()

    welcome_time = datetime.now(timezone.utc)
    welcome = MessageORM(
        id=str(uuid.uuid4()),
        room_id=personal_room.id,
        chat_instance_id=assistant_chat.id,
        sender_id="assistant",
        sender_name="Parallel",
        role="assistant",
        content="👋 Hey! I'm Parallel, your AI chief of staff. I'm here to help you manage your day, prioritize tasks, and coordinate with your team. What would you like to focus on today?",
        user_id=user_id,
        created_at=welcome_time,
    )
    db.add(welcome)

    assistant_chat.last_message_at = welcome_time
    db.commit()
    db.refresh(assistant_chat)

    logger.info(f"[Assistant] Created personal assistant chat for user {user_id}")
    return assistant_chat


async def incremental_sync_context(user_id: str, db: Session):
    """
    Background task to incrementally fetch new data and update context store.
    """
    from models import UserContextStore, User as UserORM, DailyBrief as DailyBriefORM
    from datetime import timedelta
    import uuid

    user = db.query(UserORM).filter(UserORM.id == user_id).first()
    if not user:
        return

    context_store = db.query(UserContextStore).filter(
        UserContextStore.user_id == user_id
    ).first()

    if not context_store:
        context_store = UserContextStore(
            id=str(uuid.uuid4()),
            user_id=user_id,
        )
        db.add(context_store)
        db.commit()
        db.refresh(context_store)

    last_sync = context_store.last_email_sync or (datetime.now(timezone.utc) - timedelta(days=7))

    logger.info(f"[Context Sync] Starting for user {user.email}, last sync: {last_sync}")

    try:
        new_emails = fetch_emails_since(user, db, since=last_sync)
        logger.info(f"[Context Sync] Fetched {len(new_emails)} new emails")
        current_emails = context_store.emails_recent or []
        context_store.emails_recent = merge_and_dedupe(current_emails, new_emails)
        context_store.last_email_sync = datetime.now(timezone.utc)

        # Proactive: urgent email detection
        urgency_keywords = ["urgent", "asap", "immediately", "deadline today"]
        for e in new_emails:
            subj = (e.get("subject") or "").lower()
            snip = (e.get("snippet") or "").lower()
            link = e.get("link") or f"https://mail.google.com/mail/u/0/#all/{e.get('id')}"
            if any(k in subj or k in snip for k in urgency_keywords):
                meta_id = e.get("id") or e.get("thread_id") or subj
                personal_chat = get_or_create_personal_assistant_chat(user_id, db)
                if not has_recent_proactive(personal_chat.id, "urgent_email", meta_id, db, within_minutes=240):
                    send_proactive_message(
                        user_id=user_id,
                        text=f"You just received an urgent email from {e.get('from', 'someone')}: \"{e.get('subject', 'No subject')}\". Do you want to adjust your plan or add a follow-up task?",
                        trigger="urgent_email",
                        context={"email_id": meta_id, "link": link, "snippet": e.get("snippet", ""), "subject": e.get("subject", "")},
                        db=db,
                    )
    except Exception as e:
        logger.error(f"[Context Sync] Email fetch failed: {e}")

    try:
        new_events = fetch_events_since(user, db, since=last_sync)
        logger.info(f"[Context Sync] Fetched {len(new_events)} new events")
        current_events = context_store.calendar_recent or []
        context_store.calendar_recent = merge_and_dedupe(current_events, new_events)
        context_store.last_calendar_sync = datetime.now(timezone.utc)
    except Exception as e:
        logger.error(f"[Context Sync] Calendar fetch failed: {e}")

    total = len(context_store.emails_recent or []) + len(context_store.calendar_recent or [])
    context_store.total_items_cached = total

    db.commit()
    logger.info(f"[Context Sync] Complete. Total cached: {total}")

    regenerate_brief_from_context(user, context_store, db)


def regenerate_brief_from_context(user: UserORM, context_store, db: Session):
    """
    Regenerate daily brief using data from context store instead of fresh API calls.
    """
    from models import DailyBrief as DailyBriefORM

    emails = context_store.emails_recent or []
    events = context_store.calendar_recent or []

    # Ensure links exist for legacy cached items
    for email in emails:
        if email.get("id") and not email.get("link"):
            email["link"] = f"https://mail.google.com/mail/u/0/#all/{email['id']}"
    for event in events:
        if event.get("id") and not event.get("link"):
            # Prefer view link for stability
            event["link"] = event.get("htmlLink") or f"https://calendar.google.com/calendar/event?eid={event['id']}"

    personal = _generate_personal_brief_with_ai(user, emails, events, db)
    org = _generate_org_brief_with_ai(user, db)

    today = datetime.now(timezone.utc).date()
    brief = db.query(DailyBriefORM).filter(
        DailyBriefORM.user_id == user.id,
        DailyBriefORM.date == today
    ).first()

    if not brief:
        new_id = str(uuid.uuid4())
        brief = DailyBriefORM(
            id=new_id,
            user_id=user.id,
            date=today,
            summary_json={}
        )
        logger.info(f"[Brief] Creating new brief with ID: {new_id}")
        db.add(brief)

    brief.summary_json = {
        "date": today.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "personal": personal,
        "org": org
    }
    brief.generated_at = datetime.now(timezone.utc)

    db.commit()
    logger.info(f"[Context Sync] Brief regenerated for {user.email}")


def _filter_past_timeline_items(timeline: dict, now: datetime) -> dict:
    """
    Remove timeline items with deadlines in the past.
    This is a safety filter in case the AI includes old items despite instructions.
    """
    from dateutil import parser as date_parser

    filtered_timeline = {}
    total_removed = 0

    for timeframe, sections in timeline.items():
        if not isinstance(sections, dict):
            filtered_timeline[timeframe] = sections
            continue

        filtered_sections = {}
        for section_key, items in sections.items():
            if not isinstance(items, list):
                filtered_sections[section_key] = items
                continue

            filtered_items = []
            for item in items:
                # Check if item has a deadline or date field
                deadline_str = item.get("deadline") or item.get("date")

                if not deadline_str:
                    # No deadline specified, keep it
                    filtered_items.append(item)
                    continue

                try:
                    # Try to parse the deadline
                    # Handle relative dates like "5pm today", "Monday", "tomorrow"
                    deadline_lower = deadline_str.lower()

                    # Skip relative future dates (these are OK)
                    if any(word in deadline_lower for word in ["today", "tomorrow", "next", "this week", "this month", "upcoming"]):
                        filtered_items.append(item)
                        continue

                    # Skip if no absolute date to parse
                    if any(word in deadline_lower for word in ["asap", "urgent", "soon", "tbd", "pending"]):
                        filtered_items.append(item)
                        continue

                    # Try to parse absolute date
                    try:
                        deadline_dt = date_parser.parse(deadline_str, fuzzy=True)

                        # Make timezone-aware if needed
                        if deadline_dt.tzinfo is None:
                            deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)

                        # Check if deadline is in the past (with 1-hour grace period for "today" items)
                        grace_period = timedelta(hours=1)
                        if deadline_dt < (now - grace_period):
                            title = item.get("title", "Unknown")
                            logger.info(f"[Date Filter] REMOVING past item: '{title}' (deadline: {deadline_str}, now: {now.strftime('%Y-%m-%d %H:%M')})")
                            total_removed += 1
                            continue  # Skip this item
                        else:
                            logger.debug(f"[Date Filter] Keeping future item: '{item.get('title', 'Unknown')}' (deadline: {deadline_str})")
                            filtered_items.append(item)
                    except (ValueError, OverflowError):
                        # Can't parse date, keep it to be safe
                        logger.debug(f"[Date Filter] Couldn't parse deadline '{deadline_str}', keeping item: {item.get('title', 'Unknown')}")
                        filtered_items.append(item)

                except Exception as e:
                    # If anything goes wrong, keep the item to be safe
                    logger.warning(f"[Date Filter] Error processing item: {e}")
                    filtered_items.append(item)

            filtered_sections[section_key] = filtered_items

        filtered_timeline[timeframe] = filtered_sections

    if total_removed > 0:
        logger.info(f"[Date Filter] ✂️  Removed {total_removed} past items from timeline")
    else:
        logger.info(f"[Date Filter] ✅ No past items found, all items are current")

    return filtered_timeline


def normalize_iso_timestamps(timeline: dict) -> dict:
    """
    Fix common ISO 8601 formatting issues in AI-generated timestamps.

    JavaScript Date() requires uppercase 'T' separator, but AI sometimes generates lowercase.
    This function normalizes timestamps to valid ISO 8601 format.

    Args:
        timeline: Timeline dict with potential timestamp fields

    Returns:
        Timeline with normalized timestamps
    """
    import re

    fixed_count = 0
    invalid_count = 0

    for timeframe in ["1d", "7d", "28d"]:
        for priority in ["urgent", "normal"]:
            items = timeline.get(timeframe, {}).get(priority, [])
            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue

                # Check all possible timestamp fields
                for field in ["deadline", "due_time", "start", "end", "start_time", "end_time"]:
                    if field not in item or not item[field]:
                        continue

                    value = item[field]
                    if not isinstance(value, str):
                        continue

                    original = value

                    # Fix lowercase 't' separator using regex to only replace between date and time
                    if 't' in value:
                        # Pattern: YYYY-MM-DD t HH:MM:SS
                        value = re.sub(
                            r'(\d{4}-\d{2}-\d{2})t(\d{2}:\d{2}:\d{2})',
                            r'\1T\2',
                            value
                        )
                        if value != original:
                            item[field] = value
                            fixed_count += 1
                            logger.debug(f"[Normalize] Fixed: {original} → {value} (item: {item.get('title', 'unknown')})")

                    # Validate it's parseable
                    try:
                        datetime.fromisoformat(value.replace('Z', '+00:00'))
                    except (ValueError, AttributeError) as e:
                        logger.warning(
                            f"[Normalize] Invalid timestamp for '{item.get('title', 'unknown')}': "
                            f"{field}='{value}' - {e}"
                        )
                        # Remove invalid timestamp rather than breaking
                        item.pop(field, None)
                        invalid_count += 1

    if fixed_count > 0:
        logger.info(f"[Normalize] ✅ Fixed {fixed_count} lowercase 't' timestamps")
    if invalid_count > 0:
        logger.warning(f"[Normalize] ⚠️  Removed {invalid_count} invalid timestamps")

    return timeline


def _generate_personal_brief_with_ai(user: UserORM, emails: list, events: list, db: Session) -> dict:
    """
    Use AI to generate intelligent personal brief with timeline categorization.
    """
    from app.services.canon import generate_item_signature

    events = events or []
    emails = emails or []

    logger.info(f"[Personal Brief AI] Input: {len(emails)} emails, {len(events)} events")

    all_items = list(events) + list(emails)

    logger.warning("=" * 80)
    logger.warning(f"🤖 [AI Input] Sending {len(all_items)} items to AI for categorization")
    logger.warning("[AI Input] === ITEMS SENT TO AI ===")

    total_events = len(events)
    for i, item in enumerate(all_items, 1):
        is_event = i <= total_events
        source_type = item.get("source_type") or ("calendar" if is_event else "email")
        time_value = (
            item.get("deadline")
            or item.get("start")
            or item.get("start_time")
            or item.get("date")
            or item.get("received_at")
            or "NO TIME"
        )
        title = item.get('title') or item.get('summary') or item.get('subject') or 'NO TITLE'
        logger.warning(f"  {i}. {title}")
        if i <= 10:  # Only show details for first 10 to reduce noise
            logger.warning(f"     Type: {source_type} | Time: {time_value}")

    if len(all_items) > 10:
        logger.warning(f"  ... and {len(all_items) - 10} more items")

    logger.warning("=" * 80)

    # Get list of completed/deleted task signatures to exclude
    completed_items = db.query(CompletedBriefItem).filter(
        CompletedBriefItem.user_id == user.id
    ).all()
    completed_sigs = {item.item_signature for item in completed_items if item.item_signature}
    logger.info(f"[Brief Gen] User has {len(completed_sigs)} completed tasks")
    
    if not emails and not events:
        logger.warning("[Personal Brief AI] No data - returning empty")
        return {
            "unread_emails": [],
            "upcoming_meetings": [],
            "calendar": [],
            "priorities": [],
            "mentions": [],
            "actions": [],
            "timeline": {
                "1d": {"urgent": [], "normal": []},
                "7d": {"urgent": [], "normal": []},
                "28d": {"urgent": [], "normal": []}
            }
        }
    
    # Build context for AI
    email_context = "\n".join([
        f"- [ID: {e.get('id', 'unknown')}] From: {e.get('from', 'Unknown')}, Subject: {e.get('subject', 'No subject')}, Date: {e.get('date', 'Unknown')}, Snippet: {e.get('snippet', '')[:100]}"
        for e in emails[:20]  # Increased from 15 to 20
    ]) if emails else "No unread emails"

    calendar_context = "\n".join([
        f"- [ID: {e.get('id', 'unknown')}] {e.get('summary', 'Untitled')} at {e.get('start_time', e.get('start', 'TBD'))} ({e.get('location', 'No location')})"
        for e in events[:15]
    ]) if events else "No upcoming meetings"
    
    user_name = user.name or user.email.split('@')[0]
    
    logger.info(f"[Personal Brief AI] Email context length: {len(email_context)} chars")
    logger.info(f"[Personal Brief AI] Calendar context length: {len(calendar_context)} chars")

    # Get user timezone for calendar-day based categorization
    from app.services.canon import get_user_timezone
    user_timezone_str = get_user_timezone(user, db)
    user_tz = pytz.timezone(user_timezone_str)

    # Get current date/time in user's timezone
    now_utc = datetime.now(timezone.utc)
    now_user = now_utc.astimezone(user_tz)
    today_date = now_user.date()
    tomorrow_date = today_date + timedelta(days=1)
    week_end_date = today_date + timedelta(days=7)
    month_end_date = today_date + timedelta(days=28)

    # Format dates for prompt
    today_str = now_user.strftime("%A, %B %d, %Y")
    current_time_str = now_user.strftime("%I:%M %p %Z")
    today_date_str = today_date.strftime("%Y-%m-%d")
    tomorrow_date_str = tomorrow_date.strftime("%Y-%m-%d")
    week_end_date_str = week_end_date.strftime("%Y-%m-%d")
    month_end_date_str = month_end_date.strftime("%Y-%m-%d")

    prompt = f"""You are generating a Daily Brief with Timeline for {user_name}.

TODAY'S DATE: {today_str}
CURRENT TIME: {current_time_str}
USER TIMEZONE: {user_timezone_str}

EMAILS ({len(emails)} unread):
{email_context}

CALENDAR (upcoming events):
{calendar_context}

Generate a JSON response with these sections:

{{
  "priorities": [
    {{"title": "Top priority action", "detail": "Why it matters"}},
    // 3-5 top priorities combining emails + calendar
  ],
  "unread_emails": [
    {{"title": "Reply to John's design feedback", "detail": "Urgent - needs response by EOD"}},
    // Only emails needing ACTION (3-5 max, skip newsletters)
  ],
  "upcoming_meetings": [
    {{"title": "Standup at 10am", "detail": "Prepare: yesterday's progress update"}},
    // All meetings for next 2 days with prep suggestions
  ],
  "actions": [
    {{"title": "Review Q4 roadmap before 2pm call", "detail": "High priority"}},
    // 3-5 specific next actions
  ],
  "timeline": {{
    "1d": {{
      "urgent": [
        {{"title": "Fix production bug", "detail": "Users affected now", "deadline": "5pm today", "source_type": "email", "source_id": "msg_123"}},
        // MUST handle TODAY: Explicit urgency (URGENT/ASAP keywords), deadlines today, imminent meetings, production issues
      ],
      "normal": [
        {{"title": "Reply to design feedback", "detail": "Review attached mockups", "deadline": "EOD", "source_type": "email", "source_id": "msg_456"}},
        // SHOULD handle today: Regular emails needing response, standard tasks, today's meetings
      ]
    }},
    "7d": {{
      "urgent": [
        {{"title": "Ship Gmail integration", "detail": "Demo deadline Friday", "deadline": "2025-12-13", "source_type": "email", "source_id": "msg_789"}},
        // Important THIS WEEK: Key deliverables, critical deadlines within 7 days, high-priority meetings
      ],
      "normal": [
        {{"title": "YC demo prep", "detail": "Prepare metrics deck", "deadline": "Friday 3pm", "source_type": "calendar", "source_id": "evt_abc"}},
        // Handle this week: Upcoming meetings needing prep, regular tasks due this week
      ]
    }},
    "28d": {{
      "urgent": [
        {{"title": "Q4 board deck", "detail": "Due end of month", "deadline": "Dec 31", "source_type": "email", "source_id": "msg_xyz"}},
        // Critical MONTHLY: Major milestones, key deadlines within 28 days
      ],
      "normal": [
        {{"title": "Review hiring pipeline", "detail": "Monthly check-in", "source_type": "calendar", "source_id": "evt_def"}},
        // General monthly: Ongoing projects, long-term tasks, routine monthly items
      ]
    }}
  }}
}}

CRITICAL DATE FILTERING RULES:
⚠️ EXTREMELY IMPORTANT - READ CAREFULLY:
- TODAY IS: {today_str}
- ONLY include events/tasks that are FUTURE or happening TODAY
- EXCLUDE ANY past events (meetings that already happened, expired deadlines)
- For calendar events: Check the date/time - if it's in the past, DO NOT include it
- For email deadlines: If a deadline has passed, DO NOT include it
- Examples of what to EXCLUDE:
  * Meeting on December 20 when today is December 23 ❌
  * "Due last Friday" when today is Monday ❌
  * "Deadline was yesterday" ❌
- Examples of what to INCLUDE:
  * Meeting later today ✅
  * Meeting tomorrow ✅
  * "Due this Friday" when today is Wednesday ✅
  * "Deadline next week" ✅

TIMEFRAME CATEGORIZATION RULES (CALENDAR-DAY BASED):

⚠️ CRITICAL: Categorize by CALENDAR DATE in user timezone ({user_timezone_str}), NOT by hours from now!

**1D (Daily Goals) - Items happening TODAY ONLY:**
- Calendar date: {today_date_str} (from 00:00:00 to 23:59:59)
- URGENT: Explicit urgency keywords (URGENT, ASAP), deadlines TODAY, production issues, critical blockers
- NORMAL: Regular emails needing response, standard tasks, today's meetings, items to handle EOD
- ⚠️ Example: If it's Saturday 11pm, only Saturday items go here (NOT Sunday morning items!)
- ⚠️ Event at 9am tomorrow ({tomorrow_date_str}) goes in 7D, NOT 1D (even if only 10 hours away)

**7D (Weekly Focus) - Items happening NEXT 7 DAYS (excluding today):**
- Date range: {tomorrow_date_str} through {week_end_date_str}
- URGENT: Key deliverables with THIS WEEK deadlines, critical meetings requiring prep, high-priority tasks
- NORMAL: Regular meetings this week, standard tasks due within 7 days, general follow-ups
- ⚠️ Tomorrow's events go HERE, not in 1D!

**28D (Monthly Objectives) - Items happening NEXT 28 DAYS (excluding this week):**
- Date range: After {week_end_date_str} through {month_end_date_str}
- URGENT: Major milestones due THIS MONTH, critical deadlines within 28 days, key project deliverables
- NORMAL: Ongoing projects, long-term tasks, routine monthly items, general goals
- ⚠️ Longer-term planning items only

**URGENCY CLASSIFICATION GUIDELINES:**
- URGENT = Explicit urgency indicators (URGENT/ASAP in text), imminent deadlines, critical importance
- NORMAL = Everything else - regular work that should be handled within the timeframe
- When uncertain, default to NORMAL (better to under-prioritize than over-prioritize)

CRITICAL ANTI-HALLUCINATION RULES:
- ONLY extract information that is EXPLICITLY stated in the emails/calendar above
- DO NOT infer goals, percentages, completion rates, or metrics unless directly mentioned
- DO NOT make up progress numbers (e.g., "50% complete", "2/5 done") unless those exact numbers appear in the context
- If a section has no clear items from the context, return an empty array []
- Better to return empty sections than to guess or fabricate information
- If you see vague references (like "YC Pilot Selling"), DO NOT expand them into specific goals like "Launch 5 pilots"

GENERAL RULES:
1. For emails: Skip newsletters, automated notifications, receipts
2. For meetings: Add "Prepare: X" suggestions for important meetings
3. Extract specific deadlines from email content when mentioned
4. Keep titles SHORT (under 60 chars), details under 100 chars
5. Return ONLY valid JSON, no markdown code fences
6. If an item fits multiple timeframes, put it in the SHORTEST timeframe (1D > 7D > 28D)
7. **CRITICAL**: ALWAYS include "source_type" (email/calendar) and "source_id" for EVERY timeline item
   - For emails: Use the email ID from the context
   - For calendar: Use the event ID from the context
   - This ensures items don't reappear after completion

⚠️⚠️⚠️ CRITICAL TIMESTAMP FORMAT REQUIREMENTS ⚠️⚠️⚠️

8. ALL deadline/due_time/start/end fields MUST use ISO 8601 with UPPERCASE 'T' separator.

✅ CORRECT EXAMPLES:
- "2025-12-30T17:00:00-08:00"
- "2025-12-31T09:30:00-08:00"
- "{today_date_str}T16:00:00-08:00" (example for today at 4pm PST)
- "{today_date_str}T16:00:00Z" (example for UTC)

❌ WRONG - THESE BREAK THE UI:
- "2025-12-30t17:00:00-08:00" ← lowercase 't' causes JavaScript Error
- "2025-12-30 17:00:00-08:00" ← space instead of 'T'
- "2025-12-30T17:00:00" ← missing timezone

WHY THIS IS CRITICAL:
JavaScript's Date() constructor REQUIRES uppercase 'T' per ISO 8601 standard.
Using lowercase 't' causes "Invalid Date" errors that crash the frontend timeline.

DOUBLE-CHECK: Before responding, verify EVERY timestamp has uppercase 'T' between date and time.

Focus on ACTIONABLE items. Don't include FYI information unless it requires a response.

IMPORTANT - EXCLUDE COMPLETED TASKS:
The user has already completed or dismissed these tasks (by their signatures):
{list(completed_sigs)[:20] if completed_sigs else "None"}

DO NOT include any task that matches these signatures in your timeline. The user has already dealt with these items.
"""

    logger.info(f"[Personal Brief AI] Calling OpenAI...")
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You are a personal productivity assistant that generates structured daily briefs. CRITICAL: Only include information explicitly present in the provided context. Never infer metrics, percentages, or goals not mentioned. If uncertain, leave sections empty. Always return valid JSON.\n\nIMPORTANT - EXCLUDE COMPLETED TASKS:\nThe user has already completed or dismissed these tasks (by their signatures):\n{list(completed_sigs)[:20] if completed_sigs else 'None'}\nDO NOT include any task that matches these signatures in your timeline. The user has already dealt with these items."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=1500  # Increased from 1000 to handle timeline data
        )
        
        content = response.choices[0].message.content.strip()
        logger.info(f"[Personal Brief AI] OpenAI response length: {len(content)} chars")
        
        # Remove markdown code fences if present
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        if content.endswith("```"):
            content = content[:-3].strip()

        ai_result = json.loads(content)
        logger.info(f"[Personal Brief AI] ✅ JSON parsed successfully")
        logger.info(f"[Personal Brief AI] Raw response type: {type(ai_result)}")

        # DEFENSIVE: Handle malformed AI responses
        timeline = ai_result.get('timeline', {})

        if not isinstance(timeline, dict):
            logger.error(f"[Personal Brief AI] ❌ AI returned timeline as {type(timeline).__name__}, expected dict")
            logger.error(f"[Personal Brief AI] Raw response: {str(ai_result)[:500]}...")
            # Return empty timeline structure to prevent crash
            timeline = {
                '1d': {'urgent': [], 'normal': []},
                '7d': {'urgent': [], 'normal': []},
                '28d': {'urgent': [], 'normal': []}
            }
            ai_result['timeline'] = timeline

        # DEFENSIVE: Validate each timeframe is a dict
        for timeframe in ['1d', '7d', '28d']:
            section = timeline.get(timeframe, {})

            if not isinstance(section, dict):
                logger.warning(f"[Personal Brief AI] ⚠️ Timeline {timeframe} is {type(section).__name__}, expected dict")
                timeline[timeframe] = {'urgent': [], 'normal': []}
                continue

            # Ensure urgent/normal keys exist and are lists
            if 'urgent' not in section or not isinstance(section.get('urgent'), list):
                section['urgent'] = []
            if 'normal' not in section or not isinstance(section.get('normal'), list):
                section['normal'] = []

            timeline[timeframe] = section

        ai_result['timeline'] = timeline

        # NOW safe to log (wrap in try/catch for extra safety)
        try:
            logger.warning("=" * 80)
            logger.warning("🧠 [AI Output] === AI DECISION ===")
            logger.warning(f"[AI Output] Items placed in 1d/urgent: {len(timeline['1d']['urgent'])}")
            logger.warning(f"[AI Output] Items placed in 1d/normal: {len(timeline['1d']['normal'])}")
            logger.warning(f"[AI Output] Items placed in 7d/urgent: {len(timeline['7d']['urgent'])}")
            logger.warning(f"[AI Output] Items placed in 7d/normal: {len(timeline['7d']['normal'])}")
            logger.warning(f"[AI Output] Items placed in 28d/urgent: {len(timeline['28d']['urgent'])}")
            logger.warning(f"[AI Output] Items placed in 28d/normal: {len(timeline['28d']['normal'])}")
            logger.warning(f"[AI Output] Priorities count: {len(ai_result.get('priorities', []))}")

            total_ai_output = sum(
                len(timeline.get(tf, {}).get(pr, []))
                for tf in ['1d', '7d', '28d']
                for pr in ['urgent', 'normal']
            )
            excluded_count = max(0, len(all_items) - total_ai_output)
            logger.warning(f"[AI Output] ✅ TOTAL items in AI output: {total_ai_output}")
            logger.warning(f"[AI Output] ⚠️ Items EXCLUDED by AI: {excluded_count}")

            output_signatures = set()
            for tf in ['1d', '7d', '28d']:
                for pr in ['urgent', 'normal']:
                    for item in timeline.get(tf, {}).get(pr, []):
                        sig = item.get("signature") or generate_item_signature(item)
                        output_signatures.add(sig)

            input_signature_map = {}
            for item in all_items:
                sig = generate_item_signature(item)
                title = item.get("title") or item.get("summary") or item.get("subject") or "NO TITLE"
                input_signature_map[sig] = title

            excluded_titles = [title for sig, title in input_signature_map.items() if sig not in output_signatures]
            if excluded_titles:
                logger.info(f"[AI Output] Items excluded by AI (by signature): {len(excluded_titles)}")
                for title in excluded_titles[:5]:
                    logger.info(f"  - {title}")
                if len(excluded_titles) > 5:
                    logger.info(f"  ... and {len(excluded_titles) - 5} more")
            else:
                logger.info("[AI Output] No items excluded by AI based on signatures")
            logger.info("=" * 80)
        except (KeyError, TypeError) as e:
            logger.error(f"[Personal Brief AI] Failed to log timeline stats: {e}")

        # CRITICAL: Normalize timestamps FIRST (fix lowercase 't' → uppercase 'T')
        # This must run BEFORE validation to prevent false warnings about lowercase 't'
        if 'timeline' in ai_result:
            ai_result['timeline'] = normalize_iso_timestamps(
                ai_result.get('timeline', {})
            )

        # Validate to prevent hallucinations (runs AFTER normalization)
        if 'timeline' in ai_result:
            ai_result['timeline'] = _validate_timeline_response(
                ai_result.get('timeline', {}),
                emails,
                events
            )

        # CRITICAL: Filter out past items (safety check in case AI included old events)
        if 'timeline' in ai_result:
            ai_result['timeline'] = _filter_past_timeline_items(
                ai_result.get('timeline', {}),
                now_utc
            )

        # CRITICAL: Generate signatures for ALL items using centralized function and exclude completed ones
        total_items_from_ai = count_timeline_items(ai_result.get("timeline") or {})
        excluded_count = 0
        for tf_key, sections in (ai_result.get("timeline") or {}).items():
            if not isinstance(sections, dict):
                continue
            for sec_key, sec_items in sections.items():
                if not isinstance(sec_items, list):
                    continue
                filtered_items = []
                for item in list(sec_items):
                    title = item.get("title") or item.get("subject") or ""
                    if not item.get("signature"):
                        # Use centralized signature generation based on source_id
                        signature = generate_item_signature(item)
                        item["signature"] = signature
                        logger.info(f"[Brief Gen] Generated signature for timeline/{tf_key}/{sec_key} '{title[:50]}': {signature}")
                    else:
                        logger.info(f"[Brief Gen] Existing signature for timeline/{tf_key}/{sec_key} '{title[:50]}': {item.get('signature')}")
                    if item["signature"] in completed_sigs:
                        excluded_count += 1
                        logger.info(f"[Brief Gen] EXCLUDING completed: {title[:50]}")
                        continue
                    filtered_items.append(item)
                    logger.info(f"[Brief Gen] Including: {title[:50]}")
                sections[sec_key] = filtered_items

        # Add signatures to priorities, actions, emails, meetings (fallback to title/source_id)
        for section in ["priorities", "actions", "unread_emails", "upcoming_meetings"]:
            items = ai_result.get(section, [])
            if isinstance(items, list):
                for item in items:
                    if item.get("signature"):
                        continue
                    signature = generate_item_signature(item)
                    item["signature"] = signature
                    title = item.get("title") or item.get("subject") or ""
                    logger.info(f"[Brief Gen] Generated signature for {section} '{title[:50]}': {signature}")

        total_items_after_filter = count_timeline_items(ai_result.get("timeline") or {})
        logger.info(f"[Brief Gen] AI returned {total_items_from_ai} timeline items")
        logger.info(f"[Brief Gen] Filtered to {total_items_after_filter} items (excluded {excluded_count} completed)")

        # Attach source links for emails (fuzzy match)
        if 'unread_emails' in ai_result:
            for item in ai_result['unread_emails']:
                title = item.get("title") or ""
                words = [w for w in title.split() if len(w) > 4]
                for email in emails:
                    subj = email.get("subject") or ""
                    if subj and words and any(word.lower() in subj.lower() for word in words):
                        item["link"] = email.get("link")
                        item["source_id"] = email.get("id")
                        item["source_type"] = "email"
                        logger.info(f"[Link Match] Matched '{title}' to email '{subj}'")
                        break

        # Attach source links for meetings (fuzzy match)
        if 'upcoming_meetings' in ai_result:
            for item in ai_result['upcoming_meetings']:
                title = item.get("title") or ""
                words = [w for w in title.split() if len(w) > 4]
                for ev in events:
                    summ = ev.get("summary") or ""
                    if summ and words and any(word.lower() in summ.lower() for word in words):
                        item["link"] = ev.get("link")
                        item["source_id"] = ev.get("id")
                        item["source_type"] = "calendar"
                        logger.info(f"[Link Match] Matched meeting '{title}' to event '{summ}'")
                        break

        # Attach source links in timeline (fuzzy match)
        if 'timeline' in ai_result:
            for timeframe in ['1d', '7d', '28d']:
                if timeframe not in ai_result['timeline']:
                    continue
                for section_key, section_items in ai_result['timeline'][timeframe].items():
                    if not isinstance(section_items, list):
                        continue
                    for item in section_items:
                        title = item.get("title") or ""
                        words = [w for w in title.split() if len(w) > 4]
                        matched = False
                        for email in emails:
                            subj = email.get("subject") or ""
                            if subj and words and any(word.lower() in subj.lower() for word in words):
                                item.setdefault("source", {})
                                item["source"]["type"] = "email"
                                item["source"]["id"] = email.get("id")
                                item["source"]["link"] = email.get("link")
                                matched = True
                                logger.info(f"[Link Match] Timeline '{title}' -> email '{subj}'")
                                break
                        if matched:
                            continue
                        for ev in events:
                            summ = ev.get("summary") or ""
                            if summ and words and any(word.lower() in summ.lower() for word in words):
                                item.setdefault("source", {})
                                item["source"]["type"] = "calendar"
                                item["source"]["id"] = ev.get("id")
                                item["source"]["link"] = ev.get("link")
                                logger.info(f"[Link Match] Timeline '{title}' -> event '{summ}'")
                                break

        logger.info(f"[Links] Unread emails with links: {[e.get('link') for e in ai_result.get('unread_emails', [])]}")
        logger.info(f"[Links] Meetings with links: {[m.get('link') for m in ai_result.get('upcoming_meetings', [])]}")
        logger.info(f"[Debug Links] Sample email: {emails[0] if emails else 'No emails'}")
        logger.info(f"[Debug Links] AI unread_emails: {ai_result.get('unread_emails', [])[:1]}")
        
        # Ensure timeline structure exists
        if 'timeline' not in ai_result:
            ai_result['timeline'] = {
                "1d": {"critical": [], "high_priority": []},
                "7d": {"milestones": [], "upcoming": []},
                "28d": {"goals": [], "progress": {}}
            }

        # Filter out items the user already completed
        if 'priorities' in ai_result:
            ai_result['priorities'] = filter_completed_items(
                ai_result['priorities'],
                user.id,
                db
            )

        if 'unread_emails' in ai_result:
            ai_result['unread_emails'] = filter_completed_items(
                ai_result['unread_emails'],
                user.id,
                db
            )

        if 'upcoming_meetings' in ai_result:
            ai_result['upcoming_meetings'] = filter_completed_items(
                ai_result['upcoming_meetings'],
                user.id,
                db
            )

        if 'actions' in ai_result:
            ai_result['actions'] = filter_completed_items(
                ai_result['actions'],
                user.id,
                db
            )

        if 'timeline' in ai_result:
            for timeframe in ['1d', '7d', '28d']:
                if timeframe in ai_result['timeline']:
                    for section_key, section_items in ai_result['timeline'][timeframe].items():
                        if isinstance(section_items, list):
                            ai_result['timeline'][timeframe][section_key] = filter_completed_items(
                                section_items,
                                user.id,
                                db
                            )
        
        result = {
            "priorities": ai_result.get("priorities", []),
            "unread_emails": ai_result.get("unread_emails", []),
            "upcoming_meetings": ai_result.get("upcoming_meetings", []),
            "calendar": ai_result.get("upcoming_meetings", []),
            "mentions": [],
            "actions": ai_result.get("actions", []),
            "timeline": ai_result.get("timeline", {
                "1d": {"critical": [], "high_priority": []},
                "7d": {"milestones": [], "upcoming": []},
                "28d": {"goals": [], "progress": {}}
            })
        }
        
        logger.info(f"[Personal Brief AI] ✅ SUCCESS")
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"[Personal Brief AI] ❌ JSON parsing failed: {e}")
        logger.error(f"[Personal Brief AI] Raw content: {content}")
        return _fallback_personal_brief(emails, events)
        
    except Exception as e:
        logger.error(f"[Personal Brief AI] ❌ OpenAI failed: {e}", exc_info=True)
        return _fallback_personal_brief(emails, events)

def _fallback_personal_brief(emails: list, events: list) -> dict:
    """Fallback if AI fails"""
    logger.info("[Personal Brief AI] Using FALLBACK formatting")
    return {
        "priorities": [],
        "unread_emails": [
            {"title": e.get("subject", "No subject"), "detail": f"From: {e.get('from', 'Unknown')}"}
            for e in emails[:5]
        ],
        "upcoming_meetings": [
            {"title": e.get("summary", "Untitled"), "detail": f"at {e.get('start_time', e.get('start', 'TBD'))}"}
            for e in events[:5]
        ],
        "calendar": events[:5],
        "mentions": [],
        "actions": [],
        "timeline": {
            "1d": {"critical": [], "high_priority": []},
            "7d": {"milestones": [], "upcoming": []},
            "28d": {"goals": [], "progress": {}}
        }
    }

def _validate_timeline_response(timeline: dict, emails: list, events: list) -> dict:
    """
    Validate AI timeline output and remove suspicious hallucinations.
    """
    # Build searchable context from actual data
    email_text = ' '.join([
        f"{e.get('subject', '')} {e.get('snippet', '')}"
        for e in emails
    ]).lower()

    calendar_text = ' '.join([
        f"{e.get('summary', '')} {e.get('description', '')}"
        for e in events
    ]).lower()

    all_context = email_text + ' ' + calendar_text

    # Validate 28D progress metrics (most prone to hallucination)
    if '28d' in timeline and 'progress' in timeline['28d']:
        validated_progress = {}

        for key, value in timeline['28d']['progress'].items():
            value_str = str(value).lower()

            # Check if this metric/number appears in actual context
            # Look for the key concept
            key_terms = key.replace('_', ' ').split()

            # If value contains numbers/percentages, verify they exist in context
            import re
            if any(char.isdigit() for char in value_str) or '%' in value_str:
                numbers = re.findall(r'\d+', value_str)

                has_key_term = any(term in all_context for term in key_terms)
                has_number = any(num in all_context for num in numbers)

                if has_key_term and has_number:
                    validated_progress[key] = value
                else:
                    logger.warning(f"[Timeline Validation] Removed suspicious metric: {key}: {value}")
            else:
                # Non-numeric progress, keep if key terms found
                if any(term in all_context for term in key_terms):
                    validated_progress[key] = value

        timeline['28d']['progress'] = validated_progress

    # Validate goal deadlines - remove if dates seem fabricated
    for timeframe in ['1d', '7d', '28d']:
        if timeframe not in timeline:
            continue

        for section in timeline[timeframe].values():
            if not isinstance(section, list):
                continue

            for item in section:
                if not isinstance(item, dict):
                    continue
                if 'deadline' in item:
                    deadline_str = str(item['deadline']).lower()
                    if deadline_str not in all_context and deadline_str not in ['today', 'tomorrow', 'eod', 'asap']:
                        if any(char.isdigit() for char in deadline_str):
                            logger.warning(f"[Timeline Validation] Suspicious deadline: {item.get('title')} - {deadline_str}")

    return timeline

def _fallback_personal_brief(emails: list, events: list) -> dict:
    """Fallback if AI fails"""
    logger.info("[Personal Brief AI] Using FALLBACK formatting")
    return {
        "priorities": [],
        "unread_emails": [
            {"title": e.get("subject", "No subject"), "detail": f"From: {e.get('from', 'Unknown')}"}
            for e in emails[:5]
        ],
        "upcoming_meetings": [
            {"title": e.get("summary", "Untitled"), "detail": f"at {e.get('start_time', e.get('start', 'TBD'))}"}
            for e in events[:5]
        ],
        "calendar": events[:5],
        "mentions": [],
        "actions": [],
    }

def _generate_org_brief_with_ai(user: UserORM, db: Session) -> dict:
    """
    Generate org-level brief from team activity.
    """
    logger.info(f"[Org Brief AI] Starting for user {user.email}")
    
    # ⭐ FIXED IMPORT - User is the actual SQLAlchemy model
    from models import Message, RoomMember, User
    from datetime import timedelta
    
    # Get user's rooms
    room_ids = db.query(RoomMember.room_id).filter(
        RoomMember.user_id == user.id
    ).all()
    room_ids = [r[0] for r in room_ids]
    
    logger.info(f"[Org Brief AI] User is in {len(room_ids)} rooms")
    
    if not room_ids:
        logger.warning("[Org Brief AI] No rooms - returning empty")
        return {
            "activity": [],
            "fires": [],
            "statuses": [],
            "bottlenecks": [],
            "risks": [],
        }
    
    # Get messages from last 24 hours - JOIN with User table
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    messages = db.query(Message, User).join(
        User, Message.sender_id == User.id
    ).filter(
        Message.room_id.in_(room_ids),
        Message.created_at >= since,
        Message.sender_id != user.id
    ).order_by(Message.created_at.desc()).limit(50).all()
    
    logger.info(f"[Org Brief AI] Found {len(messages)} messages in last 24h")
    
    if not messages:
        logger.warning("[Org Brief AI] No recent messages - returning empty")
        return {
            "activity": [],
            "fires": [],
            "statuses": [],
            "bottlenecks": [],
            "risks": [],
        }
    
    # Group by sender - messages is list of tuples (Message, User)
    activity_by_person = {}
    for msg, sender_user in messages:
        sender = sender_user.name or sender_user.email.split('@')[0]
        if sender not in activity_by_person:
            activity_by_person[sender] = []
        activity_by_person[sender].append(msg.content[:200])
    
    logger.info(f"[Org Brief AI] Activity from {len(activity_by_person)} people")
    
    # Build context
    context = "\n\n".join([
        f"{sender}:\n" + "\n".join([f"  - {msg}" for msg in msgs[:3]])
        for sender, msgs in list(activity_by_person.items())[:10]
    ])
    
    logger.info(f"[Org Brief AI] Context length: {len(context)} chars")
    
    prompt = f"""Summarize recent team activity into 3-5 key updates.

RECENT MESSAGES (last 24 hours):
{context}

Return JSON array:
[
  {{"title": "Yug is blocked on API integration", "detail": "Waiting for OAuth credentials from IT"}},
  {{"title": "Sean shipped new auth flow", "detail": "JWT tokens now refresh automatically"}},
  ...
]

Focus on:
- Blockers or issues team members mentioned
- Completed work or shipped features
- Important questions that need answers
- Key decisions or updates

RULES:
1. Keep titles SHORT and ACTIONABLE (under 60 chars)
2. Extract the KEY POINT, not exact quotes
3. Focus on HIGH-SIGNAL items (skip small talk)
4. Return 3-5 items max
5. Return ONLY valid JSON array, no markdown

If there are no significant updates, return an empty array [].
"""

    logger.info(f"[Org Brief AI] Calling OpenAI...")
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are summarizing team activity. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        content = response.choices[0].message.content.strip()
        logger.info(f"[Org Brief AI] OpenAI response: {content[:200]}...")
        
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        if content.endswith("```"):
            content = content[:-3].strip()
        
        activity = json.loads(content)
        logger.info(f"[Org Brief AI] ✅ Parsed {len(activity)} activity items")
        
        return {
            "activity": activity,
            "fires": [],
            "statuses": [],
            "bottlenecks": [],
            "risks": [],
        }
        
    except Exception as e:
        logger.error(f"[Org Brief AI] ❌ Failed: {e}", exc_info=True)
        # Fallback - show raw messages
        logger.info("[Org Brief AI] Using FALLBACK")
        return {
            "activity": [
                {"title": f"{sender_user.name or 'Team member'}: {msg.content[:50]}...", "detail": ""}
                for msg, sender_user in messages[:5]
            ],
            "fires": [],
            "statuses": [],
            "bottlenecks": [],
            "risks": [],
        }

@api_router.get("/org/me", response_model=OrgOut)
def org_me(request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    org = get_or_create_org_for_user(db, user)

    # if you wired OrganizationORM.users relationship, this will work
    members = []
    if getattr(org, "users", None):
        for u in org.users:
            members.append(
                OrgMemberOut(
                    id=u.id,
                    name=u.name or u.email,
                    role=getattr(u, "role", None),
                )
            )

    return OrgOut(
        id=org.id,
        name=org.name,
        members=members,
    )

# def build_system_prompt_for_room(
#     db: Session,
#     room: RoomORM,
#     user: UserORM,
#     mode: str = "self",
#     chat_instance: ChatInstanceORM | None = None,
# ) -> str:
#     """
#     Stage-1: safe system prompt with room + team activity context.
#     """

#     effective_mode = mode or "self"

#     logger.info(
#         "=== build_system_prompt_for_room V2_NO_TEAM_SUMMARY user_id=%s room_id=%s mode=%s module=%s ===",
#         getattr(user, "id", None),
#         getattr(room, "id", None),
#         effective_mode,
#         __name__,
#     )

#     # This MUST only include:
#     # - this room's messages
#     # - this room's project/memory summary (if any)
#     # - recent teammate activity inside this room
#     base_ctx = build_system_context(db, room, chat_instance)
#     team_ctx = build_team_activity_context(db, room, user)

#     system_header = """
# SYSTEM_VERSION_TAG: PARALLEL_V2_NO_TEAM_SUMMARY

# You are ONLY allowed to use information that appears in:
# - the room context and summaries provided below,
# - the current user's messages, and
# - the recent teammate activity context provided below (for this room only).

# You DO NOT have access to:
# - any hidden teammate logs,
# - any activity feeds,
# - or any messages from other rooms.

# If you are asked what a teammate did, said, or asked, and that is not
# explicitly visible in the room or team activity context, you MUST answer that you do not know.
# Do NOT invent or guess teammate behavior or questions.

# You are the Parallel workspace assistant.
# The backend automatically creates inbox tasks and notifications based on what the user writes.

# When the user says things like remind me to ..., a reminder task is created in their own inbox.

# When the user says remind/notify/tell/ping <Name> to ..., the system will create an inbox task and notification for that teammate, as long as their name can be resolved.

# You must not tell the user that you “can’t send messages” or that they should “set a reminder on their phone or calendar”.
# Instead, acknowledge what the system does. For example:

# Got it — I’ve added a reminder in your Parallel inbox to do that.

# Done — I’ve created a task for <Name> and added it to their Parallel inbox.

# Use natural, concise language, but always speak as if these inbox tasks and notifications are actually being created by the backend.
# """.strip()

#     rep_block = f"""
# You are the dedicated AI representative for this human.

# - name: {user.name or "Unknown"}
# - id: {user.id}
# - role: {user.role or "(none specified)"}

# You speak as their assistant.
# When you say "you", you are talking only to this human.
# Do not treat other teammates' messages as if they were from this user.
# Do not assume knowledge of teammates beyond what is explicitly included in the room context.
# Answer clearly and directly, focusing on helping this human accomplish their goals.
# """.strip()

#     mode_block = f"""
# Current interaction mode: {effective_mode}.

# In this mode, your primary job is to answer the user's question helpfully
# and concisely, using the room context above when it is relevant.
# """.strip()

#     parts = [system_header, base_ctx]
#     if team_ctx:
#         parts.append(team_ctx)
#     parts.extend([rep_block, mode_block])
#     prompt = "\n\n".join(parts).strip()

#     logger.info(
#         "=== final system prompt V2_NO_TEAM_SUMMARY for user_id=%s at %s ===",
#         getattr(user, "id", None),
#         datetime.now(timezone.utc).isoformat(),
#     )
#     return prompt

def build_system_prompt_for_room(
    db: Session,
    room: RoomORM,
    user: UserORM,
    mode: str = "self",
    chat_instance: ChatInstanceORM | None = None,
    user_query: Optional[str] = None,  # NEW: For RAG retrieval
) -> str:
    """
    Stage-1: safe system prompt with room + team activity context + RAG.
    """

    effective_mode = mode or "self"

    logger.info(
        "=== build_system_prompt_for_room V2_WITH_RAG user_id=%s room_id=%s mode=%s module=%s ===",
        getattr(user, "id", None),
        getattr(room, "id", None),
        effective_mode,
        __name__,
    )

    # Existing context builders
    base_ctx = build_system_context(db, room, chat_instance)
    team_ctx = build_team_activity_context(db, room, user)
    teammate_summary_block, teammate_ids = build_teammate_activity_summaries(db, user)
    
    # NEW: RAG context retrieval
    rag_ctx = ""
    if user_query:
        try:
            relevant_context = get_relevant_context(
                db=db,
                query=user_query,
                room_ids=[room.id],
                limit=10,
            )
            if relevant_context:
                rag_ctx = build_rag_context(relevant_context, user.name)
                logger.info(
                    "RAG retrieved %d relevant context items for query",
                    len(relevant_context),
                )
        except Exception as e:
            logger.error("RAG retrieval failed: %s", e)
            # Continue without RAG if it fails

    system_header = """
SYSTEM_VERSION_TAG: PARALLEL_V2_WITH_RAG

You are ONLY allowed to use information that appears in:
- the room context and summaries provided below,
- the RELEVANT PAST CONTEXT section (if present - retrieved via semantic search),
- the current user's messages, and
- the recent teammate activity context provided below (for teammates who share rooms with this user).

You DO NOT have access to:
- any hidden teammate logs,
- any activity feeds,
- or any messages from other rooms.

If you are asked what a teammate did, said, or asked, and that is not
explicitly visible in the room, RAG context, or team activity context, you MUST answer that you do not know.
Do NOT invent or guess teammate behavior or questions.

You are the Parallel workspace assistant.
The backend automatically creates inbox tasks and notifications based on what the user writes.

When the user says things like remind me to ..., a reminder task is created in their own inbox.

When the user says remind/notify/tell/ping <Name> to ..., the system will create an inbox task and notification for that teammate, as long as their name can be resolved.

You must not tell the user that you "can't send messages" or that they should "set a reminder on their phone or calendar".
Instead, acknowledge what the system does. For example:

Got it — I've added a reminder in your Parallel inbox to do that.

Done — I've created a task for <Name> and added it to their Parallel inbox.

Use natural, concise language, but always speak as if these inbox tasks and notifications are actually being created by the backend.
""".strip()

    rep_block = f"""
You are the dedicated AI representative for this human.

- name: {user.name or "Unknown"}
- id: {user.id}
- role: {user.role or "(none specified)"}

You speak as their assistant.
When you say "you", you are talking only to this human.
Do not treat other teammates' messages as if they were from this user.
Do not assume knowledge of teammates beyond what is explicitly included in the room context.
Answer clearly and directly, focusing on helping this human accomplish their goals.
""".strip()

    mode_block = f"""
Current interaction mode: {effective_mode}.

In this mode, your primary job is to answer the user's question helpfully
and concisely, using the room context above when it is relevant.
""".strip()

    # Build prompt with RAG context inserted after base context
    parts = [system_header, FORMATTING_INSTRUCTIONS, base_ctx]
    if rag_ctx:  # NEW: Insert RAG context
        parts.append(rag_ctx)
    if teammate_summary_block:
        parts.append(teammate_summary_block)
    if team_ctx:
        parts.append(team_ctx)
    parts.extend([rep_block, mode_block])
    prompt = "\n\n".join(parts).strip()

    logger.info(
        "=== final system prompt V2_WITH_RAG for user_id=%s at %s ===",
        getattr(user, "id", None),
        datetime.now(timezone.utc).isoformat(),
    )
    if teammate_summary_block:
        logger.info(
            "[TeamActivitySummaries] included=%s users=%s",
            len(teammate_ids),
            teammate_ids,
        )
    return prompt

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=60))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def to_message_out(m: MessageORM, db: Session) -> MessageOut:
    user_id = m.user_id
    sender = m.sender_id or ""
    if not user_id and sender.startswith("user:"):
        user_id = sender.replace("user:", "", 1)
    elif not user_id and sender.startswith("agent:"):
        agent_id = sender.replace("agent:", "", 1)
        agent = (
            db.query(AgentORM)
            .filter(AgentORM.id == agent_id)
            .first()
        )
        if agent:
            user_id = agent.user_id

    return MessageOut(
        id=m.id,
        chat_instance_id=m.chat_instance_id,
        sender_id=m.sender_id,
        sender_name=m.sender_name,
        role=m.role,
        content=m.content,
        created_at=m.created_at,
        user_id=user_id,
    )


def to_message_out_batch(messages: list[MessageORM], db: Session) -> list[MessageOut]:
    """
    PERFORMANCE FIX: Batch-convert messages to MessageOut, loading all agents in one query.
    This eliminates N+1 queries when processing message lists.
    """
    # Extract all agent IDs that need to be looked up
    agent_ids_to_fetch = []
    for m in messages:
        sender = m.sender_id or ""
        if not m.user_id and sender.startswith("agent:"):
            agent_id = sender.replace("agent:", "", 1)
            agent_ids_to_fetch.append(agent_id)

    # Batch load all agents in one query
    agent_map = {}
    if agent_ids_to_fetch:
        agents = (
            db.query(AgentORM)
            .filter(AgentORM.id.in_(agent_ids_to_fetch))
            .all()
        )
        agent_map = {agent.id: agent for agent in agents}

    # Convert all messages using the pre-loaded agent map
    results = []
    for m in messages:
        user_id = m.user_id
        sender = m.sender_id or ""

        if not user_id and sender.startswith("user:"):
            user_id = sender.replace("user:", "", 1)
        elif not user_id and sender.startswith("agent:"):
            agent_id = sender.replace("agent:", "", 1)
            agent = agent_map.get(agent_id)
            if agent:
                user_id = agent.user_id

        results.append(MessageOut(
            id=m.id,
            chat_instance_id=m.chat_instance_id,
            sender_id=m.sender_id,
            sender_name=m.sender_name,
            role=m.role,
            content=m.content,
            created_at=m.created_at,
            user_id=user_id,
        ))

    return results

def get_default_chat_instance(
    db: Session,
    room: RoomORM,
    created_by_user_id: Optional[str] = None,
) -> ChatInstanceORM:
    """
    Return the default chat instance for a room.
    Prefers a chat named 'General', otherwise falls back to the first created chat.
    Creates a General chat if none exist.
    """
    general = (
        db.query(ChatInstanceORM)
        .filter(
            ChatInstanceORM.room_id == room.id,
            func.lower(ChatInstanceORM.name) == "general",
        )
        .first()
    )
    if general:
        return general

    existing = (
        db.query(ChatInstanceORM)
        .filter(ChatInstanceORM.room_id == room.id)
        .order_by(ChatInstanceORM.created_at.asc())
        .first()
    )
    if existing:
        return existing

    chat = ChatInstanceORM(
        id=str(uuid.uuid4()),
        room_id=room.id,
        name="General",
        created_by_user_id=created_by_user_id,
        created_at=datetime.now(timezone.utc),
        last_message_at=None,
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat

def get_preferred_chat_instance(
    db: Session,
    room: RoomORM,
    chat_id: Optional[str] = None,
    created_by_user_id: Optional[str] = None,
) -> ChatInstanceORM:
    """
    Choose which chat to surface for a room response:
    - If chat_id provided, return that chat (404 if missing/room mismatch handled upstream).
    - Else, the most recent chat by last_message_at (falls back to newest created).
    - Else, create/return the General chat.
    """
    if chat_id:
        chat = db.get(ChatInstanceORM, chat_id)
        if chat and chat.room_id == room.id:
            return chat

    chat = (
        db.query(ChatInstanceORM)
        .filter(ChatInstanceORM.room_id == room.id)
        .order_by(
            ChatInstanceORM.last_message_at.desc().nullslast(),
            ChatInstanceORM.created_at.desc(),
        )
        .first()
    )
    if chat:
        return chat

    return get_default_chat_instance(db, room, created_by_user_id)

def to_chat_instance_out(db: Session, chat: ChatInstanceORM) -> ChatInstanceOut:
    message_count = (
        db.query(MessageORM)
        .filter(MessageORM.chat_instance_id == chat.id)
        .count()
    )
    result = ChatInstanceOut(
        id=chat.id,
        room_id=chat.room_id,
        name=chat.name,
        created_by_user_id=chat.created_by_user_id,
        created_at=chat.created_at,
        last_message_at=chat.last_message_at,
        message_count=message_count,
    )
    return result


def to_chat_instance_out_batch(db: Session, chats: list[ChatInstanceORM]) -> list[ChatInstanceOut]:
    """
    PERFORMANCE FIX: Batch-convert chats to ChatInstanceOut, loading all message counts in one query.
    This eliminates N+1 queries when listing chats.
    """
    if not chats:
        return []

    # Batch load message counts for all chats in one query
    chat_ids = [chat.id for chat in chats]
    message_counts_raw = (
        db.query(
            MessageORM.chat_instance_id,
            func.count(MessageORM.id).label('count')
        )
        .filter(MessageORM.chat_instance_id.in_(chat_ids))
        .group_by(MessageORM.chat_instance_id)
        .all()
    )

    # Build a lookup map: chat_id -> count
    message_count_map = {row[0]: row[1] for row in message_counts_raw}

    # Convert all chats using the pre-loaded counts
    results = []
    for chat in chats:
        message_count = message_count_map.get(chat.id, 0)
        results.append(ChatInstanceOut(
            id=chat.id,
            room_id=chat.room_id,
            name=chat.name,
            created_by_user_id=chat.created_by_user_id,
            created_at=chat.created_at,
            last_message_at=chat.last_message_at,
            message_count=message_count,
        ))

    return results

def require_chat_access(
    db: Session,
    user: UserORM,
    chat_id: str,
) -> tuple[ChatInstanceORM, RoomORM]:
    chat = db.get(ChatInstanceORM, chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")

    room = db.get(RoomORM, chat.room_id)
    if not room:
        raise HTTPException(404, "Room not found for chat")

    ensure_room_access(db, user, room)
    membership = (
        db.query(RoomMemberORM)
        .filter(RoomMemberORM.room_id == room.id, RoomMemberORM.user_id == user.id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this room")
    return chat, room

def room_to_response(
    db: Session,
    room: RoomORM,
    chat: Optional[ChatInstanceORM] = None,
    chat_id: Optional[str] = None,
    created_by_user_id: Optional[str] = None,
    context_preview: Optional[dict] = None,
) -> RoomResponse:
    chat = chat or get_preferred_chat_instance(
        db,
        room,
        chat_id=chat_id,
        created_by_user_id=created_by_user_id,
    )

    messages = []
    if chat:
        messages = (
            db.query(MessageORM)
            .filter(MessageORM.chat_instance_id == chat.id)
            .order_by(MessageORM.created_at.asc())
            .all()
        )
    memory_count = (
        db.query(MemoryORM).filter(MemoryORM.room_id == room.id).count()
    )
    # PERFORMANCE FIX: Use batch loading to eliminate N+1 queries
    return RoomResponse(
        room_id=room.id,
        room_name=room.name,
        active_chat_id=chat.id if chat else None,
        active_chat_name=chat.name if chat else None,
        project_summary=room.project_summary or "",
        memory_summary=room.memory_summary or "",
        memory_count=memory_count,
        messages=to_message_out_batch(messages, db),
        context_preview=context_preview,
    )

@api_router.post("/chats")
async def legacy_create_chat(
    body: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new chat in user's personal room (legacy compatibility).
    """
    personal_room = get_or_create_personal_room(current_user.id, db)

    chat_name = (body or {}).get("name") or "New Chat"
    room_id = (body or {}).get("room_id") or personal_room.id

    new_chat = ChatInstanceORM(
        id=str(uuid.uuid4()),
        room_id=room_id,
        name=chat_name,
        created_by_user_id=current_user.id,
        created_at=datetime.now(timezone.utc),
        last_message_at=datetime.now(timezone.utc),
    )
    db.add(new_chat)
    db.commit()
    db.refresh(new_chat)

    logger.info(f"[Create Chat] Created chat {new_chat.id} for user {current_user.id}")

    return {
        "id": new_chat.id,
        "chat_id": new_chat.id,
        "room_id": new_chat.room_id,
        "name": new_chat.name,
        "created_at": new_chat.created_at.isoformat(),
    }

@api_router.get("/chats")
async def legacy_list_chats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all chats the user has access to (legacy compatibility).
    """
    user_rooms = (
        db.query(RoomMemberORM.room_id)
        .filter(RoomMemberORM.user_id == current_user.id)
        .distinct()
        .all()
    )
    room_ids = [r[0] for r in user_rooms]

    chats = (
        db.query(ChatInstanceORM)
        .filter(ChatInstanceORM.room_id.in_(room_ids))
        .order_by(ChatInstanceORM.last_message_at.desc())
        .all()
    )

    return {
        "chats": [
            {
                "id": chat.id,
                "chat_id": chat.id,
                "room_id": chat.room_id,
                "name": chat.name,
                "created_at": chat.created_at.isoformat() if chat.created_at else None,
                "last_message_at": chat.last_message_at.isoformat() if chat.last_message_at else None,
            }
            for chat in chats
        ]
    }

# ============================================================


# Auth shit


# ============================================================

from fastapi.encoders import jsonable_encoder

AUTH_COOKIE_NAME = "access_token"

oauth = OAuth()

google = oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

def set_auth_cookie(resp: JSONResponse, token: str) -> None:
    resp.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        max_age=60 * 60 * 24 * 7,
        path="/",
        domain=config.COOKIE_DOMAIN,
    )

def clear_auth_cookie(resp: Response):
    resp.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        domain=config.COOKIE_DOMAIN,
        samesite=config.COOKIE_SAMESITE,
        secure=config.COOKIE_SECURE,
    )


# ============================================================
# Waitlist Endpoints
# ============================================================

def save_waitlist_submission(data: dict) -> Optional[str]:
    """Persist submission to database. Returns submission id on success."""
    try:
        meta = data.get("metadata") or {}
        extras = {k: v for k, v in data.items() if k in {"company", "teamSize", "role", "problems"} and v}
        if extras:
            meta.update(extras)
        notes_val = data.get("notes") or data.get("problems")
        submission_id = str(uuid.uuid4())
        with SessionLocal() as db:
            submission = WaitlistSubmission(
                id=submission_id,
                name=data.get("name"),
                email=data.get("email"),
                notes=notes_val,
                source=data.get("source"),
                meta=meta or None,
            )
            db.add(submission)
            db.commit()
        logger.info(f"Waitlist submission saved: {data.get('email')}")
        return submission_id
    except Exception as e:
        logger.error(f"Error saving waitlist submission: {e}", exc_info=True)
        return None


@api_router.post("/waitlist")
async def submit_waitlist(submission: WaitlistSubmissionPayload):
    """Handle waitlist form submission from landing page"""
    try:
        # Add timestamp
        data = submission.dict()
        data['timestamp'] = datetime.now(timezone.utc).isoformat()

        # Save to file
        submission_id = save_waitlist_submission(data)
        if not submission_id:
            raise HTTPException(status_code=500, detail="Failed to save submission")

        return {
            "success": True,
            "message": "Application submitted successfully",
            "id": submission_id,
        }

    except Exception as e:
        logger.error(f"Waitlist submission error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/waitlist")
async def get_waitlist():
    """Get all waitlist submissions (no auth required for now - can add later)"""
    try:
        with SessionLocal() as db:
            rows = (
                db.query(WaitlistSubmission)
                .order_by(WaitlistSubmission.created_at.desc())
                .limit(500)
                .all()
            )

        submissions = [
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

        return {"submissions": submissions, "count": len(submissions)}

    except Exception as e:
        logger.error(f"Error fetching waitlist: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Auth Endpoints
# ============================================================

@api_router.post("/auth/register", response_model=UserOut)
def register(payload: CreateUserRequest, db: Session = Depends(get_db)):
    # Unique email
    exists = db.query(UserORM).filter(UserORM.email == payload.email).first()
    if exists:
        raise HTTPException(status_code=400, detail="Email already registered")

    role = payload.role
    user = UserORM(
        id=str(uuid.uuid4()),
        email=payload.email,
        name=payload.name or payload.email.split("@")[0],
        role=role,
        created_at=datetime.now(timezone.utc),
    )
    cred = UserCredentialORM(
        user_id=user.id,
        password_hash=hash_password(payload.password),
        created_at=datetime.now(timezone.utc),
    )

    db.add(user)
    db.add(cred)

    db.commit()
    db.refresh(user)

    # Auto-provision personal room + assistant chat so new users have data immediately
    try:
        personal_room = get_or_create_personal_room(user.id, db)
        get_or_create_personal_assistant_chat(user.id, db)
        logger.info(
            "[Signup] Provisioned personal room %s and assistant chat for user %s",
            personal_room.id,
            user.id,
        )
    except Exception as e:
        logger.warning("[Signup] Failed to provision defaults for %s: %s", user.email, e)

    token = create_access_token({"sub": user.id})

    # Serialize safely
    user_out = UserOut.model_validate(user)
    data = jsonable_encoder(user_out)

    resp = JSONResponse(content=data)
    set_auth_cookie(resp, token)
    return resp

@api_router.post("/auth/login")
def login(payload: AuthLoginRequest, db: Session = Depends(get_db)):
    user = db.query(UserORM).filter(UserORM.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    cred = db.get(UserCredentialORM, user.id)
    if not cred or not verify_password(payload.password, cred.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Auto-provision org for platform admins on login
    try:
        ensure_admin_org(db, user)
    except Exception:
        logger.exception("Failed to ensure admin org on login")

    token = create_access_token({"sub": user.id})
    resp = JSONResponse({"ok": True})
    set_auth_cookie(resp, token)
    return resp

@api_router.post("/auth/logout")
def logout():
    resp = JSONResponse({"ok": True})
    clear_auth_cookie(resp)
    return resp

@api_router.get("/auth/google/login")
async def google_login(request: StarletteRequest):
    # Explicitly set redirect URI to match Google Console configuration
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI") or f"{BACKEND_URL}/api/auth/google/callback"
    return await google.authorize_redirect(request, redirect_uri)

@api_router.get("/auth/google/callback")
async def google_callback(
    request: StarletteRequest,
    db: Session = Depends(get_db),
):
    token = await google.authorize_access_token(request)
    userinfo = token.get("userinfo")

    if not userinfo:
        raise HTTPException(status_code=400, detail="No user info returned by Google")

    email = userinfo["email"]
    name = userinfo.get("name") or email.split("@")[0]

    user = db.query(UserORM).filter(UserORM.email == email).first()
    if not user:
        user = UserORM(
            id=str(uuid.uuid4()),
            email=email,
            name=name,
            role=None,
            created_at=datetime.now(timezone.utc),
        )
        cred = UserCredentialORM(
            user_id=user.id,
            password_hash=hash_password(str(uuid.uuid4())),
            created_at=datetime.now(timezone.utc),
        )
        db.add(user)
        db.add(cred)
        db.commit()
        db.refresh(user)

    admin_emails = parse_admin_emails()
    admin_status = is_platform_admin_user(user, admin_emails)

    print("🔍 DEBUG - User after Google auth:")
    print(f"   Email: {user.email}")
    print(f"   Org ID: {getattr(user, 'org_id', None)}")
    print(f"   Permissions: {getattr(user, 'permissions', None)}")
    print(f"   Is Admin: {admin_status}")

    try:
        ensure_admin_org(db, user)
    except Exception:
        logger.exception("Failed to ensure admin org on Google callback")

    token_str = create_access_token({"sub": user.id})
    frontend_app_url = os.getenv("FRONTEND_APP_URL") or config.FRONTEND_APP_URL

    resp = RedirectResponse(url=frontend_app_url)
    set_auth_cookie(resp, token_str)
    return resp

@api_router.get("/debug/google")
def debug_google():
    return {
        "GOOGLE_REDIRECT_URI": os.getenv("GOOGLE_REDIRECT_URI"),
        "computed_redirect_uri": os.getenv("GOOGLE_REDIRECT_URI") or f"{BACKEND_URL}/api/auth/google/callback",
    }

def require_user(request: Request, db: Session) -> UserORM:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user

def user_to_dict(user: UserORM, org: OrganizationORM | None = None) -> dict:
    org_data = None
    if org is not None:
        org_data = {
            "id": org.id,
            "name": org.name,
        }

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "org": org_data,
    }

def get_or_create_org_for_user(db: Session, user: UserORM) -> OrganizationORM:
    """
    DEV / MVP behavior:
    - All users share the first organization in the database.
    - If none exists, create a 'Parallel Dev Org' and attach this user.
    - Uses the User.org / User.org_id side only (no Organization.users needed).
    """

    # 1) If user is already attached to an org, just return it
    if getattr(user, "org", None) is not None:
        return user.org

    # 2) See if any org already exists
    existing_org = db.query(OrganizationORM).first()
    if existing_org:
        # Attach user to existing org via the user side of the relationship
        if hasattr(user, "org"):
            user.org = existing_org
        elif hasattr(user, "org_id"):
            user.org_id = existing_org.id

        db.add(user)
        db.commit()
        db.refresh(user)
        return existing_org

    # 3) No orgs yet → create the first one
    org = OrganizationORM(
        id=str(uuid.uuid4()),
        name="Parallel Dev Org",
        owner_user_id=user.id,
        invite_code=secrets.token_urlsafe(12),
        created_at=datetime.now(timezone.utc),
    )
    db.add(org)
    db.commit()
    db.refresh(org)

    # Attach user to this new org
    if hasattr(user, "org"):
        user.org = org
    elif hasattr(user, "org_id"):
        user.org_id = org.id

    db.add(user)
    db.commit()
    db.refresh(user)

    return org

def generate_invite_code() -> str:
    return secrets.token_urlsafe(8)

def ensure_admin_org(db: Session, user: UserORM) -> OrganizationORM | None:
    admin_emails = parse_admin_emails()
    if not is_platform_admin_user(user, admin_emails):
        return None
    if not getattr(user, "is_platform_admin", False):
        user.is_platform_admin = True
    # If already has an org, just return it
    if getattr(user, "org_id", None):
        return db.query(OrganizationORM).filter(OrganizationORM.id == user.org_id).first()

    org = OrganizationORM(
        id=str(uuid.uuid4()),
        name=f"{user.name or user.email}'s Organization",
        invite_code=generate_invite_code(),
        owner_user_id=user.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(org)
    db.flush()  # get org.id

    # ensure admin permissions
    perms = (getattr(user, "permissions", None) or {}).copy()
    perms.update({"frontend": True, "backend": True})
    user.permissions = perms
    user.org_id = org.id
    db.add(user)

    team_room = RoomORM(
        id=str(uuid.uuid4()),
        org_id=org.id,
        name="team",
        project_summary="",
        memory_summary="",
        created_at=datetime.now(timezone.utc),
    )
    db.add(team_room)
    db.flush()

    membership = RoomMemberORM(
        id=str(uuid.uuid4()),
        room_id=team_room.id,
        user_id=user.id,
        role_in_room="owner",
    )
    db.add(membership)

    db.commit()
    db.refresh(user)
    db.refresh(org)
    return org

def _find_user_by_first_name(name: str, org_users: list[UserORM]) -> UserORM | None:
    if not name:
        return None
    target = name.strip().lower()
    for u in org_users:
        first_attr = getattr(u, "first_name", None)
        first_token = (first_attr or (u.name.split()[0] if (u.name or "").strip() else "")).strip().lower()
        if first_token == target:
            return u
    return None

@api_router.get("/me")
def read_me(current_user: User = Depends(get_current_user)):
    # PERFORMANCE FIX: Use current_user directly (already loaded by get_current_user)
    # No need to re-query the database
    needs_invite = current_user.org_id is None

    admin_emails = parse_admin_emails()
    is_platform_admin = is_platform_admin_user(current_user, admin_emails)

    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "org_id": current_user.org_id,
        "permissions": current_user.permissions,
        "needs_invite": needs_invite,
        "is_platform_admin": is_platform_admin
    }

@api_router.post("/org/join")
def join_organization(
    payload: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user(request, db)

    code = (payload or {}).get("invite_code")
    if not code:
        raise HTTPException(status_code=400, detail="invite_code is required")

    org = (
        db.query(OrganizationORM)
        .filter(OrganizationORM.invite_code == code)
        .first()
    )
    if not org:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    if getattr(current_user, "org_id", None):
        raise HTTPException(status_code=400, detail="Already in an organization")

    current_user.org_id = org.id

    user_count = db.query(UserORM).filter(UserORM.org_id == org.id).count()
    if user_count == 0:
        current_user.permissions = {"frontend": True, "backend": True}

    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    return {"org_id": org.id, "org_name": org.name}

@api_router.post("/activate", response_model=UserOut)
def activate_account(
    payload: ActivateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_current_user(request, db)

    # Set their role if provided (optional)
    if payload.role:
        if ROLE_OPTIONS and payload.role not in ROLE_OPTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Role must be one of: {', '.join(ROLE_OPTIONS)}",
            )
        user.role = payload.role
    
    # Mark as activated by setting a default role or flag
    # This ensures needs_invite becomes false
    if not user.role:
        user.role = "Member"  # Default role - just to pass the needs_invite check
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    print(f"✅ User activated: {user.email}, role: {user.role}")
    
    return user

def ensure_room_access(
    db: Session,
    user: UserORM,
    room: RoomORM,
    expected_label: str | None = None,
) -> RoomORM:
    """
    Ensure that the given room belongs to the same org as the user.
    - If room.org_id is NULL, attach it to the user's org.
    - If it belongs to a different org, forbid access.
    """

    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")

    org = get_or_create_org_for_user(db, user)

    # Attach unowned room to this org
    if room.org_id is None:
        room.org_id = org.id
        db.add(room)
        db.commit()
        db.refresh(room)

    # Cross-org access is not allowed
    if room.org_id != org.id:
        logger.warning(
            "User %s tried to access room %s belonging to org %s (user org %s)",
            user.id,
            room.id,
            room.org_id,
            org.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Room belongs to a different organization.",
        )

    # Optional: log name mismatch, but don't fail
    if expected_label and room.name:
        if expected_label.lower() not in room.name.lower():
            logger.info(
                "Room name mismatch for user %s: expected label '%s', actual name '%s'",
                user.id,
                expected_label,
                room.name,
            )

    return room

@api_router.post("/rooms", response_model=CreateRoomResponse)
def create_room(payload: CreateRoomRequest, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    org = get_or_create_org_for_user(db, user)

    room = RoomORM(
        id=str(uuid.uuid4()),
        name=payload.room_name,
        org_id=org.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(room)
    db.flush()  # get room.id without full commit

    membership = RoomMemberORM(
        id=str(uuid.uuid4()),
        room_id=room.id,
        user_id=user.id,
        role_in_room="creator",
    )
    db.add(membership)

    default_chat = ChatInstanceORM(
        id=str(uuid.uuid4()),
        room_id=room.id,
        name="General",
        created_by_user_id=user.id,
        created_at=datetime.now(timezone.utc),
        last_message_at=None,
    )
    db.add(default_chat)

    db.commit()
    db.refresh(room)

    return {
        "room_id": room.id,
        "room_name": room.name,
        "id": room.id,
        "name": room.name,
        "default_chat_id": default_chat.id,
    }

@api_router.get("/rooms/{room_id}", response_model=RoomResponse)
def get_room(
    room_id: str,
    request: Request,
    chat_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    user = require_current_user(request, db)
    room = db.get(RoomORM, room_id)
    room = ensure_room_access(db, user, room)

    chat_obj = None
    if chat_id:
        chat_obj, _ = require_chat_access(db, user, chat_id)
        if chat_obj.room_id != room.id:
            raise HTTPException(status_code=404, detail="Chat not found in this room")

    return room_to_response(
        db,
        room,
        chat=chat_obj,
        chat_id=chat_id,
        created_by_user_id=user.id,
    )

@api_router.get("/rooms/{room_id}/chats", response_model=List[ChatInstanceOut])
def list_room_chats(room_id: str, request: Request, db: Session = Depends(get_db)):
    print(f"\n[LIST CHATS] Room ID: {room_id}")
    user = require_current_user(request, db)
    room = db.get(RoomORM, room_id)
    room = ensure_room_access(db, user, room)
    membership = (
        db.query(RoomMemberORM)
        .filter(RoomMemberORM.room_id == room.id, RoomMemberORM.user_id == user.id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this room")

    # Ensure there's at least one chat (General) available
    get_default_chat_instance(db, room, created_by_user_id=user.id)

    chats = (
        db.query(ChatInstanceORM)
        .filter(ChatInstanceORM.room_id == room.id) # A
        .order_by(
            ChatInstanceORM.last_message_at.desc().nullslast(),
            ChatInstanceORM.created_at.desc(),
        )
        .all()
    )

    # PERFORMANCE FIX: Use batch loading to eliminate N+1 queries for message counts
    chats_out = to_chat_instance_out_batch(db, chats)
    print(f"[LIST CHATS] Returning {len(chats_out)} chats")
    for c in chats_out:
        try:
            print(f"  - {c.dict()}")
        except Exception:
            print(f"  - {c}")
    return chats_out

@api_router.post("/rooms/{room_id}/chats", response_model=ChatInstanceOut)
def create_chat_instance(
    room_id: str,
    payload: CreateChatInstanceRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    print("\n" + "=" * 80)
    print(f"[CREATE CHAT] Starting chat creation")
    print(f"[CREATE CHAT] Room ID: {room_id}")
    print(f"[CREATE CHAT] Payload: {payload}")
    print(f"[CREATE CHAT] Payload name: '{payload.name}'")
    print("=" * 80 + "\n")

    user = require_current_user(request, db)
    print(f"[CREATE CHAT] User authenticated: {user.id} ({user.name})")

    room = db.get(RoomORM, room_id)
    print(f"[CREATE CHAT] Room found: {room.id if room else 'None'}")

    room = ensure_room_access(db, user, room)
    print(f"[CREATE CHAT] Room access verified")
    membership = (
        db.query(RoomMemberORM)
        .filter(RoomMemberORM.room_id == room.id, RoomMemberORM.user_id == user.id)
        .first()
    )
    if not membership:
        print(f"[CREATE CHAT] Membership check: False")
        print(f"[CREATE CHAT] ERROR: User not a member of room")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this room")
    else:
        print(f"[CREATE CHAT] Membership check: True")

    name = (payload.name or "").strip()
    print(f"[CREATE CHAT] Trimmed name: '{name}'")
    if not name:
        print(f"[CREATE CHAT] ERROR: Empty chat name")
        raise HTTPException(status_code=400, detail="Chat name is required")

    existing = (
        db.query(ChatInstanceORM)
        .filter(
            ChatInstanceORM.room_id == room.id,
            func.lower(ChatInstanceORM.name) == name.lower(),
        )
        .first()
    )
    print(f"[CREATE CHAT] Duplicate check: {existing is not None}")
    if existing:
        print(f"[CREATE CHAT] ERROR: Duplicate chat name")
        raise HTTPException(status_code=400, detail="A chat with that name already exists in this room")

    chat_id = str(uuid.uuid4())
    print(f"[CREATE CHAT] Generated chat ID: {chat_id}")

    chat = ChatInstanceORM(
        id=chat_id,
        room_id=room.id,
        name=name,
        created_by_user_id=user.id,
        created_at=datetime.now(timezone.utc),
        last_message_at=None,
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    # Create welcome message
    welcome_msg = MessageORM(
        id=str(uuid.uuid4()),
        chat_instance_id=chat.id,
        room_id=room_id,
        sender_id="system",
        sender_name="Parallel OS",
        role="assistant",
        content="Hey! How can I help you today?",
        user_id=user.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(welcome_msg)
    chat.last_message_at = welcome_msg.created_at
    db.commit()
    db.refresh(chat)
    result = to_chat_instance_out(db, chat)

    return result

@api_router.delete("/chats/{chat_id}", status_code=204)
def delete_chat_instance(
    chat_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_current_user(request, db)
    chat = db.get(ChatInstanceORM, chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    room = db.get(RoomORM, chat.room_id)
    room = ensure_room_access(db, user, room)

    remaining = (
        db.query(ChatInstanceORM)
        .filter(ChatInstanceORM.room_id == room.id, ChatInstanceORM.id != chat.id)
        .count()
    )
    if remaining == 0:
        raise HTTPException(status_code=400, detail="Cannot delete the last chat in a room")

    db.query(MessageORM).filter(MessageORM.chat_instance_id == chat.id).delete()
    db.delete(chat)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)

@api_router.get("/chats/{chat_id}/messages", response_model=ChatMessagesResponse)
def get_chat_messages(
    chat_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_current_user(request, db)
    chat = db.query(ChatInstanceORM).filter(ChatInstanceORM.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    membership = (
        db.query(RoomMemberORM)
        .filter(RoomMemberORM.room_id == chat.room_id, RoomMemberORM.user_id == user.id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this room")

    room = db.get(RoomORM, chat.room_id)

    messages = (
        db.query(MessageORM)
        .filter(MessageORM.chat_instance_id == chat.id)
        .order_by(MessageORM.created_at.asc())
        .all()
    )

    # PERFORMANCE FIX: Use batch loading to eliminate N+1 queries
    return ChatMessagesResponse(
        chat=to_chat_instance_out(db, chat),
        messages=to_message_out_batch(messages, db),
    )

@api_router.post("/chats/{chat_id}/messages", response_model=ChatMessagesResponse)
async def post_chat_message(
    chat_id: str,
    payload: AskModeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_current_user(request, db)
    chat, room = require_chat_access(db, user, chat_id)

    include_preview = _should_include_context_preview(request, payload.dict(exclude_none=True))
    logger.info(
        "[ChatSendRoute] path=%s handler=post_chat_message chat_id=%s user_id=%s streaming=false include_context_preview=%s",
        request.url.path,
        chat_id,
        user.id,
        include_preview,
    )

    _, _, context_preview = await process_chat_message(db, room, chat, user, payload, include_preview=include_preview, request=request)
    db.refresh(chat)

    messages = (
        db.query(MessageORM)
        .filter(MessageORM.chat_instance_id == chat.id)
        .order_by(MessageORM.created_at.asc())
        .all()
    )

    # PERFORMANCE FIX: Use batch loading to eliminate N+1 queries
    return ChatMessagesResponse(
        chat=to_chat_instance_out(db, chat),
        messages=to_message_out_batch(messages, db),
        context_preview=context_preview,
    )

@api_router.post("/chats/{chat_id}/ask", response_model=ChatMessagesResponse)
async def ask_in_chat(
    chat_id: str,
    request: Request,
    payload: Optional[ChatAskRequest] = Body(None),
    content: Optional[str] = Form(None),
    mode: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    user_name: Optional[str] = Form(None),
    file_count: Optional[int] = Form(0),
    file_0: Optional[UploadFile] = File(None),
    file_1: Optional[UploadFile] = File(None),
    file_2: Optional[UploadFile] = File(None),
    file_3: Optional[UploadFile] = File(None),
    file_4: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """
    Send a message to a specific chat instance. Supports JSON or multipart with up to 5 files.
    """
    user = require_current_user(request, db)
    chat, room = require_chat_access(db, user, chat_id)
    body_data: Dict[str, Any] = {}

    # Collect uploaded files from form inputs; limit to 5 for now
    uploaded_files = []
    max_files = 5
    requested_files = max(0, min(file_count or 0, max_files))
    for i in range(max_files):
        f = locals().get(f"file_{i}")
        if f:
            uploaded_files.append(f)
    # In case file_count is missing but files were provided
    if not requested_files:
        uploaded_files = [f for f in [file_0, file_1, file_2, file_3, file_4] if f]
    logger.info(f"[Chat Ask] Received {len(uploaded_files)} files for chat {chat_id}")

    # Parse incoming content (form first, then JSON)
    message_content = ""
    # Resolve incoming content + user metadata from form or JSON
    request_mode = "self"
    message_content = ""
    if content is not None or mode is not None or uploaded_files:
        message_content = (content or "").strip()
        request_mode = (mode or "self").strip() or "self"
    else:
        if payload:
            body_data = payload.dict(exclude_none=True)
        else:
            try:
                body_data = await request.json()
            except Exception:
                body_data = {}
        message_content = (body_data.get("message") or body_data.get("content") or "").strip()
        request_mode = (body_data.get("mode") or "self").strip() or "self"

    file_text_blocks: List[str] = []
    for f in uploaded_files:
        try:
            raw = await f.read()
            logger.info(f"[File Upload] Processing {f.filename} ({f.content_type}) size={len(raw)}")

            if f.content_type and f.content_type.startswith("image/"):
                b64 = base64.b64encode(raw).decode("utf-8")
                preview = b64[:200] + ("..." if len(b64) > 200 else "")
                media_type = f.content_type.replace("image/jpg", "image/jpeg")
                file_text_blocks.append(
                    f"[Image uploaded: {f.filename} ({media_type}) | base64 preview: {preview}]"
                )
            elif f.content_type == "application/pdf":
                file_text_blocks.append(f"[PDF uploaded: {f.filename}]")
            else:
                try:
                    decoded = raw.decode("utf-8")
                    snippet = decoded[:8000]
                    file_text_blocks.append(f"File: {f.filename}\n\n```\n{snippet}\n```")
                except UnicodeDecodeError:
                    file_text_blocks.append(f"[Binary file uploaded: {f.filename} ({f.content_type})]")

            logger.info(f"[File Upload] Processed {f.filename} ({f.content_type})")
        except Exception as e:
            logger.error(f"[File Upload] Error processing {f.filename}: {e}", exc_info=True)

    if file_text_blocks:
        logger.info(f"[File Upload] User {user.id} uploaded {len(file_text_blocks)} files")
        if message_content:
            message_content = f"{message_content}\n\n" + "\n\n".join(file_text_blocks)
        else:
            message_content = "\n\n".join(file_text_blocks)

    if not message_content.strip():
        raise HTTPException(status_code=400, detail="Message content is required")

    ask_payload = AskModeRequest(
        user_id=user.id,
        user_name=user.name,
        content=message_content,
        mode=request_mode,
        include_context_preview=_should_include_context_preview(request, body_data),
    )

    include_preview = _should_include_context_preview(request, body_data)
    logger.info(
        "[ChatSendRoute] path=%s handler=ask_in_chat chat_id=%s user_id=%s streaming=false include_context_preview=%s",
        request.url.path,
        chat_id,
        user.id,
        include_preview,
    )

    _, _, context_preview = await process_chat_message(db, room, chat, user, ask_payload, include_preview=include_preview, request=request)
    db.refresh(chat)

    messages = (
        db.query(MessageORM)
        .filter(MessageORM.chat_instance_id == chat.id)
        .order_by(MessageORM.created_at.asc())
        .all()
    )

    # PERFORMANCE FIX: Use batch loading to eliminate N+1 queries
    return ChatMessagesResponse(
        chat=to_chat_instance_out(db, chat),
        messages=to_message_out_batch(messages, db),
        context_preview=context_preview,
    )


@api_router.post("/chats/{chat_id}/dispatch", response_model=V1DispatchResponse)
def dispatch_chat_message_legacy(
    chat_id: str,
    payload: V1DispatchRequest,
    current_user: UserORM = Depends(v1_get_current_user),
    db: Session = Depends(v1_get_db),
    _: None = Depends(v1_require_scope("chats:write")),
):
    """
    Legacy alias for /api/v1/chats/{chat_id}/dispatch to preserve backwards compatibility.
    """
    return v1_dispatch_chat_message(
        chat_id=chat_id,
        payload=payload,
        current_user=current_user,
        db=db,
        _=_,
    )

CANONICAL_ROOMS = {
    "engineering": "Engineering Room",
    "design": "Design Room",
    "team": "Team Room",
    "product": "Product Room",
}

@api_router.get("/team/activity")
def get_team_activity(request: Request, db: Session = Depends(get_db)):
    """
    Get team activity with cached statuses (no LLM calls on every request).
    Now uses intelligent Activity Manager with semantic similarity.
    """
    from models import UserStatus
    from datetime import timedelta

    user = require_user(request, db)
    logger.info(f"[Team Activity] User {user.id[:8]} fetching team activity")

    try:
        # Get team members (same logic as before)
        if not user.role:
            teammates = db.query(UserORM).limit(20).all()
        else:
            teammates = (
                db.query(UserORM)
                .filter(UserORM.role == user.role)
                .all()
            )

        logger.info(f"[Team Activity] Found {len(teammates)} teammates for user {user.id[:8]}")

        members = []
        for u in teammates:
            try:
                # Get user's current status (CACHED - no LLM call!)
                user_status = db.query(UserStatus).filter(
                    UserStatus.user_id == u.id
                ).first()

                if user_status:
                    # Use cached status from Activity Manager
                    room = None
                    if user_status.room_id:
                        room = db.query(RoomORM).get(user_status.room_id)

                    # Apply summarization to cached status
                    summarized_status = summarize_activity_message(user_status.current_status or "")

                    last_activity = {
                        "room_name": room.name if room else "Active",
                        "message": summarized_status,  # ✅ Summarized for readability
                        "at": user_status.last_updated.isoformat()
                    }
                else:
                    # Fallback to old behavior for users without status yet
                    since = datetime.now(timezone.utc) - timedelta(hours=24)
                    recent_msg = db.query(MessageORM).filter(
                        MessageORM.user_id == u.id,
                        MessageORM.created_at >= since
                    ).order_by(desc(MessageORM.created_at)).first()

                    if recent_msg:
                        room = db.query(RoomORM).get(recent_msg.room_id)
                        # Use new summarization function instead of cached summary
                        message_preview = summarize_activity_message(recent_msg.content or "")
                        last_activity = {
                            "room_name": room.name if room else "Unknown",
                            "message": message_preview,
                            "at": recent_msg.created_at.isoformat()
                        }
                    else:
                        last_activity = None

                members.append({
                    "id": u.id,
                    "name": u.name,
                    "role": u.role,
                    "last_activity": last_activity,
                })
            except Exception as member_err:
                logger.warning(f"[Team Activity] ⚠️  Error processing user {u.id[:8]}: {member_err}")
                # Include user but with no activity data
                members.append({
                    "id": u.id,
                    "name": u.name,
                    "role": u.role,
                    "last_activity": None,
                })

        # Sort by most recent activity
        members.sort(
            key=lambda m: (m["last_activity"]["at"] if m["last_activity"] else ""),
            reverse=True,
        )

        logger.info(f"[Team Activity] ✅ Returning {len(members)} members for user {user.id[:8]}")

        return {"members": members}

    except Exception as e:
        logger.error(f"[Team Activity] ❌ Error fetching team activity for user {user.id[:8]}: {e}", exc_info=True)
        # Graceful degradation - return empty list
        return {"members": []}


@api_router.get("/activity/history")
def get_activity_history(
    request: Request,
    user_id: Optional[str] = None,
    days: int = 7,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """
    Get activity history with AI summaries.
    Returns persistent log of distinct activities (deduplicated by similarity).
    """
    from models import UserAction

    current_user = require_user(request, db)
    target_user_id = user_id or current_user.id

    logger.info(f"[Activity History] Fetching for user {target_user_id[:8]}, days={days}, limit={limit}")

    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)

        activities = db.query(UserAction).filter(
            UserAction.user_id == target_user_id,
            UserAction.timestamp >= since,
            UserAction.activity_summary.isnot(None)  # Only activities with summaries
        ).order_by(desc(UserAction.timestamp)).limit(limit).all()

        logger.info(f"[Activity History] ✅ Found {len(activities)} activities for user {target_user_id[:8]}")

        return {
            "activities": [
                {
                    "id": act.id,
                    "user_id": act.user_id,
                    "summary": act.activity_summary,
                    "tool": act.tool,
                    "action_type": act.action_type,
                    "timestamp": act.timestamp.isoformat(),
                    "room_id": act.room_id,
                    "is_status_change": act.is_status_change,
                    "similarity_to_status": act.similarity_to_status,
                    "similarity_to_previous": act.similarity_to_previous
                }
                for act in activities
            ],
            "total": len(activities),
            "days": days
        }
    except Exception as e:
        logger.error(f"[Activity History] ❌ Error fetching activities for user {target_user_id[:8]}: {e}", exc_info=True)
        # Graceful degradation - return empty list instead of 500 error
        return {
            "activities": [],
            "total": 0,
            "days": days,
            "error": "Failed to load activity history"
        }


def get_or_create_team_room_for_org(db: Session, org: OrganizationORM) -> RoomORM:
    """
    MVP: one canonical Team room per organization.
    If none exists yet, create it.
    """

    # 1) Try to find existing Team room
    room = (
        db.query(RoomORM)
        .filter(RoomORM.org_id == org.id, RoomORM.name == "Team")
        .first()
    )
    if room:
        return room

    # 2) Create a new Team room
    room = RoomORM(
        id=str(uuid.uuid4()),
        org_id=org.id,
        name="Team",
        project_summary=None,
        memory_summary=None,
        summary_version=0,
        summary_updated_at=None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room

@api_router.get("/rooms/team/team", response_model=RoomResponse)
def get_team_room(
    request: Request,
    db: Session = Depends(get_db),
):
    # 1) Make sure user is logged in
    user = require_current_user(request, db)

    # 2) Ensure user is in an org (shared dev org helper you already have)
    org = get_or_create_org_for_user(db, user)

    # 3) Find-or-create the Team room for this org
    room = get_or_create_team_room_for_org(db, org)

    # 4) Enforce org access
    ensure_room_access(db, user, room, expected_label="Team")

    # 5) Return the standard room response
    return room_to_response(db, room)

@api_router.get("/rooms/team/{team_label}")
def get_or_create_team_room(
    team_label: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Return (or create) the team room for this user.

    - If team_label is "team" or empty, use the user's own role.
    - Otherwise, treat team_label as a specific team name.
    - (Optional) we can later re-add a strict guard to prevent cross-team access.
    """
    user = require_user(request, db)
    org = get_or_create_org_for_user(db, user)

    raw_label = (team_label or "").strip()

    # "team" is just a placeholder meaning "my team"
    if not raw_label or raw_label.lower() == "team":
        label = user.role or "Team"
    else:
        label = raw_label

    key = (label or "").lower()

    # ❌ REMOVE the hard 403 that blocked you:
    # if user.role and key != user.role.lower():
    #     raise HTTPException(403, "You can only access your own team room for now.")

    room_name = CANONICAL_ROOMS.get(key, f"{label.title()} Room")

    room = (
        db.query(RoomORM)
        .filter(
            RoomORM.org_id == org.id,
            func.lower(RoomORM.name) == func.lower(room_name),
        )
        .first()
    )

    if not room:
        room = RoomORM(
            id=str(uuid.uuid4()),
            name=room_name,
            org_id=org.id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(room)
        db.commit()
        db.refresh(room)

    return {"room_id": room.id, "room_name": room.name}

@api_router.get("/health")
def health():
    return {"ok": True}

@api_router.get("/llm_health")
def llm_health():
    provider = "fireworks" if config.LLM_PROVIDER == "fireworks" else "openai"
    client = openai_client
    if not client:
        raise HTTPException(status_code=500, detail="LLM not configured. Set OPENAI_API_KEY or FIREWORKS_API_KEY.")
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a health check responder."},
                {"role": "user", "content": "Reply with a single word: ok"},
            ],
            max_tokens=5,
            temperature=0,
        )
        sample = response.choices[0].message.content.strip() if response.choices else ""
        return {"provider": provider, "model": OPENAI_MODEL, "ok": True, "sample": sample}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LLM health check failed: {exc}")

SUBSCRIBERS = []   # list[(queue, filters {room_id,user_id})]

async def event_generator(filters: Dict):
    queue: asyncio.Queue = asyncio.Queue()
    SUBSCRIBERS.append((queue, filters))
    try:
        while True:
            payload = await queue.get()
            # room filter
            if filters.get("room_id") and payload.get("room_id") != filters.get("room_id"):
                continue
            # user filter
            if filters.get("user_id") and payload.get("user_id") != filters.get("user_id"):
                continue
            yield f"data: {json.dumps(payload)}\n\n"
    finally:
        if (queue, filters) in SUBSCRIBERS:
            SUBSCRIBERS.remove((queue, filters))

def publish_event(payload: Dict):
    for queue, filters in list(SUBSCRIBERS):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass

@api_router.get("/events")
async def events(room_id: Optional[str] = None, user_id: Optional[str] = None):
    """
    SSE stream filtered by room
    """
    filters = {"room_id": room_id, "user_id": user_id}
    return StreamingResponse(event_generator(filters), media_type="text/event-stream")

def publish_status(room_id: str, step: str, meta: Optional[Dict] = None):
    publish_event({
        "type": "status",
        "room_id": room_id,
        "step": step,
        "meta": meta or {},
        "ts": datetime.now(timezone.utc).isoformat(),
    })

def publish_error(room_id: str, message: str, meta: Optional[Dict] = None):
    publish_event({
        "type": "error",
        "room_id": room_id,
        "message": message,
        "meta": meta or {},
        "ts": datetime.now(timezone.utc).isoformat(),
    })

@api_router.get("/users/{user_id}/inbox", response_model=List[InboxTaskOut])
def list_inbox(user_id: str, request: Request, db: Session = Depends(get_db)):
    me = require_user(request, db)

    if me.id != user_id:
        raise HTTPException(403, "Forbidden")

    tasks = (
        db.query(InboxTaskORM)
        .filter(InboxTaskORM.user_id == user_id)
        .order_by(InboxTaskORM.created_at.desc())
        .all()
    )
    return tasks

@api_router.post("/users/{user_id}/inbox", response_model=InboxTaskOut)
def add_inbox(user_id: str, payload: InboxCreateRequest, request: Request, db: Session = Depends(get_db)):
    me = require_user(request, db)
    if me.id != user_id:
        raise HTTPException(403, "Forbidden")

    task = InboxTaskORM(
        id=str(uuid.uuid4()),
        user_id=user_id,
        content=payload.content,
        room_id=payload.room_id,
        source_message_id=payload.source_message_id,
        priority=payload.priority,
        tags=payload.tags,
        pinned=payload.pinned,
        status="open",
        created_at=datetime.now(timezone.utc),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task

@api_router.patch("/users/{user_id}/inbox/{task_id}", response_model=InboxTaskOut)
def update_inbox(user_id: str, task_id: str, payload: InboxUpdateRequest, request: Request, db: Session = Depends(get_db)):
    me = require_user(request, db)
    if me.id != user_id:
        raise HTTPException(403, "Forbidden")

    task = db.get(InboxTaskORM, task_id)
    if not task or task.user_id != user_id:
        raise HTTPException(404, "Task not found")

    task.status = payload.status
    task.priority = payload.priority or task.priority
    if payload.pinned is not None:
        task.pinned = payload.pinned

    db.add(task)
    db.commit()
    db.refresh(task)
    return task

@api_router.get("/users/{user_id}/notifications", response_model=List[NotificationOut])
def list_notifications(user_id: str, request: Request, db: Session = Depends(get_db)):
    me = require_user(request, db)

    if me.id != user_id:
        raise HTTPException(403, "Forbidden")

    logger.info("[DEPRECATED] notifications endpoint used path=/api/users/%s/notifications user_id=%s", user_id, me.id)

    envelope = v1_notifications._build_notifications_envelope(db, me.id, limit=50, unread_only=False)
    # Return just notifications list to match legacy shape for this route
    return [NotificationOut(**n) if isinstance(n, dict) else n for n in envelope.get("notifications", [])]

@api_router.post("/users/{user_id}/notifications", response_model=NotificationOut)
def create_notification(user_id: str, payload: NotificationCreate, request: Request, db: Session = Depends(get_db)):
    me = require_user(request, db)

    notif = create_notification_safe(
        db,
        user_id=user_id,
        notif_type=payload.type or "task",
        title=payload.title,
        message=payload.message or payload.title,
        task_id=payload.task_id,
    )
    if not notif:
        raise HTTPException(status_code=400, detail="Failed to create notification")
    db.commit()
    db.refresh(notif)
    return notif


@api_router.get("/notifications/unread-count")
async def get_unread_notification_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger.info("[DEPRECATED] notifications endpoint used path=/api/notifications/unread-count user_id=%s", current_user.id)
    return {"count": v1_notifications._get_unread_count(db, current_user.id)}


@api_router.post("/notifications/{notification_id}/mark-read")
async def mark_notification_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger.info("[DEPRECATED] notifications endpoint used path=/api/notifications/%s/mark-read user_id=%s", notification_id, current_user.id)
    v1_notifications._mark_one_read(db, current_user.id, notification_id)
    return {"status": "marked_read"}


@api_router.post("/notifications/mark-all-read")
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark all notifications as read for the current user"""
    logger.info("[DEPRECATED] notifications endpoint used path=/api/notifications/mark-all-read user_id=%s", current_user.id)
    updated_count = v1_notifications._mark_all_read(db, current_user.id)
    return {"status": "success", "marked_read": updated_count}


@api_router.delete("/notifications/{notification_id}")
async def delete_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a specific notification"""
    logger.info("[DEPRECATED] notifications endpoint used path=/api/notifications/%s [DELETE] user_id=%s", notification_id, current_user.id)
    notif = (
        db.query(NotificationORM)
        .filter_by(id=notification_id, user_id=current_user.id)
        .first()
    )
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    db.delete(notif)
    db.commit()
    return {"status": "deleted", "id": notification_id}


@api_router.get("/notifications")
async def get_notifications(
    limit: int = 50,
    unread_only: bool = False,
    severity: str = None,  # 'urgent' or 'normal'
    source_type: str = None,  # 'conflict_file', 'conflict_semantic', etc.
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get user's notifications with optional filtering.

    Query params:
    - limit: Max notifications to return (default 50)
    - unread_only: Only return unread notifications
    - severity: Filter by 'urgent' or 'normal'
    - source_type: Filter by source type ('conflict_file', 'conflict_semantic', etc.)
    """
    logger.info("[DEPRECATED] notifications endpoint used path=/api/notifications user_id=%s", current_user.id)

    # Reuse v1 envelope then apply legacy filters locally to avoid drift
    envelope = v1_notifications._build_notifications_envelope(
        db, current_user.id, limit=limit, unread_only=unread_only
    )

    notifications = envelope.get("notifications", [])
    if severity:
        notifications = [n for n in notifications if n.get("severity") == severity]
    if source_type:
        notifications = [n for n in notifications if n.get("source_type") == source_type]

    return {
        "notifications": [
            {
                "id": n.get("id"),
                "type": n.get("type"),
                "severity": n.get("severity", "normal"),
                "title": n.get("title"),
                "message": n.get("message"),
                "data": n.get("data"),
                "read": n.get("read"),
                "source_type": n.get("source_type"),
                "created_at": n.get("created_at").isoformat() if n.get("created_at") else None,
            }
            for n in notifications
        ],
        "total": envelope.get("total", 0),
        "urgent_count": envelope.get("urgent_count", 0),
    }


@api_router.get("/team/members")
async def get_team_members(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all members in user's organization for @mention autocomplete"""
    members = (
        db.query(UserORM)
        .filter(UserORM.org_id == current_user.org_id, UserORM.id != current_user.id)
        .all()
    )
    return {
        "members": [
            {
                "id": m.id,
                "name": m.name or (m.email.split("@")[0] if m.email else ""),
                "email": m.email,
            }
            for m in members
        ]
    }


@api_router.get("/debug/user-notifications/{user_id}")
async def debug_notifications(user_id: str, db: Session = Depends(get_db)):
    """See all notifications for a user"""
    notifications = (
        db.query(NotificationORM)
        .filter(NotificationORM.user_id == user_id)
        .order_by(NotificationORM.created_at.desc())
        .all()
    )
    return {
        "user_id": user_id,
        "total": len(notifications),
        "unread": sum(1 for n in notifications if not n.is_read),
        "notifications": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "message": n.message,
                "data": n.data,
                "read": n.is_read,
                "created": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ],
    }


@api_router.get("/debug/user-timeline/{user_id}")
async def debug_timeline(user_id: str, db: Session = Depends(get_db)):
    """See user's full timeline"""
    canon = get_or_create_canonical_plan(user_id, db)
    timeline = canon.approved_timeline or {}
    counts = {}
    for timeframe in ["today", "this_week", "this_month"]:
        counts[timeframe] = sum(
            len(tasks) for tasks in timeline.get(timeframe, {}).values()
        )

    return {
        "user_id": user_id,
        "task_counts": counts,
        "timeline": timeline,
    }


@api_router.get("/activity/feed")
async def get_activity_feed(
    limit: int = 50,
    relevant_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get team activity feed showing recent task completions.
    """
    # Get all users in the same org
    org_users = db.query(UserORM).filter_by(org_id=current_user.org_id).all()
    user_ids = [u.id for u in org_users]

    activities = []

    recent_completions = (
        db.query(CompletedBriefItem)
        .filter(
            CompletedBriefItem.user_id.in_(user_ids),
            CompletedBriefItem.completed_at >= datetime.now(timezone.utc) - timedelta(days=7),
        )
        .order_by(CompletedBriefItem.completed_at.desc())
        .limit(limit * 2)
        .all()
    )

    for completion in recent_completions:
        user = db.query(UserORM).filter_by(id=completion.user_id).first()
        if not user:
            continue

        item_data = completion.raw_item or {}
        title = item_data.get("title") or completion.item_title or "Untitled task"
        description = item_data.get("description") or item_data.get("detail") or completion.item_description or ""

        search_text = f"{title} {description}".lower()
        current_user_name = (current_user.name or "").lower()
        current_user_email_prefix = (current_user.email.split("@")[0] if current_user.email else "").lower()

        is_relevant = (
            completion.user_id == current_user.id
            or f"@{current_user_name}" in search_text
            or f"@{current_user_email_prefix}" in search_text
            or (current_user_name and current_user_name in search_text)
        )

        if relevant_only and not is_relevant:
            continue

        activities.append(
            {
                "id": f"completion-{completion.id}",
                "type": "task_completed" if completion.action == "completed" else "task_deleted",
                "user_name": user.name or user.email,
                "user_id": completion.user_id,
                "title": title,
                "description": description[:100] if description else None,
                "timestamp": completion.completed_at.isoformat() if completion.completed_at else None,
                "is_relevant": is_relevant,
            }
        )

    activities = activities[:limit]

    logger.info(f"[ACTIVITY FEED] User {current_user.id}: {len(activities)} activities (relevant_only={relevant_only})")

    return {
        "activities": activities,
        "total_count": len(activities),
        "filtered": relevant_only,
    }

# -----------------------------
# GitHub IDE Mock Endpoints
# -----------------------------
@api_router.get("/github/status")
def github_status():
    return {
        "connected": False,
        "repo_name": None,
        "repo_owner": None,
        "repo_url": None,
    }

@api_router.get("/github/repo/files")
def github_list_files(path: str = "", request: Request = None):
    require_user(request, SessionLocal())
    path = path.strip()
    files = []
    if not path:
        files = GITHUB_MOCK_FILES
    else:
        files = [f for f in GITHUB_MOCK_FILES if f["path"].startswith(path)]
    return {"files": files}

@api_router.get("/github/repo/file")
def github_get_file(path: str, request: Request = None):
    require_user(request, SessionLocal())
    content = GITHUB_MOCK_CONTENT.get(path, f"# {path}\n\nMock file. Connect GitHub for real content.\n")
    return {"path": path, "content": content, "sha": None}

# -----------------------------
# Team / Tasks management
# -----------------------------
@api_router.get("/team")
def get_team(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # PERFORMANCE FIX: Filter by org_id to avoid loading all users
    query = db.query(UserORM)

    # Only load users from the same org (if user has org)
    if current_user.org_id:
        query = query.filter(UserORM.org_id == current_user.org_id)

    # Add safety limit to prevent excessive memory usage
    users = query.limit(500).all()

    members = []
    for u in users:
        members.append({
            "id": u.id,
            "name": u.name,
            "roles": [u.role] if u.role else [],
            "status": "active",
        })
    return {"members": members}

@api_router.patch("/users/{user_id}/role", response_model=UserOut)
def update_user_role(user_id: str, payload: RoleUpdate, request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    user = db.get(UserORM, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if ROLE_OPTIONS and payload.role not in ROLE_OPTIONS:
        raise HTTPException(400, f"Role must be one of: {', '.join(ROLE_OPTIONS)}")
    user.role = payload.role
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def require_platform_admin(user: UserORM) -> None:
    admin_emails = parse_admin_emails()
    email_normalized = normalize_email(getattr(user, "email", None))
    allowlist_match = bool(email_normalized and email_normalized in admin_emails)
    if not is_platform_admin_user(user, admin_emails):
        logger.warning(
            "Admin access denied",
            extra={
                "user_id": getattr(user, "id", None),
                "email": user.email,
                "is_platform_admin": getattr(user, "is_platform_admin", False),
                "allowlist_match": allowlist_match,
            },
        )
        raise HTTPException(status_code=403, detail="Admin access required")

@api_router.get("/admin/orgs")
def list_organizations(
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = require_user(request, db)
    require_platform_admin(current_user)

    orgs = db.query(OrganizationORM).all()

    results = []
    for org in orgs:
        owner_email = None
        if org.owner_user_id:
            owner = db.query(UserORM).filter(UserORM.id == org.owner_user_id).first()
            owner_email = owner.email if owner else None

        results.append(
            {
                "id": org.id,
                "name": org.name,
                "owner_user_id": org.owner_user_id,
                "owner_email": owner_email,
                "invite_code": org.invite_code,
                "created_at": org.created_at.isoformat() if org.created_at else None,
            }
        )

    return results

@api_router.post("/admin/orgs/create")
def create_organization(
    payload: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user(request, db)
    require_platform_admin(current_user)

    name = (payload or {}).get("name") or "New Organization"

    # generate unique invite code
    invite_code = None
    attempts = 0
    while not invite_code:
        candidate = secrets.token_urlsafe(8)
        exists = (
            db.query(OrganizationORM)
            .filter(OrganizationORM.invite_code == candidate)
            .first()
        )
        if not exists:
            invite_code = candidate
        attempts += 1
        if attempts > 5 and not invite_code:
            raise HTTPException(status_code=500, detail="Could not generate unique invite code")

    org = OrganizationORM(
        id=str(uuid.uuid4()),
        name=name,
        invite_code=invite_code,
        owner_user_id=None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(org)
    db.commit()
    db.refresh(org)

    return {
        "id": org.id,
        "name": org.name,
        "owner_user_id": org.owner_user_id,
        "owner_email": None,
        "invite_code": invite_code,
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }

# ============================================================
# Integrations (Gmail / Calendar)
# ============================================================
@api_router.get("/integrations/status")
def integrations_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    accounts = (
        db.query(ExternalAccountORM)
        .filter(ExternalAccountORM.user_id == current_user.id)
        .all()
    )
    status_map = {
        "gmail": {"connected": False, "last_updated_at": None},
        "calendar": {"connected": False, "last_updated_at": None},
    }
    provider_to_key = {
        "google_gmail": "gmail",
        "google_calendar": "calendar",
    }
    for acct in accounts:
        key = provider_to_key.get(acct.provider)
        if not key:
            continue
        status_map[key] = {
            "connected": bool(acct.access_token),
            "last_updated_at": acct.updated_at.isoformat() if acct.updated_at else None,
        }
    return status_map

def _build_google_auth_url(redirect_uri: str, scope: str, state: str) -> str:
    params = {
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

def _exchange_google_code(code: str, redirect_uri: str) -> dict:
    data = {
        "code": code,
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    resp = httpx.post(GOOGLE_TOKEN_URL, data=data, timeout=10)
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to exchange code with Google")
    return resp.json() # aa

def _handle_google_callback(
    request: Request,
    db: Session,
    current_user: UserORM,
    provider: str,
    scope: str,
    state_key: str,
) -> RedirectResponse:
    # Get callback parameters
    state = request.query_params.get("state")
    code = request.query_params.get("code")
    expected = request.session.get(state_key)
    
    # ✅ DEBUG LOGGING
    print(f"🔍 OAuth callback debug for {provider}:")
    print(f"   State from Google: {state}")
    print(f"   Expected state (session): {expected}")
    print(f"   State key: {state_key}")
    print(f"   Code: {code[:20]}..." if code else "   Code: None")
    
    # Validate state
    if not state or not expected or state != expected:
        print(f"❌ STATE MISMATCH!")
        print(f"   Received: {state}")
        print(f"   Expected: {expected}")
        raise HTTPException(status_code=400, detail="Invalid state")

    if not code:
        print(f"❌ MISSING CODE")
        raise HTTPException(status_code=400, detail="Missing code")

    # ✅ FIX: Build redirect_uri manually to ensure it matches /start
    # Use BACKEND_URL instead of request.url_for to avoid issues
    provider_path = provider.replace("google_", "")  # "google_gmail" -> "gmail"
    redirect_uri = f"{BACKEND_URL}/api/integrations/google/{provider_path}/callback"
    
    print(f"   Redirect URI for token exchange: {redirect_uri}")
    
    # Exchange code for tokens
    try:
        token_data = _exchange_google_code(code, redirect_uri)
        print(f"✅ Token exchange successful")
    except Exception as e:
        print(f"❌ Token exchange failed: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to exchange code with Google: {str(e)}"
        )

    # Extract token data
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in") or 0
    scopes_raw = token_data.get("scope") or ""
    scopes = scopes_raw.split() if isinstance(scopes_raw, str) else scopes_raw
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    print(f"   Access token: {access_token[:20]}..." if access_token else "   No access token")
    print(f"   Refresh token: {'Present' if refresh_token else 'None'}")
    print(f"   Expires at: {expires_at}")

    # Save to database
    try:
        upsert_external_account(
            db=db,
            user_id=current_user.id,
            provider=provider,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            scopes=scopes or [],
        )
        print(f"✅ Saved external account for user {current_user.id}")
    except Exception as e:
        print(f"❌ Failed to save external account: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save tokens: {str(e)}"
        )

    # ✅ FIX: Redirect to frontend (not FRONTEND_APP_URL which has /app)
    # Use the simple provider name for the query param
    simple_provider = provider.replace("google_", "")  # "google_gmail" -> "gmail"
    frontend_base_url = (
        os.getenv("FRONTEND_BASE_URL")
        or os.getenv("FRONTEND_APP_URL")
        or config.FRONTEND_APP_URL
    )
    frontend_base_url = frontend_base_url.rstrip("/")
    if frontend_base_url.endswith("/app"):
        frontend_base_url = frontend_base_url[:-4]
    redirect_target = f"{frontend_base_url}/settings?connected={simple_provider}"
    
    print(f"✅ Redirecting to: {redirect_target}")
    return RedirectResponse(url=redirect_target)

@api_router.get("/integrations/google/gmail/start")
def start_google_gmail_oauth(request: Request, current_user: User = Depends(get_current_user)):
    state = secrets.token_urlsafe(16)
    request.session["oauth_state_google_gmail"] = state
    redirect_uri = f"{BACKEND_URL}/api/integrations/google/gmail/callback"
    url = _build_google_auth_url(redirect_uri, GOOGLE_GMAIL_SCOPE, state)
    return RedirectResponse(url=url)

@api_router.get("/integrations/google/calendar/start")
def start_google_calendar_oauth(request: Request, current_user: User = Depends(get_current_user)):
    state = secrets.token_urlsafe(16)
    request.session["oauth_state_google_calendar"] = state
    redirect_uri = f"{BACKEND_URL}/api/integrations/google/calendar/callback"
    url = _build_google_auth_url(redirect_uri, GOOGLE_CALENDAR_SCOPE, state)
    return RedirectResponse(url=url)

@api_router.get("/integrations/google/gmail/callback", name="google_gmail_callback")
def google_gmail_callback(request: Request, db: Session = Depends(get_db)):
    current_user = require_user(request, db)
    return _handle_google_callback(
        request=request,
        db=db,
        current_user=current_user,
        provider="google_gmail",
        scope=GOOGLE_GMAIL_SCOPE,
        state_key="oauth_state_google_gmail",
    )

@api_router.get("/integrations/google/calendar/callback", name="google_calendar_callback")
def google_calendar_callback(request: Request, db: Session = Depends(get_db)):
    current_user = require_user(request, db)
    return _handle_google_callback(
        request=request,
        db=db,
        current_user=current_user,
        provider="google_calendar",
        scope=GOOGLE_CALENDAR_SCOPE,
        state_key="oauth_state_google_calendar",
    )

@api_router.delete("/integrations/{provider}")
def disconnect_integration(
    provider: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if provider not in ALLOWED_INTEGRATION_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported provider")

    (
        db.query(ExternalAccountORM)
        .filter(
            ExternalAccountORM.user_id == current_user.id,
            ExternalAccountORM.provider == provider,
        )
        .delete()
    )
    db.commit()
    return {"success": True}

# ============================================================
# Daily Brief
# ============================================================

def _fetch_recent_emails(token: str) -> List[dict]:
    """
    Minimal Gmail fetch: list messages newer than 1d and pull snippet.
    """
    headers = {"Authorization": f"Bearer {token}"}
    params = {"q": "newer_than:1d", "maxResults": 20}
    base = "https://www.googleapis.com/gmail/v1/users/me/messages"
    resp = httpx.get(base, headers=headers, params=params, timeout=10)
    if resp.status_code != 200:
        return []
    data = resp.json()
    messages = data.get("messages", []) or []
    results = []
    for msg in messages[:20]:
        mid = msg.get("id")
        if not mid:
            continue
        detail = httpx.get(f"{base}/{mid}", headers=headers, timeout=10)
        if detail.status_code != 200:
            continue
        body = detail.json()
        snippet = body.get("snippet") or ""
        payload = body.get("payload") or {}
        headers_list = payload.get("headers") or []
        header_map = {h.get("name"): h.get("value") for h in headers_list if h.get("name")}
        results.append(
            {
                "id": mid,
                "thread_id": body.get("threadId"),
                "from": header_map.get("From"),
                "subject": header_map.get("Subject"),
                "snippet": snippet,
                "received_at": body.get("internalDate"),
            }
        )
    return results

def _fetch_calendar_events(token: str) -> List[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=2)
    params = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 20,
    }
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    resp = httpx.get(url, headers=headers, params=params, timeout=10)
    if resp.status_code != 200:
        return []
    data = resp.json()
    events = data.get("items", []) or []
    normalized = []
    for ev in events:
        start_at = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
        end_at = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date")
        normalized.append(
            {
                "id": ev.get("id"),
                "title": ev.get("summary"),
                "start_time": start_at,
                "end_time": end_at,
                "location": ev.get("location"),
                "is_all_day": bool(ev.get("start", {}).get("date")),
            }
        )
    return normalized

@api_router.get("/tasks", response_model=List[TaskOut])
def list_tasks(request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    tasks = db.query(TaskORM).order_by(TaskORM.created_at.desc()).all()
    return tasks

@api_router.post("/tasks", response_model=TaskOut)
def create_task(payload: TaskIn, request: Request, db: Session = Depends(get_db)):
    me = require_user(request, db)
    task = TaskORM(
        id=str(uuid.uuid4()),
        title=payload.title,
        description=payload.description or "",
        assignee_id=payload.assignee_id,
        status="new",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    # best effort notify assignee
    notif = create_notification_safe(
        db,
        user_id=payload.assignee_id,
        notif_type="task",
        title=f"New task from {me.name}",
        message=payload.title,
        task_id=task.id,
    )
    db.commit()
    return task

@api_router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: str, payload: TaskUpdate, request: Request, db: Session = Depends(get_db)):
    require_user(request, db)
    task = db.get(TaskORM, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    task.status = payload.status
    task.updated_at = datetime.now(timezone.utc)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task

def require_current_user(request: Request, db: Session) -> UserORM:
    """
    Fetch the currently authenticated user from the JWT cookie.
    Raise 401 if not authenticated.
    """
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

# ============================================================
# MEMORY HELPERS
# ============================================================

def append_memory(db: Session, room: RoomORM, agent_id: str, content: str, importance: float = 0.1):
    mem = MemoryORM(
        id=str(uuid.uuid4()),
        agent_id=agent_id,
        room_id=room.id,
        content=content,
        importance_score=importance,
        created_at=datetime.now(timezone.utc),
    )
    db.add(mem)
    return mem

def list_recent_memories(db: Session, room_id: str, limit: int = 8):
    return (
        db.query(MemoryORM)
        .filter(MemoryORM.room_id == room_id)
        .order_by(MemoryORM.created_at.desc())
        .limit(limit)
        .all()
    )

# ============================================================
# SUMMARY UPDATE RULES (Fix #14)
# ============================================================

def extract_explicit_summary_request(text: str) -> Optional[str]:
    """
    Only update summary if user writes something like:
        "update summary: <text>"
    """
    marker = "update summary:"
    lower = text.lower()
    if marker in lower:
        return text[lower.index(marker) + len(marker):].strip()
    return None

def build_ai_prompt(
    db: Session,
    room: RoomORM,
    user: UserORM,
    content: str,
    mode: str,
):
    """
    Build a system + user prompt that:
    - Only goes into "draft a message to X" mode when the user actually
      asks to send/notify/tell someone.
    - Otherwise just answers the question normally.
    - Always talks to the user as "you" / "I", not using their name.
    """
    memories = list_recent_memories(db, room.id, limit=8)
    mem_text = "\n".join(f"- {m.content}" for m in memories)

    # Figure out teammate names in this org (excluding current user)
    teammate_names: list[str] = []
    if room.org_id:
        teammates = (
            db.query(UserORM)
            .filter(UserORM.org_id == room.org_id)
            .all()
        )
        teammate_names = [
            (u.name or "").strip()
            for u in teammates
            if u.id != user.id and (u.name or "").strip()
        ]

    text_lower = (content or "").lower()
    outreach_verbs = [
        "tell ",
        "message ",
        "notify ",
        "ping ",
        "remind ",
        "email ",
        "dm ",
        "slack ",
        "text ",
        "send a message",
        "send this to",
        "let them know",
    ]
    has_verb = any(v in text_lower for v in outreach_verbs)
    has_teammate_name = any(
        name and name.lower() in text_lower for name in teammate_names
    )
    is_outreach = has_verb and has_teammate_name

    # Base system prompt
    system = f"""
You are the workspace assistant inside the room "{room.name}".

Core rules:
- Never actually send messages outside this chat. You only talk to the user here.
- Never say that you are "drafting" a message or "won't send it automatically".
- Never auto-create inbox tasks or notifications unless the user clearly asks for that.
- Never update summaries unless the user explicitly says: "update summary: ...".
- Answer concisely and stay on task.
- Do not hallucinate tasks, inbox items, or teammates that don't exist.
- The user's name is "{user.name}". When you talk to them, refer to them as "you".
  If you write a message on their behalf, speak in first person ("I", "we") and
  never say their name in third person.

""".rstrip()

    if is_outreach:
        # Only in true teammate-messaging scenarios do we use the helper pattern.
        system += """

Current request type: TEAM OUTREACH.

The user is asking you to help send a message to another teammate.

When the user asks you to "send a message to X", "tell X that ...", or similar:
- Assume they want help with the wording.
- Respond with ONE short, natural message they could send, written in the user's voice.
  For example:
    "Hi Alice, could you take a look at the UI and finish the remaining tasks today?"
- Do NOT say "Here is a draft" or "I won't send this automatically".
- You may ask ONCE:
    "Do you want to use that message as-is?"
- Do not ask for confirmation more than once and do not loop.
"""
    else:
        # For normal questions, forbid the draft-message pattern entirely.
        system += """

Current request type: NORMAL QUESTION.

The user is NOT asking you to send or draft a message to a teammate.
For this request:
- Just answer the question directly.
- Do NOT suggest or draft messages to teammates.
- Do NOT use phrases like "Here’s a message you could send to X".
- Do NOT ask whether they want to send anything.
"""

    system += f"""

You may use these recent memory notes and project context:

Project Summary:
{room.project_summary or "(none)"}

Recent Memory Notes:
{mem_text or "(none)"}

Mode: {mode}
""".rstrip()

    # User message is just their raw content; no third-person name.
    user_msg = content

    return system, user_msg

def run_ai(client: OpenAI, system_prompt: str, user_text: str) -> str:
    """
    Unified OpenAI chat wrapper.
    """
    if not client:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_text},
        ],
        temperature=0.4,
    )
    return resp.choices[0].message.content

CONFIRM_PHRASES = [
    "yes",
    "yes please",
    "yes, please",
    "yeah",
    "yep",
    "sure",
    "please send",
    "send it",
    "send it for me",
    "go ahead and send",
    "can you send it for me",
]

def maybe_send_approved_message(
    db: Session,
    room: RoomORM,
    chat_instance: ChatInstanceORM,
    user: UserORM,
    latest_text: str,
) -> Optional[MessageORM]:
    """
    If the latest user message is a confirmation to send a previously
    suggested draft (e.g., 'Yes please, send it'), convert that draft
    into a NotificationORM and add a deterministic assistant reply.

    Returns the assistant MessageORM if we handled it, otherwise None.
    """
    normalized = latest_text.strip().lower()
    if not any(p in normalized for p in CONFIRM_PHRASES):
        return None

    # Look at the most recent assistant message in this room
    last_assistant = db.query(MessageORM).filter(
        MessageORM.room_id == room.id,
        MessageORM.chat_instance_id == chat_instance.id,
        MessageORM.role == "assistant",
    ).order_by(MessageORM.created_at.desc()).first()
    if not last_assistant or not last_assistant.content:
        return None

    content = last_assistant.content

    # Pattern: “Here’s a message you could send to Angie: "Hi Angie, ..." …”
    m = re.search(
        r"message you could send to\s+([A-Za-z][A-Za-z0-9_\- ]*)\s*:\s*\"(.+?)\"",
        content,
        flags=re.DOTALL,
    )
    if not m:
        return None

    target_name = m.group(1).strip()
    message_text = m.group(2).strip()

    # Find recipient user in same org
    recipient = (
        db.query(UserORM)
        .filter(
            UserORM.org_id == room.org_id,
            func.lower(UserORM.name) == target_name.lower(),
        )
        .first()
    )

    # If we can't find them, just tell the user and bail
    if not recipient:
        bot_msg = MessageORM(
            id=str(uuid.uuid4()),
            room_id=room.id,
            chat_instance_id=chat_instance.id,
            sender_id="agent:coordinator",
            sender_name="Coordinator",
            role="assistant",
            content=(
                f"I couldn't find a teammate named {target_name} in your workspace, "
                f"so I couldn’t send it automatically. Here’s the message again for you "
                f"to copy and send manually:\n\n{message_text}"
            ),
            user_id=user.id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(bot_msg)
        chat_instance.last_message_at = bot_msg.created_at
        db.commit()
        return bot_msg

    # Create notification with EXACT approved content
    notif = create_notification_safe(
        db,
        user_id=recipient.id,
        notif_type="message",
        title=f"Message from {user.name}",
        message=message_text,
    )

    # Deterministic assistant reply – no LLM call
    bot_msg = MessageORM(
        id=str(uuid.uuid4()),
        room_id=room.id,
        chat_instance_id=chat_instance.id,
        sender_id="agent:coordinator",
        sender_name="Coordinator",
        role="assistant",
        content=f'Okay, I sent this message to {recipient.name}:\n\n"{message_text}"',
        user_id=user.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(bot_msg)

    chat_instance.last_message_at = bot_msg.created_at
    db.commit()
    publish_status(room.id, "notification_sent", {"recipient": recipient.name})
    return bot_msg

def auto_assign_tasks_from_message(
    db: Session,
    sender: UserORM,
    room: RoomORM,
    message: MessageORM,
    org_users: list[UserORM],
) -> None:
    """
    Heuristic: if message contains a self-reminder or a teammate mention with directive,
    create a pending recommendation in the appropriate user's canon and notify them.
    """
    if not getattr(sender, "org_id", None):
        return
    content = message.content or ""
    text_lower = content.lower()
    now = datetime.now(timezone.utc)

    def add_rec_for_user(target: UserORM, title: str, description: str, assigned_by: str, source_msg_id: Optional[str]):
        plan = get_or_create_canonical_plan(target.id, db)
        pending = plan.pending_recommendations or []
        sig = generate_timeline_signature("today", "high", title)
        if any(rec.get("signature") == sig for rec in pending):
            return False
        rec = {
            "signature": sig,
            "timeframe": "today",
            "section": "high",
            "type": "timeline_addition",
            "reason": f"Assigned by {assigned_by}",
            "item": {
                "title": title,
                "description": description,
                "signature": sig,
                "priority": "high",
                "timeframe": "today",
                "section": "high",
                "source": "agent_assignment",
                "source_message_id": source_msg_id,
                "assigned_by": assigned_by,
                "assigned_by_id": sender.id,
            },
        }
        pending.append(rec)
        plan.pending_recommendations = pending
        flag_modified(plan, "pending_recommendations")
        db.add(plan)
        return True

    def notify_user(target: UserORM, title: str, message_text: str, data: dict):
        notif = NotificationORM(
            id=str(uuid.uuid4()),
            user_id=target.id,
            type="agent_message",
            title=title,
            message=message_text,
            task_id=None,
            created_at=now,
            is_read=False,
            data=data,
        )
        db.add(notif)

    # 1) Self-reminders
    for pattern in SELF_REMINDER_PATTERNS:
        m = re.search(pattern, text_lower, flags=re.IGNORECASE)
        if m:
            reminder_body = (m.group(1) or "").strip()
            if not reminder_body:
                break
            title = f"Reminder: {reminder_body}"
            created = add_rec_for_user(sender, title, "Self reminder", sender.name or sender.email, message.id if message else None)
            notify_user(
                sender,
                "New reminder",
                title,
                {
                    "action": "task_created",
                    "from_user": sender.name,
                    "task_title": title,
                    "notification_type": "self_reminder",
                },
            )
            db.commit()
            break

    # 2) Teammate reminders / notifications via explicit patterns
    for pattern in TEAMMATE_REMINDER_PATTERNS:
        m = re.search(pattern, content, flags=re.IGNORECASE)
        if not m:
            continue
        raw_name = m.group("name")
        body = (m.group("body") or "").strip()
        if not raw_name or not body:
            continue

        target_user = _find_user_by_first_name(raw_name, org_users)
        if not target_user:
            continue

        sender_label = getattr(sender, "name", None) or getattr(sender, "email", "") or "Someone"
        title = body
        description = f"From {sender_label}"
        created = add_rec_for_user(target_user, title, description, sender_label, message.id if message else None)
        if created:
            notify_user(
                target_user,
                f"New task from {sender_label}",
                body,
                {
                    "action": "task_created",
                    "from_user": sender_label,
                    "from_user_id": sender.id,
                    "task_title": title,
                    "notification_type": "agent_coordination",
                },
            )
            db.commit()
            return

    verbs = ["tell", "let", "notify", "ask", "remind", "ping", "inform", "message", "send"]
    if not any(v in text_lower for v in verbs):
        return

    created_any = False
    for teammate in org_users:
        if teammate.id == sender.id:
            continue
        name = (teammate.name or "").lower()
        if not name or name not in text_lower:
            continue

        title = f"{sender.name or sender.email}: {content}"
        description = "Assigned via agent message"
        created = add_rec_for_user(teammate, title, description, sender.name or sender.email, message.id if message else None)
        if created:
            notify_user(
                teammate,
                f"New task from {sender.name or sender.email}",
                content,
                {
                    "action": "task_created",
                    "from_user": sender.name,
                    "from_user_id": sender.id,
                    "task_title": title,
                    "notification_type": "agent_coordination",
                },
            )
            created_any = True

    if created_any:
        db.commit()

async def process_chat_message(
    db: Session,
    room: RoomORM,
    chat: ChatInstanceORM,
    user: UserORM,
    payload: AskModeRequest,
    include_preview: bool = False,
    request: Optional[Request] = None,
) -> tuple[MessageORM, Optional[MessageORM], Optional[dict]]:
    """
    Save a user message to a chat instance and optionally create an assistant reply.
    Now includes automatic embedding generation for RAG.
    Returns (user_message, assistant_message | None, context_preview | None).
    """
    # Compute visibility rooms for author
    user_visible_rooms = _get_user_room_ids(db, user.id) or [room.id]

    # Create user message
    user_msg = MessageORM(
        id=str(uuid.uuid4()),
        room_id=room.id,
        chat_instance_id=chat.id,
        sender_id=f"user:{user.id}",
        sender_name=user.name,
        role="user",
        content=payload.content,
        user_id=user.id,
        created_at=datetime.now(timezone.utc),
        visible_room_ids=user_visible_rooms,
    )
    
    # Generate embedding for user message
    try:
        user_msg.embedding = generate_embedding(payload.content)  # ✅ CORRECT
        logger.debug("Generated embedding for user message %s", user_msg.id)
    except Exception as e:
        logger.warning("Failed to generate embedding for user message: %s", e)
    
    db.add(user_msg)
    chat.last_message_at = user_msg.created_at
    db.commit()

    # Update activity tracking with semantic similarity
    try:
        from app.services.activity_manager import update_user_activity

        status_updated, activity_logged, user_action = await update_user_activity(
            user_id=user.id,
            content=payload.content,
            room_id=room.id,
            action_type="chat_message",
            tool="chat",
            db=db,
        )

        logger.debug(
            f"[Activity] User {user.id[:8]}: status_updated={status_updated}, "
            f"activity_logged={activity_logged}"
        )
    except Exception as e:
        logger.error(f"[Activity] Failed to update activity: {e}")
        # Don't fail the request if activity tracking fails
        user_action = None

    try:
        handled = maybe_send_approved_message(db, room, chat, user, payload.content)
    except Exception as e:
        logger.exception("Error in maybe_send_approved_message: %s", e)
        handled = None

    if handled:
        db.refresh(chat)
        db.refresh(user_msg)
        return user_msg, handled, None

    # Optional conflict fallback
    try:
        _maybe_conflict_fallback(db, user_action, user)
    except Exception as e:
        logger.error("[ConflictFallback] error=%s", e, exc_info=True)

    try:
        teammates = (
            db.query(UserORM)
            .filter(UserORM.org_id == user.org_id)
            .all()
        )
        auto_assign_tasks_from_message(db, user, room, user_msg, teammates)
    except Exception as e:
        logger.exception("Error in auto_assign_tasks_from_message: %s", e)

    agent = get_or_create_agent_for_user(db, user)

    # Build unified system prompt (all chats behave as assistants)
    include_preview = bool(
        (payload and getattr(payload, "include_context_preview", False))
        or (request.query_params.get("include_context_preview") in {"1", "true", "True"})
    )

    fast_path = bool(
        FAST_PATH_SIMPLE
        and not include_preview
        and (
            (request.query_params.get(FAST_PATH_HINT_PARAM) in {"1", "true", "True"} if request else False)
            or len((payload.content or "")) <= 120
        )
    )
    context_preview = None
    meta = {}
    if include_preview:
        system_prompt, context_preview = build_unified_assistant_context(
            db=db,
            user=user,
            room=room,
            chat_instance=chat,
            user_query=payload.content,
            return_preview=True,
            fast_path=fast_path,
        )
        meta = context_preview.get("meta", {})
    else:
        system_prompt, meta = build_unified_assistant_context(
            db=db,
            user=user,
            room=room,
            chat_instance=chat,
            user_query=payload.content,
            return_preview=False,
            fast_path=fast_path,
        )
    recent_msgs = get_context_window(db, chat.id, CONTEXT_WINDOW_SIZE, MAX_CONTEXT_TOKENS)
    logger.info(
        "[UnifiedContext] user_id=%s room_id=%s chat_id=%s canon_items=%s integ_items=%s teammate_users=%s rag_items=%s transcript_msgs=%s",
        user.id,
        room.id,
        chat.id,
        meta.get("canon_items"),
        meta.get("integration_items"),
        meta.get("teammate_users"),
        meta.get("rag_items"),
        meta.get("transcript_msgs"),
    )
    logger.info(
        "[MessageVisibility] room_id=%s user_id=%s user_rooms_count=%s set_on_user_msg=%s set_on_bot_msg=%s",
        room.id,
        user.id,
        len(user_visible_rooms),
        1,
        1,
    )
    conversation_history = [
        {"role": m.role, "content": m.content} for m in recent_msgs
    ]
    messages_payload = [
        {"role": "system", "content": system_prompt},
        *conversation_history,
        {"role": "user", "content": payload.content},
    ]
    if include_preview and context_preview:
        logger.info(
            "[ContextPreview] enabled user_id=%s chat_id=%s sections=%s",
            user.id,
            chat.id,
            [s.get("key") for s in context_preview.get("sections", [])],
        )
    logger.info(f"[Prompt] Built prompt with {len(messages_payload)} messages (history + system + user) fast_path={fast_path}")

    if not openai_client:
        logger.warning("OpenAI client not configured; skipping assistant response.")
        bot_msg = MessageORM(
            id=str(uuid.uuid4()),
            room_id=room.id,
            chat_instance_id=chat.id,
            sender_id=f"agent:{agent.id}",
            sender_name=agent.name,
            role="assistant",
            content="OpenAI API key not configured. Set OPENAI_API_KEY to enable assistant responses.",
            user_id=user.id,
            created_at=datetime.now(timezone.utc),
            visible_room_ids=user_visible_rooms,
        )
        db.add(bot_msg)
        chat.last_message_at = bot_msg.created_at
        db.commit()
        return user_msg, bot_msg

    completion = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages_payload,
    )
    answer = completion.choices[0].message.content

    # Create assistant message
    bot_msg = MessageORM(
        id=str(uuid.uuid4()),
        room_id=room.id,
        chat_instance_id=chat.id,
        sender_id=f"agent:{agent.id}",
        sender_name=agent.name,
        role="assistant",
        content=answer,
        user_id=user.id,
        created_at=datetime.now(timezone.utc),
        visible_room_ids=user_visible_rooms,
    )
    
    # Generate embedding for assistant response
    try:
        bot_msg.embedding = generate_embedding(answer)  # ✅ FIXED - removed asyncio.run()
        logger.debug("Generated embedding for assistant message %s", bot_msg.id)
    except Exception as e:
        logger.warning("Failed to generate embedding for assistant message: %s", e)
    
    db.add(bot_msg)
    chat.last_message_at = bot_msg.created_at
    db.commit()

    return user_msg, bot_msg, context_preview

def get_or_create_agent_for_user(db: Session, user: UserORM) -> AgentORM:
    """
    Ensure each human user has exactly one AgentORM row
    that represents their personal AI rep.
    """
    agent = (
        db.query(AgentORM)
        .filter(AgentORM.user_id == user.id)
        .first()
    )
    if agent:
        return agent

    agent = AgentORM(
        id=str(uuid.uuid4()),
        user_id=user.id,
        name=f"{user.name or user.email}'s Rep",
        persona_json={
            "style": "default",
            "description": f"AI representative for {user.name or user.email}",
        },
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent

@api_router.get("/users/{user_id}/agent")
def get_user_agent(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user(request, db)
    perms = getattr(current_user, "permissions", {}) or {}
    if current_user.id != user_id and not perms.get("backend"):
        raise HTTPException(status_code=403, detail="Not authorized")

    user = db.get(UserORM, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    agent = get_or_create_agent_for_user(db, user)
    return {
        "agent_id": agent.id,
        "user_id": agent.user_id,
        "name": agent.name,
    }

@api_router.get("/agents/{agent_id}")
def get_agent_by_id(
    agent_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user(request, db)
    perms = getattr(current_user, "permissions", {}) or {}

    agent = db.get(AgentORM, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent.user_id != current_user.id and not perms.get("backend"):
        raise HTTPException(status_code=403, detail="Not authorized")

    return {
        "agent_id": agent.id,
        "user_id": agent.user_id,
        "name": agent.name,
    }

@api_router.post("/rooms/{room_id}/ask", response_model=RoomResponse)
async def ask(room_id: str, payload: AskModeRequest, request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request, db)
    room = db.get(RoomORM, room_id)
    room = ensure_room_access(db, user, room)
    chat = get_preferred_chat_instance(db, room, created_by_user_id=user.id)

    include_preview = _should_include_context_preview(request, payload.dict(exclude_none=True))
    logger.info(
        "[ChatSendRoute] path=%s handler=ask(room) chat_id=%s user_id=%s streaming=false include_context_preview=%s",
        request.url.path,
        chat.id if chat else None,
        user.id,
        include_preview,
    )

    _, _, context_preview = await process_chat_message(
        db=db,
        room=room,
        chat=chat,
        user=user,
        payload=payload,
        include_preview=include_preview,
        request=request,
    )

    db.refresh(room)
    db.refresh(chat)
    return room_to_response(db, room, chat=chat, context_preview=context_preview)

# ============================================================
# Room logic
# ============================================================

@api_router.get("/rooms/{room_id}/memory")
def get_memory(room_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    room = db.get(RoomORM, room_id)
    if not room:
        raise HTTPException(404, "Room not found")
    ensure_room_access(db, user, room)

    notes = (
        db.query(MemoryORM)
        .filter(MemoryORM.room_id == room_id)
        .order_by(MemoryORM.created_at.desc())
        .limit(20)
        .all()
    )
    return {
        "project_summary": room.project_summary or "",
        "memory_summary": room.memory_summary or "",
        "notes": [m.content for m in notes],
        "count": len(notes),
    }

@api_router.post("/rooms/{room_id}/memory/query")
def query_memory(
    room_id: str,
    payload: MemoryQueryRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Small helper: asks the model ONLY using memory context.
    """
    user = require_user(request, db)

    room = db.get(RoomORM, room_id)
    if not room:
        raise HTTPException(404, "Room not found")
    ensure_room_access(db, user, room)

    notes = (
        db.query(MemoryORM)
        .filter(MemoryORM.room_id == room.id)
        .order_by(MemoryORM.created_at.desc())
        .limit(200)
        .all()
    )
    text = "\n".join(n.content for n in notes)

    system_prompt = f"""
You are the memory subsystem for room "{room.name}".

You ONLY answer based on the memory context below.
If the answer is not present, say you don't know.
Never invent details.

Memory Context:
{text or "(empty)"}
""".strip()

    # ✅ use the same client as everywhere else
    answer = run_ai(openai_client, system_prompt, payload.question)

    # optional: log memory usage
    append_memory(
        db,
        room,
        agent_id="coordinator",
        content=f"Memory queried: {payload.question}",
        importance=0.05,
    )
    db.commit()

    return {"answer": answer}

# -----------------------------
# Daily Brief (MVP)
# -----------------------------
from textwrap import dedent

@api_router.get("/daily-brief")
def daily_brief(request: Request, force: bool = False, db: Session = Depends(get_db)):
    """
    Get daily brief with real Gmail/Calendar data
    
    - Cached per user per day
    - Use ?force=true to regenerate
    """
    user = require_user(request, db)
    today = datetime.now(timezone.utc).date()

    # Check cache (if you have DailyBrief model)
    # If not, skip caching for now
    try:
        brief = (
            db.query(DailyBriefORM)
            .filter(
                DailyBriefORM.user_id == user.id,
                DailyBriefORM.date == today
            )
            .first()
        )

        # Return cached if exists and not forcing refresh
        if brief and not force:
            return {
                "date": brief.date.isoformat(),
                "generated_at": brief.generated_at.isoformat() if brief.generated_at else None,
                **brief.summary_json,
            }
    except:
        # If DailyBrief table doesn't exist yet, skip caching
        brief = None

    # Generate new brief with real data
    try:
        from app.services.briefs import generate_daily_brief, MissingIntegrationsError
        
        try:
            summary = generate_daily_brief(user, db)
        except MissingIntegrationsError as mie:
            return {
                "error": "missing_integrations",
                "missing": mie.missing
            }
        
    except ImportError:
        # Fallback if services aren't available
        return {
            "error": "service_unavailable",
            "message": "Daily brief service not configured"
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Save to database (if table exists)
    if brief:
        brief.summary_json = summary
        brief.generated_at = datetime.now(timezone.utc)
        db.commit()
    else:
        try:
            brief = DailyBriefORM(
                id=str(uuid.uuid4()),
                user_id=user.id,
                org_id=getattr(user, "org_id", None),
                date=today,
                summary_json=summary,
                generated_at=datetime.now(timezone.utc),
            )
            db.add(brief)
            db.commit()
        except:
            # If table doesn't exist, skip saving
            pass

    # Return structured response
    return {
        "date": summary.get("date"),
        "generated_at": summary.get("generated_at"),
        "personal": summary.get("personal", {}),
        "org": summary.get("org", {}),
        "outbound": summary.get("outbound", {}),
    }

@api_router.get("/rooms", response_model=List[RoomOut])
async def list_rooms(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all rooms the current user is a member of."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Ensure the personal room/membership exists
    try:
        get_or_create_personal_room(current_user.id, db)
    except Exception as e:
        logger.warning(f"[Assistant] Could not ensure personal room: {e}")

    memberships = (
        db.query(RoomMemberORM)
        .filter(RoomMemberORM.user_id == current_user.id)
        .all()
    )
    room_ids = [m.room_id for m in memberships]

    if not room_ids:
        return []

    rooms = (
        db.query(RoomORM)
        .filter(RoomORM.id.in_(room_ids))
        .all()
    )

    # Personal first, then newest
    rooms = sorted(
        rooms,
        key=lambda r: (
            0 if r.name == "Personal" else 1,
            -(r.created_at.timestamp() if r.created_at else 0),
        ),
    )

    # PERFORMANCE FIX: Batch load all message counts in one query with GROUP BY
    # Previously: N individual COUNT queries (one per room)
    # Now: Single query for all rooms
    room_list = []

    if rooms:
        room_ids_for_count = [r.id for r in rooms]
        message_counts_raw = (
            db.query(
                MessageORM.room_id,
                func.count(MessageORM.id).label('count')
            )
            .filter(MessageORM.room_id.in_(room_ids_for_count))
            .group_by(MessageORM.room_id)
            .all()
        )

        # Build lookup map: room_id -> message_count
        message_count_map = {row[0]: row[1] for row in message_counts_raw}

        # Convert rooms using pre-loaded counts
        for room in rooms:
            message_count = message_count_map.get(room.id, 0)

            room_list.append(
                RoomOut(
                    id=room.id,
                    name=room.name,
                    created_at=room.created_at.isoformat() if room.created_at else "",
                    message_count=message_count,
                    project_summary=room.project_summary or "",
                    is_personal=(room.name == "Personal"),
                )
            )

    return room_list

@api_router.delete("/rooms/{room_id}", status_code=204, response_model=None)  # ✅ Add this
async def delete_room(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)  # Keep this!
):
    """Delete a room. Only org owner can delete rooms."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    room = db.query(RoomORM).filter(RoomORM.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    # Check org match
    if getattr(current_user, "org_id", None) != room.org_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this room")

    # Only org owner or managers (backend permission) can delete
    perms = getattr(current_user, "permissions", {}) or {}
    is_owner = False
    if getattr(room, "org_id", None):
        org = db.query(OrganizationORM).filter(OrganizationORM.id == room.org_id).first()
        is_owner = org and org.owner_user_id == current_user.id
    if not (is_owner or perms.get("backend")):
        raise HTTPException(status_code=403, detail="Not authorized to delete this room")
    
    # Don't allow deleting the "team" room
    if room.name.lower() == "team":
        raise HTTPException(status_code=400, detail="Cannot delete the team room")
    
    # Delete associated records
    db.query(MessageORM).filter(MessageORM.room_id == room_id).delete()
    db.query(ChatInstanceORM).filter(ChatInstanceORM.room_id == room_id).delete()
    db.query(MemoryORM).filter(MemoryORM.room_id == room_id).delete()
    db.query(InboxTaskORM).filter(InboxTaskORM.room_id == room_id).delete()
    db.query(RoomMemberORM).filter(RoomMemberORM.room_id == room_id).delete()
    
    # Delete room
    db.delete(room)
    db.commit()
    
    return None

@api_router.post("/rooms/{room_id}/members", response_model=RoomMemberOut)
def add_room_member(
    room_id: str,
    payload: RoomMemberCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user(request, db)
    permissions = getattr(current_user, "permissions", {}) or {}
    if not permissions.get("backend"):
        raise HTTPException(status_code=403, detail="Only managers can add members")

    room = db.query(RoomORM).filter(RoomORM.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    exists = (
        db.query(RoomMemberORM)
        .filter(RoomMemberORM.room_id == room_id, RoomMemberORM.user_id == payload.user_id)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="User already in room")

    membership = RoomMemberORM(
        id=str(uuid.uuid4()),
        room_id=room_id,
        user_id=payload.user_id,
        role_in_room=payload.role_in_room,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership

@api_router.delete("/rooms/{room_id}/members/{user_id}", status_code=204)
def remove_room_member(
    room_id: str,
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user(request, db)
    permissions = getattr(current_user, "permissions", {}) or {}
    if not permissions.get("backend"):
        raise HTTPException(status_code=403, detail="Only managers can remove members")

    membership = (
        db.query(RoomMemberORM)
        .filter(RoomMemberORM.room_id == room_id, RoomMemberORM.user_id == user_id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Membership not found")

    db.delete(membership)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@api_router.get("/rooms/{room_id}/members", response_model=List[RoomMemberOut])
def get_room_members(
    room_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    is_member = (
        db.query(RoomMemberORM)
        .filter(RoomMemberORM.room_id == room_id, RoomMemberORM.user_id == current_user.id)
        .first()
    )
    if not is_member:
        raise HTTPException(status_code=403, detail="Not a member of this room")

    members = (
        db.query(RoomMemberORM)
        .filter(RoomMemberORM.room_id == room_id)
        .all()
    )
    return members


@api_router.get("/rooms/{room_id}/stats")
async def get_room_stats(
    room_id: str,
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get room statistics for organization intelligence graph.

    Returns aggregated metrics:
    - fires: Count of urgent unread notifications
    - last_active: Timestamp of most recent activity
    - recent_activities: Last 5 significant activities
    - risks: Last 5 urgent notifications
    """
    # Verify user has access to this room
    is_member = (
        db.query(RoomMemberORM)
        .filter(RoomMemberORM.room_id == room_id, RoomMemberORM.user_id == current_user.id)
        .first()
    )
    if not is_member:
        raise HTTPException(status_code=403, detail="Not a member of this room")

    # Get room
    room = db.query(RoomORM).filter(RoomORM.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Calculate stats
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Urgent notifications count (fires)
    # Note: notifications don't have room_id, so we get user notifications for room members
    room_member_ids = [m.user_id for m in db.query(RoomMemberORM).filter(RoomMemberORM.room_id == room_id).all()]

    urgent_count = db.query(NotificationORM).filter(
        NotificationORM.user_id.in_(room_member_ids),
        NotificationORM.severity == 'urgent',
        NotificationORM.is_read == False,
        NotificationORM.created_at >= since
    ).count()

    # Recent activities from room
    activities = db.query(UserAction).filter(
        UserAction.room_id == room_id,
        UserAction.timestamp >= since,
        UserAction.is_status_change == True
    ).order_by(desc(UserAction.timestamp)).limit(5).all()

    # Last activity timestamp
    last_activity = db.query(UserAction).filter(
        UserAction.room_id == room_id
    ).order_by(desc(UserAction.timestamp)).first()

    # Recent risks (urgent notifications for room members)
    risks = db.query(NotificationORM).filter(
        NotificationORM.user_id.in_(room_member_ids),
        NotificationORM.severity == 'urgent',
        NotificationORM.created_at >= since
    ).order_by(desc(NotificationORM.created_at)).limit(5).all()

    return {
        "room_id": room_id,
        "fires": urgent_count,
        "last_active": last_activity.timestamp.isoformat() if last_activity else None,
        "recent_activities": [
            {
                "summary": a.activity_summary,
                "timestamp": a.timestamp.isoformat() if a.timestamp else None
            } for a in activities
        ],
        "risks": [
            {
                "title": r.title,
                "message": r.message,
                "created_at": r.created_at.isoformat() if r.created_at else None
            } for r in risks
        ]
    }


@api_router.get("/org/graph-data")
async def get_org_graph_data(
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get complete organization graph data for intelligence visualization.

    Returns:
    - rooms: List of rooms with stats, activities, and members
    - edges: Connections between rooms based on shared members
    - last_updated: Timestamp of data generation
    """
    # Get all rooms user has access to
    room_memberships = db.query(RoomMemberORM).filter(
        RoomMemberORM.user_id == current_user.id
    ).all()

    room_ids = [m.room_id for m in room_memberships]

    if not room_ids:
        return {
            "rooms": [],
            "edges": [],
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    rooms = db.query(RoomORM).filter(RoomORM.id.in_(room_ids)).all()

    room_data = []
    since = datetime.now(timezone.utc) - timedelta(days=days)

    for room in rooms:
        # Get members for this room
        members = db.query(UserORM).join(RoomMemberORM).filter(
            RoomMemberORM.room_id == room.id
        ).all()

        room_member_ids = [m.id for m in members]

        # Get urgent notifications count
        urgent_count = db.query(NotificationORM).filter(
            NotificationORM.user_id.in_(room_member_ids),
            NotificationORM.severity == 'urgent',
            NotificationORM.is_read == False,
            NotificationORM.created_at >= since
        ).count()

        # Get recent activities
        activities = db.query(UserAction).filter(
            UserAction.room_id == room.id,
            UserAction.timestamp >= since,
            UserAction.is_status_change == True
        ).order_by(desc(UserAction.timestamp)).limit(5).all()

        # Get last activity timestamp
        last_activity = db.query(UserAction).filter(
            UserAction.room_id == room.id
        ).order_by(desc(UserAction.timestamp)).first()

        # Get recent risks
        risks = db.query(NotificationORM).filter(
            NotificationORM.user_id.in_(room_member_ids),
            NotificationORM.severity == 'urgent',
            NotificationORM.created_at >= since
        ).order_by(desc(NotificationORM.created_at)).limit(5).all()

        room_data.append({
            "id": room.id,
            "name": room.name,
            "fires": urgent_count,
            "last_active": last_activity.timestamp.isoformat() if last_activity else None,
            "recent_activities": [
                {
                    "summary": a.activity_summary or "Activity",
                    "timestamp": a.timestamp.isoformat() if a.timestamp else None
                } for a in activities
            ],
            "risks": [
                {
                    "title": r.title,
                    "message": r.message,
                    "created_at": r.created_at.isoformat() if r.created_at else None
                } for r in risks
            ],
            "members": [
                {
                    "id": m.id,
                    "name": m.name or (m.email.split('@')[0] if m.email else "Unknown"),
                    "email": m.email
                }
                for m in members
            ]
        })

    # Calculate edges (shared members between rooms)
    edges = []
    for i, room_a in enumerate(room_data):
        for room_b in room_data[i+1:]:
            members_a = {m["id"] for m in room_a["members"]}
            members_b = {m["id"] for m in room_b["members"]}
            overlap = len(members_a & members_b)

            if overlap > 0:
                edges.append({
                    "source": room_a["id"],
                    "target": room_b["id"],
                    "overlap": overlap,
                    "strength": min(overlap / 5.0, 1.0)  # Normalize to 0-1 scale
                })

    return {
        "rooms": room_data,
        "edges": edges,
        "last_updated": datetime.now(timezone.utc).isoformat()
    }

@api_router.get("/users/{user_id}/rooms", response_model=List[str])
def get_user_rooms(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user(request, db)
    permissions = getattr(current_user, "permissions", {}) or {}

    if current_user.id != user_id and not permissions.get("backend"):
        raise HTTPException(status_code=403, detail="Not authorized")

    memberships = (
        db.query(RoomMemberORM)
        .filter(RoomMemberORM.user_id == user_id)
        .all()
    )
    return [m.room_id for m in memberships]

@api_router.put("/users/{user_id}/rooms")
def update_user_rooms(
    user_id: str,
    payload: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = require_user(request, db)
    permissions = getattr(current_user, "permissions", {}) or {}
    if not permissions.get("backend"):
        raise HTTPException(status_code=403, detail="Only managers can update memberships")

    room_ids = payload.get("room_ids") if isinstance(payload, dict) else None
    if not room_ids or not isinstance(room_ids, list):
        raise HTTPException(status_code=400, detail="room_ids (list) is required")

    # Prevent removing a user from all rooms
    if len(room_ids) == 0:
        raise HTTPException(status_code=400, detail="User must belong to at least one room")

    # Validate target user exists
    target_user = db.get(UserORM, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Optional: ensure rooms exist
    existing_rooms = {
        r.id
        for r in db.query(RoomORM).filter(RoomORM.id.in_(room_ids)).all()
    }
    missing = set(room_ids) - existing_rooms
    if missing:
        raise HTTPException(status_code=400, detail=f"Invalid room ids: {', '.join(missing)}")

    db.query(RoomMemberORM).filter(RoomMemberORM.user_id == user_id).delete()

    for room_id in room_ids:
        membership = RoomMemberORM(
            id=str(uuid.uuid4()),
            room_id=room_id,
            user_id=user_id,
        )
        db.add(membership)

    db.commit()
    return {"message": "Rooms updated successfully"}

@api_router.patch("/users/{user_id}/permissions", response_model=UserOut)
def update_user_permissions(
    user_id: str,
    payload: Permissions,
    request: Request,
    db = Depends(get_db),
):
    # 1) Auth: use your existing helper
    current_user = require_user(request, db)

    admin_emails = parse_admin_emails()
    if not is_platform_admin_user(current_user, admin_emails):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage permissions",
        )

    # 3) Look up the target user
    user = db.query(UserORM).filter(UserORM.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # 4) Update JSON field & save
    user.permissions = payload.dict()
    db.commit()
    db.refresh(user)

    # 5) Return in the same shape as /me / /team
    return user_to_dict(user)

# @api_router.get("/brief/daily")
def get_daily_brief(  # DEPRECATED: route disabled, use /api/canon endpoints instead
    request: Request,
    force: bool = False,
    quick_load: bool = True,
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """
    DEPRECATED - use /api/canon endpoints instead.
    """
    user = require_user(request, db)
    now = datetime.now(timezone.utc)
    today = now.date()

    # Canonical plan setup
    canonical_plan = get_or_create_canonical_plan(user.id, db)
    recommendations = canonical_plan.pending_recommendations or []
    old_recs = list(recommendations)

    timeline = canonical_plan.approved_timeline or {}
    total_items = count_timeline_items(timeline)
    is_canon_empty = total_items == 0
    logger.info(f"[BRIEF LOAD] User {user.id} canon has {total_items} items, is_empty={is_canon_empty}")

    # Validate and backfill missing signatures in canon timeline
    missing_sig_items = []
    timeframe_keys = ["1d", "7d", "28d"]
    priority_keys = ["critical", "high", "medium", "low", "normal", "high_priority"]
    for tf in timeframe_keys:
        sections = timeline.get(tf) or {}
        for pr in priority_keys:
            items = sections.get(pr, []) or []
            for item in items:
                if item.get("signature"):
                    continue
                missing_sig_items.append({"timeframe": tf, "priority": pr, "title": item.get("title", "")})
                signature = generate_timeline_signature(tf, pr, item.get("title", ""))
                item["signature"] = signature
                logger.info(f"[CANON FIX] Added signature to timeline/{tf}/{pr} '{item.get('title', '')[:50]}': {signature}")

    if missing_sig_items:
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(canonical_plan, "approved_timeline")
        db.commit()
        logger.error(f"[CANON VALIDATION] ❌ Fixed {len(missing_sig_items)} items missing signatures")
        logger.error(f"[CANON VALIDATION] Sample missing: {missing_sig_items[:5]}")
    else:
        logger.info("[CANON VALIDATION] ✅ All timeline items have signatures")

    # Quick-load path: return canon without regeneration unless forced
    if quick_load and not force:
        completed_items = db.query(CompletedBriefItem).filter(
            CompletedBriefItem.user_id == user.id
        ).all()
        completed_sigs = {item.item_signature for item in completed_items if item.item_signature}
        filtered = _filter_canon_with_completed(canonical_plan, completed_sigs)
        logger.info(f"[Brief] Quick load mode - returning canon without sync (filtered {len(completed_sigs)} completed)")
        return {
            "canonical": filtered,
            "recommendations": filtered["recommendations"],
            "cached": True,
            "syncing": False,
            "generated_at": canonical_plan.last_ai_sync.isoformat() if canonical_plan.last_ai_sync else None,
        }

    # Regenerate recommendations if needed
    try:
        if force or should_regenerate_recommendations(canonical_plan):
            from app.services.gmail import fetch_unread_emails
            from app.services.calendar import fetch_upcoming_events

            try:
                emails = fetch_unread_emails(user, db)
            except Exception as e:
                logger.warning(f"[Canon] Failed to fetch emails for recommendations: {e}")
                emails = []

            try:
                events = fetch_upcoming_events(user, db)
            except Exception as e:
                logger.warning(f"[Canon] Failed to fetch events for recommendations: {e}")
                events = []

            # Ensure links for matching
            for email in emails:
                if email.get("id") and not email.get("link"):
                    email["link"] = f"https://mail.google.com/mail/u/0/#all/{email['id']}"
            for event in events:
                if event.get("id") and not event.get("link"):
                    event["link"] = event.get("htmlLink") or f"https://calendar.google.com/calendar/event?eid={event['id']}"

            # Generate NEW recommendations only (use canon.py version which filters past events)
            from app.services.canon import generate_recommendations as canon_generate_recommendations

            new_recommendations = canon_generate_recommendations(
                user,
                emails,
                events,
                canonical_plan,
                db,
                is_manual_refresh=force
            )

            # ADDITIVE: Add to existing recommendations, don't replace
            existing_recs = canonical_plan.pending_recommendations or []
            old_sig_set = {rec.get('signature') for rec in old_recs if rec.get('signature')}

            # Merge: existing + new (avoiding duplicates by signature)
            existing_sigs = {rec.get('signature') for rec in existing_recs if rec.get('signature')}
            new_recs_filtered = [rec for rec in new_recommendations if rec.get('signature') not in existing_sigs]

            all_recommendations = existing_recs + new_recs_filtered

            # Update pending recommendations
            canonical_plan.pending_recommendations = all_recommendations
            canonical_plan.last_ai_sync = now

            logger.info(f"[Canon] Added {len(new_recs_filtered)} new recommendations (total: {len(all_recommendations)})")

            recommendations = all_recommendations  # Use merged list
            canonical_plan.last_ai_sync = now
            db.commit()

            # Proactive: timeline drift if many new high-priority recs
            high_new = []
            for rec in new_recs_filtered:
                sig = rec.get("signature")
                if sig and sig in old_sig_set:
                    continue
                item = rec.get("item") or {}
                section = rec.get("section", "").lower()
                priority = (item.get("priority") or "").lower()
                if priority in ["critical", "high"] or section in ["critical", "high", "high_priority"]:
                    high_new.append(rec)
            if len(high_new) >= 3:
                personal_chat = get_or_create_personal_assistant_chat(user.id, db)
                marker = "bulk_high_rec"
                if not has_recent_proactive(personal_chat.id, "timeline_drift", marker, db, within_minutes=120):
                    send_proactive_message(
                        user_id=user.id,
                        text="Your AI timeline found several new high-priority items that may change your day. Want help reprioritizing?",
                        trigger="timeline_drift",
                        context={"signatures": [r.get("signature") for r in high_new], "count": len(high_new), "marker": marker},
                        db=db,
                    )
    except Exception as e:
        logger.warning(f"[Canon] Recommendation generation skipped: {e}")

    brief = db.query(DailyBriefORM).filter(
        DailyBriefORM.user_id == user.id,
        DailyBriefORM.date == today
    ).first()

    gen_at = brief.generated_at if brief else None
    if gen_at and gen_at.tzinfo is None:
        gen_at = gen_at.replace(tzinfo=timezone.utc)
    age_hours = (now - gen_at).total_seconds() / 3600 if gen_at else None

    should_generate_brief = (
        force
        or brief is None
        or not canonical_plan.last_ai_sync
        or (now - canonical_plan.last_ai_sync).total_seconds() > 3600
    )
    if age_hours is not None:
        should_generate_brief = should_generate_brief or age_hours >= 4

    cached = False
    result = brief.summary_json if brief else {}

    if brief and not should_generate_brief:
        cached = True
        logger.info(f"[Brief] Returning cached brief for {user.email} (age: {age_hours:.1f}h)")
        if background_tasks:
            background_tasks.add_task(incremental_sync_context, user.id, db)
    else:
        logger.info(f"[Brief] Generating fresh brief for {user.email} (force={force})")

        if force:
            result = generate_daily_brief(user, db)
        else:
            context_store = db.query(UserContextStore).filter(
                UserContextStore.user_id == user.id
            ).first()

            if context_store and context_store.emails_recent:
                regenerate_brief_from_context(user, context_store, db)
                brief = db.query(DailyBriefORM).filter(
                    DailyBriefORM.user_id == user.id,
                    DailyBriefORM.date == today
                ).first()
                result = brief.summary_json if brief else {}
            else:
                result = generate_daily_brief(user, db)

        if background_tasks:
            background_tasks.add_task(incremental_sync_context, user.id, db)
        canonical_plan.last_ai_sync = now
        db.add(canonical_plan)
        db.commit()
        gen_at = now

    # Canon should only be seeded once on first load
    completed_history_exists = db.query(CompletedBriefItem).filter(CompletedBriefItem.user_id == user.id).first() is not None
    is_first_seed = is_canon_empty and not completed_history_exists
    personal = result.get("personal", result if isinstance(result, dict) else {}) if result else {}
    brief_timeline = personal.get("timeline") if isinstance(personal, dict) else {}
    brief_items = count_timeline_items(brief_timeline or {})

    if is_first_seed and brief_items > 0:
        logger.info(f"[BRIEF] First-time user - SEEDING canon from AI brief (ONE TIME ONLY)")
        logger.info(f"[BRIEF] Seeding {brief_items} items into canonical plan")
        canonical_plan.approved_timeline = brief_timeline
        canonical_plan.active_priorities = personal.get("priorities") or []
        canonical_plan.last_user_modification = canonical_plan.last_user_modification or now
        canonical_plan.last_ai_sync = canonical_plan.last_ai_sync or now
        db.add(canonical_plan)
        db.commit()
    else:
        logger.info(f"[BRIEF] Existing canon with {total_items} items - KEEPING INTACT, NOT OVERWRITING")

    completed_sigs = {
        item.item_signature
        for item in db.query(CompletedBriefItem).filter(CompletedBriefItem.user_id == user.id).all()
    }
    logger.info(f"[FILTER] Found {len(completed_sigs)} completed items in DB")
    logger.info(f"[FILTER] First 5 completed signatures: {list(completed_sigs)[:5]}")

    # Get sample signatures from canon before filtering
    canon_timeline = canonical_plan.approved_timeline or {}
    sample_canon_sigs = []
    for tf, sections in canon_timeline.items():
        if isinstance(sections, dict):
            for priority, items in sections.items():
                if isinstance(items, list):
                    sample_canon_sigs.extend([item.get("signature") for item in items[:2]])
    logger.info(f"[FILTER] Sample canon signatures before filtering: {sample_canon_sigs[:5]}")

    displayed_timeline = filter_timeline_by_signatures(
        canonical_plan.approved_timeline or {},
        completed_sigs
    )
    displayed_recommendations = filter_timeline_by_signatures(
        canonical_plan.pending_recommendations or [],
        completed_sigs
    )

    # Count items after filtering
    filtered_count = count_timeline_items(displayed_timeline)
    logger.info(f"[FILTER] Displaying {filtered_count} items after removing {len(completed_sigs)} completed ones")

    canonical_last_ai_sync = canonical_plan.last_ai_sync.isoformat() if canonical_plan.last_ai_sync else None
    canonical_last_user_modification = canonical_plan.last_user_modification.isoformat() if canonical_plan.last_user_modification else None

    resp = {
        "brief": result,
        "cached": cached,
        "syncing": True,
        "generated_at": (gen_at.isoformat() if isinstance(gen_at, datetime) else gen_at) if gen_at else None,
    }
    resp.update({
        "canonical": {
            "timeline": displayed_timeline,
            "priorities": canonical_plan.active_priorities or [],
            "last_ai_sync": canonical_last_ai_sync,
            "last_user_modification": canonical_last_user_modification,
        },
        "recommendations": displayed_recommendations,
        "last_user_modification": canonical_last_user_modification,
    })
    return resp


@api_router.get("/debug/canon-state")
async def debug_canon_state(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Debug endpoint to inspect canonical plan and completion state.
    """
    canonical = get_or_create_canonical_plan(current_user.id, db)
    timeline = canonical.approved_timeline or {}

    timeframe_aliases = {
        "today": ["today", "1d"],
        "this_week": ["this_week", "7d", "week"],
        "this_month": ["this_month", "28d", "month"],
    }
    priority_aliases = {
        "urgent": ["urgent", "critical"],  # New 2-tier + legacy
        "normal": ["normal", "high", "high_priority", "medium", "low"],  # New 2-tier + legacy
    }

    def _resolve_key(key: str, aliases: dict) -> str:
        for alias in aliases.get(key, []):
            if alias in timeline:
                return alias
        return key

    total_items = 0
    sample_signatures = []
    for tf in ["today", "this_week", "this_month"]:
        tf_key = _resolve_key(tf, timeframe_aliases)
        for priority in ["urgent", "normal"]:  # 2-tier priority system
            sections = timeline.get(tf_key, {})
            pri_key = None
            for alias in priority_aliases.get(priority, []):
                if alias in sections:
                    pri_key = alias
                    break
            if pri_key is None:
                continue
            items = sections.get(pri_key, []) or []
            total_items += len(items)
            for item in items[:2]:
                sample_signatures.append({
                    "timeframe": tf_key,
                    "priority": pri_key,
                    "title": (item.get("title") or "")[:30],
                    "signature": item.get("signature"),
                })

    completed = db.query(CompletedBriefItem).filter_by(user_id=current_user.id).all()

    return {
        "canon_items_count": total_items,
        "canon_is_empty": total_items == 0,
        "completed_items_count": len(completed),
        "completed_signatures": [item.item_signature for item in completed[:10]],
        "last_ai_sync": canonical.last_ai_sync.isoformat() if canonical.last_ai_sync else None,
        "last_user_modification": canonical.last_user_modification.isoformat() if canonical.last_user_modification else None,
        "sample_canon_signatures": sample_signatures,
    }


@api_router.get("/canon")
async def get_canon(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get canonical plan with filtering for completed/old items.
    """
    logger.info(f"[Canon] User {current_user.id} loading canon (filtered)")

    canon = db.query(UserCanonicalPlan).filter(
        UserCanonicalPlan.user_id == current_user.id
    ).first()

    if not canon:
        logger.info("[Canon] No canon found - user needs to generate")
        return {"exists": False, "message": "No canonical plan yet"}

    completed = db.query(CompletedBriefItem).filter(
        CompletedBriefItem.user_id == current_user.id
    ).all()
    completed_sigs = {c.item_signature for c in completed if c.item_signature}

    timeline = canon.approved_timeline or {}

    # Migrate old schema to 2-tier if needed
    from app.services.canon import migrate_timeline_to_2tier, get_user_timezone, calculate_event_deadline, generate_item_signature
    needs_migration = any(
        timeline.get(tf, {}).get(old_key)
        for tf in ["1d", "7d", "28d"]
        for old_key in ["critical", "high", "high_priority", "medium", "low", "upcoming", "milestones", "goals"]
    )
    if needs_migration:
        logger.info(f"[Canon GET] Migrating timeline from old schema to 2-tier for user {current_user.id}")
        timeline = migrate_timeline_to_2tier(timeline)
        canon.approved_timeline = timeline
        flag_modified(canon, "approved_timeline")
        db.commit()

    # Get user timezone for accurate filtering
    user_timezone = get_user_timezone(current_user, db)

    now = datetime.now(timezone.utc)
    filtered_timeline = {}
    skipped_past_items = 0

    for timeframe, sections in (timeline.items() if isinstance(timeline, dict) else []):
        filtered_timeline[timeframe] = {}
        if not isinstance(sections, dict):
            filtered_timeline[timeframe] = sections
            continue
        for section_name, items in sections.items():
            if not isinstance(items, list):
                filtered_timeline[timeframe][section_name] = items
                continue
            filtered_items = []
            for item in items:
                # Generate signature using centralized function if not present
                sig = item.get("signature")
                if not sig:
                    sig = generate_item_signature(item)
                    item["signature"] = sig

                # Filter out completed items
                if sig in completed_sigs:
                    continue

                # Check if event is in the past using timezone-aware calculation
                is_past = False
                event_time = item.get("start_time") or item.get("start")
                if event_time:
                    try:
                        deadline_info = calculate_event_deadline(event_time, user_timezone)
                        is_past = deadline_info["is_past"]
                        if is_past:
                            skipped_past_items += 1
                            logger.debug(f"[Canon GET] Filtering past event: {item.get('title')}")
                            continue
                    except Exception as e:
                        logger.warning(f"[Canon GET] Error checking event time: {e}")

                # Fallback: check deadline string
                if not event_time:
                    deadline_str = item.get("deadline", "")
                    if deadline_str:
                        try:
                            lower = deadline_str.lower()
                            if "today" in lower or any(day in lower for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]):
                                pass
                            else:
                                from dateutil import parser
                                deadline_dt = parser.parse(deadline_str)
                                if deadline_dt.date() < now.date():
                                    skipped_past_items += 1
                                    continue
                        except Exception:
                            pass

                filtered_items.append(item)
            filtered_timeline[timeframe][section_name] = filtered_items

    logger.info(f"[Canon GET] Filtered out {skipped_past_items} past events from timeline")

    priorities = canon.active_priorities or []
    filtered_priorities = [
        p for p in priorities if not (p.get("signature") and p["signature"] in completed_sigs)
    ]

    recommendations = canon.pending_recommendations or []
    filtered_recommendations = [
        r for r in recommendations if not (r.get("signature") and r["signature"] in completed_sigs)
    ]

    # Count timeline items for logging
    from app.services.canon import count_timeline_items
    timeline_count = count_timeline_items(filtered_timeline)

    # Check OAuth connection status
    from models import ExternalAccount
    from datetime import timedelta

    try:
        gmail_account = db.query(ExternalAccount).filter(
            ExternalAccount.user_id == current_user.id,
            ExternalAccount.provider == "google_gmail"
        ).first()

        calendar_account = db.query(ExternalAccount).filter(
            ExternalAccount.user_id == current_user.id,
            ExternalAccount.provider == "google_calendar"
        ).first()

        # Determine if integrations are connected and healthy
        gmail_connected = gmail_account is not None and gmail_account.access_token is not None
        calendar_connected = calendar_account is not None and calendar_account.access_token is not None

        # Check if tokens are expired or missing expiry; missing expiry is treated as unhealthy
        gmail_healthy = False
        calendar_healthy = False

        if gmail_connected:
            if gmail_account.expires_at:
                expires_at = gmail_account.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                time_until_expiry = expires_at - datetime.now(timezone.utc)
                gmail_healthy = time_until_expiry > timedelta(minutes=5)
            else:
                gmail_healthy = False

        if calendar_connected:
            if calendar_account.expires_at:
                expires_at = calendar_account.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                time_until_expiry = expires_at - datetime.now(timezone.utc)
                calendar_healthy = time_until_expiry > timedelta(minutes=5)
            else:
                calendar_healthy = False
    except Exception as e:
        logger.error(f"[Canon GET] Error checking OAuth status: {e}")
        # Default to safe values if check fails
        gmail_connected = False
        gmail_healthy = False
        calendar_connected = False
        calendar_healthy = False

    integrations_status = {
        "gmail": {
            "connected": gmail_connected,
            "healthy": gmail_healthy,
            "needs_reconnect": gmail_connected and not gmail_healthy
        },
        "calendar": {
            "connected": calendar_connected,
            "healthy": calendar_healthy,
            "needs_reconnect": calendar_connected and not calendar_healthy
        }
    }

    # Warn if canon data is stale due to integration issues
    data_is_stale = False
    if canon.last_ai_sync:
        time_since_sync = datetime.now(timezone.utc) - canon.last_ai_sync
        # If last sync was more than 24 hours ago, data might be stale
        data_is_stale = time_since_sync > timedelta(hours=24)

    # Log bucket counts before returning to frontend (for debugging 1d bucket mismatch)
    bucket_counts = {}
    for tf in ['1d', '7d', '28d']:
        bucket_counts[tf] = {}
        tf_data = filtered_timeline.get(tf, {})
        if isinstance(tf_data, dict):
            for priority in ['urgent', 'normal']:
                items = tf_data.get(priority, [])
                bucket_counts[tf][priority] = len(items) if isinstance(items, list) else 0
        else:
            bucket_counts[tf]['urgent'] = 0
            bucket_counts[tf]['normal'] = 0

    logger.warning("=" * 80)
    logger.warning(f"[API /canon] 📤 RESPONSE TO FRONTEND for {current_user.email}")
    logger.warning(f"[API /canon] Bucket counts being returned:")
    logger.warning(f"[API /canon]   1d/urgent: {bucket_counts['1d']['urgent']}")
    logger.warning(f"[API /canon]   1d/normal: {bucket_counts['1d']['normal']}")
    logger.warning(f"[API /canon]   7d/urgent: {bucket_counts['7d']['urgent']}")
    logger.warning(f"[API /canon]   7d/normal: {bucket_counts['7d']['normal']}")
    logger.warning(f"[API /canon]   28d/urgent: {bucket_counts['28d']['urgent']}")
    logger.warning(f"[API /canon]   28d/normal: {bucket_counts['28d']['normal']}")
    logger.warning(f"[API /canon] Total: {timeline_count} items")
    logger.warning("=" * 80)

    logger.info(
        f"[API /canon] Returning canon to frontend for {current_user.email}: "
        f"{timeline_count} timeline items, "
        f"{len(filtered_priorities)} priorities, "
        f"{len(filtered_recommendations)} recommendations, "
        f"gmail={'✅' if gmail_healthy else '⚠️'}, "
        f"calendar={'✅' if calendar_healthy else '⚠️'}"
    )

    return {
        "exists": True,
        "timeline": filtered_timeline,
        "priorities": filtered_priorities,
        "recommendations": filtered_recommendations,
        "last_sync": canon.last_ai_sync.isoformat() if canon.last_ai_sync else None,
        "last_modified": canon.last_user_modification.isoformat() if canon.last_user_modification else None,
        "integrations": integrations_status,
        "data_stale": data_is_stale,
        "needs_reconnect": (gmail_connected and not gmail_healthy) or (calendar_connected and not calendar_healthy)
    }


@api_router.post("/canon/generate")
async def generate_initial_canon(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate canonical plan for first-time users - USES AI.
    """
    logger.info(f"[Canon Generate] Creating initial canon for user {current_user.id}")

    existing = db.query(UserCanonicalPlan).filter(
        UserCanonicalPlan.user_id == current_user.id
    ).first()
    if existing:
        logger.info("[Canon Generate] Canon already exists, returning existing")
        return {"exists": True, "message": "Canon already exists"}

    from app.services.gmail import fetch_unread_emails
    from app.services.calendar import fetch_upcoming_events

    unread_emails = fetch_unread_emails(current_user, db)
    upcoming_events = fetch_upcoming_events(current_user, db)

    logger.info("[Canon Generate] Calling AI to generate initial brief")
    ai_result = _generate_personal_brief_with_ai(
        user=current_user,
        emails=unread_emails,
        events=upcoming_events,
        db=db,
    )

    canon = UserCanonicalPlan(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        approved_timeline=ai_result.get("timeline") or {
            "1d": {"urgent": [], "normal": []},
            "7d": {"urgent": [], "normal": []},
            "28d": {"urgent": [], "normal": []},
        },
        active_priorities=ai_result.get("priorities", []),
        pending_recommendations=[],
        dismissed_items=[],
        last_ai_sync=datetime.now(timezone.utc),
        last_user_modification=datetime.now(timezone.utc),
    )

    db.add(canon)
    db.commit()

    logger.info("[Canon Generate] Created initial canon")

    return {
        "exists": True,
        "timeline": canon.approved_timeline,
        "priorities": canon.active_priorities,
        "recommendations": [],
    }


@api_router.post("/canon/refresh")
async def refresh_canon(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Manually refresh canonical plan with OAuth-aware error handling.
    """
    logger.info(f"[Canon Refresh] User {current_user.id} manually refreshing")

    from app.services.gmail import fetch_unread_emails
    from app.services.calendar import fetch_upcoming_events

    try:
        unread_emails = fetch_unread_emails(current_user, db)
        upcoming_events = fetch_upcoming_events(current_user, db)

        logger.info(f"[Canon Refresh] Fetched {len(unread_emails)} emails, {len(upcoming_events)} events")

        canon = db.query(UserCanonicalPlan).filter(
            UserCanonicalPlan.user_id == current_user.id
        ).first()

        if not canon:
            canon = UserCanonicalPlan(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                approved_timeline={},
                active_priorities=[],
                pending_recommendations=[],
                dismissed_items=[],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(canon)
            db.flush() # UPDATEEEE

        # Use canon.py version which filters past events
        from app.services.canon import generate_recommendations as canon_generate_recommendations

        new_recs = canon_generate_recommendations(
            user=current_user,
            emails=unread_emails,
            events=upcoming_events,
            canonical_plan=canon,
            db=db,
            is_manual_refresh=True,
        )

        canon.last_ai_sync = datetime.now(timezone.utc)
        db.commit()

        return {
            "success": True,
            "recommendations_added": len(new_recs),
            "total_recommendations": len(canon.pending_recommendations or []),
            "last_sync": canon.last_ai_sync.isoformat(),
        }

    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content=e.detail)
    except Exception as e:
        logger.error(f"[Canon Refresh] Unexpected error: {e}", exc_info=True)
        raise HTTPException(500, f"Canon refresh failed: {str(e)}")


@api_router.post("/settings/canon-refresh")
async def update_canon_refresh_interval(
    body: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update canon auto-refresh interval.
    Allowed values (minutes): 0 (disabled), 1 (default), 15, 30, 60, 120, 360, 720, 1440.
    """
    interval_minutes = body.get("interval_minutes")
    if not isinstance(interval_minutes, int):
        raise HTTPException(400, "interval_minutes must be an integer")

    allowed = {0, 1, 15, 30, 60, 120, 360, 720, 1440}
    if interval_minutes not in allowed:
        raise HTTPException(400, f"Invalid interval. Allowed values: {sorted(allowed)} (minutes)")

    prefs = getattr(current_user, "preferences", None) or {}
    prefs["canon_refresh_interval_minutes"] = interval_minutes
    current_user.preferences = prefs
    flag_modified(current_user, "preferences")
    db.commit()

    logger.info(f"[Settings] User {current_user.id} set canon refresh to {interval_minutes} min")

    return {
        "canon_refresh_interval_minutes": interval_minutes,
        "enabled": interval_minutes > 0,
        "preferences": prefs,
    }


@api_router.post("/settings/timezone")
async def update_timezone(
    body: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update user's timezone preference.
    Body: {"timezone": "America/Los_Angeles"}
    """
    timezone_str = body.get("timezone")
    if not timezone_str:
        raise HTTPException(400, "timezone is required")
    try:
        import pytz

        pytz.timezone(timezone_str)
    except Exception:
        raise HTTPException(400, f"Invalid timezone: {timezone_str}")

    prefs = getattr(current_user, "preferences", None) or {}
    prefs["timezone"] = timezone_str
    current_user.preferences = prefs
    flag_modified(current_user, "preferences")
    db.commit()

    logger.info(f"[Settings] User {current_user.email} set timezone to {timezone_str}")

    return {"success": True, "timezone": timezone_str, "preferences": prefs}


@api_router.post("/debug/canon-worker/trigger")
async def debug_trigger_canon_worker(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    DEBUG ONLY: Manually trigger a canon worker refresh cycle.
    Requires user to have admin role or be in development mode.
    """
    # Security check - only allow in dev or for admins
    from app.core.settings import get_settings
    settings = get_settings()

    if settings.env != "development":
        # In production, require admin role
        if not getattr(current_user, "is_admin", False):
            raise HTTPException(status_code=403, detail="Admin only")

    logger.info(f"[DEBUG] User {current_user.id} manually triggering canon worker cycle")

    try:
        from app.workers.canon_worker import refresh_stale_canons
        import asyncio

        # Run the worker cycle synchronously
        await refresh_stale_canons()

        return {
            "status": "success",
            "message": "Canon worker cycle completed. Check logs for details."
        }
    except Exception as e:
        logger.error(f"[DEBUG] Manual worker trigger failed: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e)
        }


@api_router.get("/debug/canon-worker/status")
async def debug_canon_worker_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    DEBUG: Check if canon worker is running and when next run is scheduled.
    """
    from app.core.settings import get_settings
    settings = get_settings()

    if settings.env != "development":
        if not getattr(current_user, "is_admin", False):
            raise HTTPException(status_code=403, detail="Admin only")

    try:
        from app.workers.canon_worker import scheduler
        import os

        jobs = scheduler.get_jobs()
        canon_job = next((j for j in jobs if j.id == "canon_refresh_worker"), None)

        if not canon_job:
            return {
                "status": "not_running",
                "message": "Canon worker job not found in scheduler",
                "all_jobs": [j.id for j in jobs]
            }

        return {
            "status": "running",
            "next_run": str(canon_job.next_run_time) if canon_job.next_run_time else "Not scheduled",
            "interval_minutes": int(os.getenv("CANON_WORKER_INTERVAL_MINUTES", "15")),
            "trigger": str(canon_job.trigger),
            "all_jobs": [j.id for j in jobs]
        }
    except Exception as e:
        logger.error(f"[DEBUG] Failed to check worker status: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e)
        }


@api_router.post("/actions/log")
async def log_user_action(
    action: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Log a user action for workflow learning.
    """
    now_ts = datetime.now(timezone.utc)
    recent_action = (
        db.query(UserAction)
        .filter(
            UserAction.user_id == current_user.id,
            UserAction.timestamp >= now_ts - timedelta(minutes=10),
        )
        .order_by(UserAction.timestamp.desc())
        .first()
    )
    session_id = recent_action.session_id if recent_action else str(uuid.uuid4())

    tool = action.get("tool")
    action_type = action.get("action_type")
    action_data = action.get("action_data") or {}

    user_action = UserAction(
        user_id=current_user.id,
        tool=tool,
        action_type=action_type,
        action_data=action_data,
        task_id=action.get("task_id"),
        session_id=session_id,
    )

    db.add(user_action)
    db.commit()

    logger.info(f"[ACTION LOG] User {current_user.id}: {tool}.{action_type} (session {session_id})")
    return {"status": "logged", "session_id": session_id}


@api_router.post("/vscode/activity")
async def log_vscode_activity(
    activity_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Log VSCode activity with automatic summary generation.

    Expected payload:
    {
        "action_type": "code_edit" | "file_save" | "git_commit" | "debug_session",
        "data": {
            "files": ["path/to/file1.py", "path/to/file2.js"],
            "file_path": "path/to/file.py",  # Alternative to files array
            "language": "python",
            "lines_added": 10,
            "lines_deleted": 5,
            "commit_message": "Fixed bug in auth",
            "diff_preview": "...",
            "project_name": "my-project"
        },
        "session_id": "optional-session-id"
    }
    """
    now_ts = datetime.now(timezone.utc)

    # Get or create session ID
    session_id = activity_data.get("session_id")
    if not session_id:
        recent_action = (
            db.query(UserAction)
            .filter(
                UserAction.user_id == current_user.id,
                UserAction.tool == "vscode",
                UserAction.timestamp >= now_ts - timedelta(minutes=30),
            )
            .order_by(UserAction.timestamp.desc())
            .first()
        )
        session_id = recent_action.session_id if recent_action else str(uuid.uuid4())

    action_type = activity_data.get("action_type", "code_edit")
    data = activity_data.get("data", {})

    # Create user action
    user_action = UserAction(
        user_id=current_user.id,
        tool="vscode",
        action_type=action_type,
        action_data=data,
        session_id=session_id,
        timestamp=now_ts,
    )

    db.add(user_action)
    db.commit()
    db.refresh(user_action)

    logger.info(f"[VSCODE] User {current_user.id}: {action_type} (session {session_id})")

    # Generate activity summary using activity manager
    try:
        from app.services.activity_manager import update_user_activity

        # Create a summary text from the activity data
        summary_parts = []
        if action_type == "git_commit" and data.get("commit_message"):
            summary_parts.append(f"Committed: {data['commit_message']}")
        elif action_type == "code_edit":
            files = data.get("files", [])
            if not files and data.get("file_path"):
                files = [data["file_path"]]
            if files:
                file_names = [f.split('/')[-1] for f in files[:3]]
                summary_parts.append(f"Edited {', '.join(file_names)}")
            if data.get("lines_added") or data.get("lines_deleted"):
                summary_parts.append(f"+{data.get('lines_added', 0)}/-{data.get('lines_deleted', 0)} lines")
        elif action_type == "file_save":
            file_path = data.get("file_path") or (data.get("files", [""])[0] if data.get("files") else "")
            if file_path:
                summary_parts.append(f"Saved {file_path.split('/')[-1]}")

        content = " ".join(summary_parts) if summary_parts else f"VSCode: {action_type}"

        # Get room_id if user is in a room
        room_id = None
        user_room = db.query(UserORM).filter_by(id=current_user.id).first()
        if user_room and hasattr(user_room, 'room_id'):
            room_id = user_room.room_id

        status_updated, activity_logged, user_action = await update_user_activity(
            user_id=current_user.id,
            content=content,
            room_id=room_id,
            action_type=action_type,
            tool="vscode",
            db=db,
        )

        logger.info(
            f"[VSCODE Activity] User {current_user.id[:8]}: "
            f"status_updated={status_updated}, activity_logged={activity_logged}"
        )

        return {
            "status": "logged",
            "session_id": session_id,
            "activity_id": user_action.id if user_action else None,
            "status_updated": status_updated,
            "activity_logged": activity_logged,
        }

    except Exception as e:
        logger.error(f"[VSCODE Activity] Failed to generate summary: {e}", exc_info=True)
        # Still return success - the action was logged even if summary failed
        return {
            "status": "logged",
            "session_id": session_id,
            "activity_id": user_action.id,
            "error": "Summary generation failed",
        }


@api_router.get("/canon/load")
async def load_canonical_plan(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Load canonical plan WITHOUT any AI regeneration or sync.
    """
    logger.info(f"[Canon Load] User {current_user.id} loading canonical plan (no sync)")

    canon = db.query(UserCanonicalPlan).filter(
        UserCanonicalPlan.user_id == current_user.id
    ).first()

    if not canon:
        canon = UserCanonicalPlan(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            approved_timeline={
                "1d": {"urgent": [], "normal": []},
                "7d": {"urgent": [], "normal": []},
                "28d": {"urgent": [], "normal": []},
            },
            active_priorities=[],
            pending_recommendations=[],
            dismissed_items=[],
        )
        db.add(canon)
        db.commit()
        logger.info("[Canon Load] Created empty canon for new user")

    completed_items = db.query(CompletedBriefItem).filter(
        CompletedBriefItem.user_id == current_user.id
    ).all()
    completed_sigs = {item.item_signature for item in completed_items if item.item_signature}

    filtered = _filter_canon_with_completed(canon, completed_sigs)
    total_items = count_timeline_items(canon.approved_timeline or {})
    logger.info(f"[CANON] User {current_user.id}: {total_items} items in canon, filtering {len(completed_sigs)} completed")

    return {
        "canonical": filtered,
        "recommendations": filtered["recommendations"],
        "last_sync": canon.last_ai_sync.isoformat() if canon.last_ai_sync else None,
        "cached": True,
        "syncing": False,
    }


@api_router.post("/brief/recommendations/accept")
def accept_recommendation(
    request: Request,
    rec_data: dict,
    db: Session = Depends(get_db),
):
    """
    Accept an AI recommendation - move it to canonical plan.
    Body: {"recommendation_index": 0}
    """
    user = require_user(request, db)
    plan = get_or_create_canonical_plan(user.id, db)

    rec_index = rec_data.get("recommendation_index")
    recommendations = plan.pending_recommendations or []

    if rec_index is None or rec_index < 0 or rec_index >= len(recommendations):
        raise HTTPException(status_code=400, detail="Invalid recommendation index")

    rec = recommendations[rec_index]
    timeframe = rec.get("timeframe")
    section = rec.get("section")
    item = rec.get("item")

    if timeframe and section and item:
        title = item.get("title") or item.get("subject") or ""
        sig = item.get("signature") or rec.get("signature") or generate_timeline_signature(timeframe, section, title)
        item["signature"] = sig
        rec["signature"] = sig
        approved_timeline = plan.approved_timeline or {}
        approved_timeline.setdefault(timeframe, {})
        approved_timeline[timeframe].setdefault(section, [])
        approved_timeline[timeframe][section].append(item)
        plan.approved_timeline = approved_timeline
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(plan, "approved_timeline")

    recommendations.pop(rec_index)
    plan.pending_recommendations = recommendations
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(plan, "pending_recommendations")
    plan.last_user_modification = datetime.now(timezone.utc)
    db.commit()

    logger.info(f"[Canon] User accepted recommendation: {item.get('title') if item else ''}")

    # Mentions: notify and create task for mentioned users
    try:
        handle_mention_notifications_and_tasks(
            task_data=item or {},
            current_user=user,
            signature=item.get("signature") if item else sig,
            action="task_created",
            db=db,
        )
    except Exception as e:
        logger.error(f"[PROACTIVE] Error handling mentions on accept: {e}")

    return {"status": "accepted"}


@api_router.post("/brief/recommendations/dismiss")
def dismiss_recommendation(
    request: Request,
    rec_data: dict,
    db: Session = Depends(get_db),
):
    """
    Dismiss an AI recommendation - won't suggest again.
    Body: {"recommendation_index": 0}
    """
    user = require_user(request, db)
    plan = get_or_create_canonical_plan(user.id, db)

    rec_index = rec_data.get("recommendation_index")
    recommendations = plan.pending_recommendations or []

    if rec_index is None or rec_index < 0 or rec_index >= len(recommendations):
        raise HTTPException(status_code=400, detail="Invalid recommendation index")

    rec = recommendations[rec_index]
    item = rec.get("item")

    dismissed = plan.dismissed_items or []
    if item:
        if not item.get("signature"):
            item["signature"] = rec.get("signature") or generate_item_signature(item)
        dismissed.append(item)
    plan.dismissed_items = dismissed

    recommendations.pop(rec_index)
    plan.pending_recommendations = recommendations
    plan.last_user_modification = datetime.now(timezone.utc)
    db.commit()

    logger.info(f"[Canon] User dismissed recommendation: {item.get('title') if item else ''}")

    return {"status": "dismissed"}


@api_router.post("/debug/run-deadline-check")
def run_deadline_check(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Manually trigger approaching-deadline proactive messages for the current user.
    """
    user = require_user(request, db)
    check_approaching_deadlines_for_user(user.id, db)
    return {"status": "ok"}


@api_router.post("/brief/items/complete")
async def mark_item_complete(
    request: Request,
    item_data: dict,
    db: Session = Depends(get_db),
):
    """
    Mark a brief item as completed.
    Body: {"title": "...", "source_id": "...", "source_type": "email|calendar|timeline", "signature": "..."}
    """
    import uuid
    from app.services.canon import generate_item_signature

    user = require_user(request, db)

    # Use centralized signature generation for consistency
    signature = item_data.get("signature") or generate_item_signature(item_data)

    logger.info(f"[COMPLETE] User {user.id}: marking signature {signature} complete")
    logger.info(f"[COMPLETE] Item: source_type={item_data.get('source_type')}, source_id={item_data.get('source_id')}, title='{item_data.get('title', 'N/A')}'")
    try:
        logger.info(f"[COMPLETE] Request body: {await request.json()}")
    except Exception:
        pass

    existing = db.query(CompletedBriefItem).filter(
        CompletedBriefItem.user_id == user.id,
        CompletedBriefItem.item_signature == signature,
    ).first()

    if existing:
        if existing.action != "completed":
            existing.action = "completed"
            existing.completed_at = datetime.now(timezone.utc)
            db.add(existing)
            db.commit()
        return {"status": "already_completed"}

    # Remove from canon/recs immediately
    plan = get_or_create_canonical_plan(user.id, db)
    prune_plan_item(plan, signature)
    db.add(plan)

    completed = CompletedBriefItem(
        id=str(uuid.uuid4()),
        user_id=user.id,
        item_signature=signature,
        source_type=item_data.get("source_type"),
        source_id=item_data.get("source_id"),
        action="completed",
        item_title=item_data.get("title"),
        item_description=item_data.get("description") or item_data.get("detail"),
        timeframe=item_data.get("timeframe"),
        section=item_data.get("section"),
        raw_item=item_data,
    )

    db.add(completed)
    plan.last_user_modification = datetime.now(timezone.utc)
    db.add(plan)
    db.commit()
    logger.info(f"[COMPLETE] Saved to DB with signature: {completed.item_signature}")
    logger.info(f"[COMPLETE] Item '{item_data.get('title')}' marked complete for user {user.email}")

    # Mark email as read in Gmail to prevent worker from re-fetching it
    source_type = item_data.get("source_type", "").lower()
    source_id = item_data.get("source_id")

    if source_type == "email" and source_id:
        try:
            from app.services.gmail import mark_email_as_read
            success = mark_email_as_read(user, source_id, db)
            if success:
                logger.info(f"[COMPLETE] ✅ Marked email {source_id} as read in Gmail")
            else:
                logger.warning(f"[COMPLETE] ⚠️  Could not mark email {source_id} as read in Gmail (non-critical)")
        except Exception as gmail_err:
            # Don't fail the completion if Gmail update fails - it's just an optimization
            logger.warning(f"[COMPLETE] Gmail mark-as-read failed (non-critical): {gmail_err}")

    # Hard-remove from canon timeline/priorities/recs as a safety net
    removed = hard_remove_signature_from_canon(plan, {signature})
    if removed:
        db.add(plan)
        db.commit()
        logger.info(f"[COMPLETE] Canon updated - item permanently removed")
    else:
        logger.warning(f"[COMPLETE] Item not found in canon when removing: {signature}")

    # Mentions: notify only (no new tasks on completion)
    try:
        handle_mention_notifications_and_tasks(
            task_data=item_data,
            current_user=user,
            signature=signature,
            action="task_completed",
            db=db,
        )
    except Exception as e:
        logger.error(f"[PROACTIVE] Error handling mentions on completion: {e}")

    return {"status": "completed", "signature": signature}


@api_router.post("/brief/items/update")
async def update_brief_item(
    request: Request,
    signature: str = Body(...),
    title: Optional[str] = Body(None),
    description: Optional[str] = Body(None),
    priority: Optional[str] = Body(None),
    due_time: Optional[str] = Body(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update a canonical plan item by signature.
    """
    canonical = get_or_create_canonical_plan(current_user.id, db)
    timeline = canonical.approved_timeline or {}
    found = False

    timeframe_keys = [
        ("1d", ["1d", "today"]),
        ("7d", ["7d", "this_week", "week"]),
        ("28d", ["28d", "this_month", "month"]),
    ]
    # 2-tier priority system + legacy support
    section_keys = ["urgent", "normal", "critical", "high", "high_priority", "medium", "low"]

    for canon_tf, aliases in timeframe_keys:
        if found:
            break
        # pick the key present in timeline if exists
        tf_key = None
        for alias in aliases:
            if alias in timeline:
                tf_key = alias
                break
        if tf_key is None:
            tf_key = canon_tf if canon_tf in timeline else None
        if tf_key is None:
            continue

        for sec in section_keys:
            items = timeline.get(tf_key, {}).get(sec, [])
            for idx, item in enumerate(list(items)):
                sig = item.get("signature") or generate_item_signature(item)
                if sig != signature:
                    continue

                # Update fields
                if title:
                    item["title"] = title
                if description:
                    item["description"] = description
                if due_time:
                    item["due_time"] = due_time

                if priority and priority in section_keys and priority != sec:
                    # move to new section
                    items.pop(idx)
                    timeline.setdefault(tf_key, {}).setdefault(priority, []).append(item)
                else:
                    # ensure list updated in place
                    items[idx] = item

                found = True
                break
            if found:
                break

    if not found:
        raise HTTPException(status_code=404, detail="Item not found")

    canonical.approved_timeline = timeline
    canonical.last_user_modification = datetime.now(timezone.utc)
    db.add(canonical)
    db.commit()

    logger.info(f"[Brief] Updated item {signature} for user {current_user.id}")
    return {"status": "updated", "signature": signature}


@api_router.post("/brief/items/delete")
async def delete_plan_item(
    request: Request,
    item_data: dict,
    db: Session = Depends(get_db),
):
    """
    Permanently delete an item from canon/recs and log it as deleted.
    Body: {"title": "...", "source_id": "...", "source_type": "email|calendar|timeline", "signature": "..."}
    """
    import uuid
    from app.services.canon import generate_item_signature

    user = require_user(request, db)
    plan = get_or_create_canonical_plan(user.id, db)

    # Use centralized signature generation for consistency
    signature = item_data.get("signature") or generate_item_signature(item_data)

    logger.info(f"[DELETE] User {user.id}: deleting signature {signature}")
    logger.info(f"[DELETE] Item: source_type={item_data.get('source_type')}, source_id={item_data.get('source_id')}, title='{item_data.get('title', 'N/A')}'")
    try:
        logger.info(f"[DELETE] Request body: {await request.json()}")
    except Exception:
        pass

    # CRITICAL FIX: Extract title from timeline if not provided in request
    # This is needed for the learning system to work (tracks deletions by title)
    if not item_data.get("title"):
        # Search through timeline to find the item by signature
        timeline = plan.approved_timeline or {}
        for timeframe in ['1d', '7d', '28d']:
            for section in ['urgent', 'normal']:
                items = timeline.get(timeframe, {}).get(section, [])
                if isinstance(items, list):
                    for item in items:
                        if item.get("signature") == signature or generate_item_signature(item) == signature:
                            item_data["title"] = item.get("title")
                            item_data["detail"] = item_data.get("detail") or item.get("detail")
                            logger.info(f"[DELETE] Extracted title from timeline: '{item_data['title']}'")
                            break
                    if item_data.get("title"):
                        break
            if item_data.get("title"):
                break

    prune_plan_item(plan, signature)

    existing = db.query(CompletedBriefItem).filter(
        CompletedBriefItem.user_id == user.id,
        CompletedBriefItem.item_signature == signature,
    ).first()

    if existing:
        existing.action = "deleted"
        existing.completed_at = datetime.now(timezone.utc)
        existing.raw_item = existing.raw_item or item_data
        existing.item_title = existing.item_title or item_data.get("title")
        existing.item_description = existing.item_description or item_data.get("description") or item_data.get("detail")
        existing.timeframe = existing.timeframe or item_data.get("timeframe")
        existing.section = existing.section or item_data.get("section")
        db.add(existing)
    else:
        deleted_item = CompletedBriefItem(
            id=str(uuid.uuid4()),
            user_id=user.id,
            item_signature=signature,
            source_type=item_data.get("source_type"),
            source_id=item_data.get("source_id"),
            action="deleted",
            item_title=item_data.get("title"),
            item_description=item_data.get("description") or item_data.get("detail"),
            timeframe=item_data.get("timeframe"),
            section=item_data.get("section"),
            raw_item=item_data,
            completed_at=datetime.now(timezone.utc),
        )
        db.add(deleted_item)

    plan.last_user_modification = datetime.now(timezone.utc)
    db.add(plan)
    db.commit()

    # Hard-remove from canon timeline/priorities/recs as a safety net
    removed = hard_remove_signature_from_canon(plan, {signature})
    if removed:
        db.add(plan)
        db.commit()
        logger.info(f"[DELETE] Canon updated - item permanently removed")
    else:
        logger.warning(f"[DELETE] Item not found in canon when removing: {signature}")

    logger.info(f"[DELETE] Saved to DB with signature: {signature}")
    logger.info(f"[DELETE] Item '{item_data.get('title')}' deleted for user {user.email}")
    return {"status": "deleted", "signature": signature}


@api_router.get("/brief/items/history")
def get_items_history(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    action: str = "all",
    db: Session = Depends(get_db),
):
    """
    Return completed/deleted brief item history.
    """
    user = require_user(request, db)
    q = db.query(CompletedBriefItem).filter(CompletedBriefItem.user_id == user.id)
    if action in ["completed", "deleted"]:
        q = q.filter(CompletedBriefItem.action == action)
    q = q.order_by(CompletedBriefItem.completed_at.desc())

    rows = q.offset(offset).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "action": r.action or "completed",
            "signature": r.item_signature,
            "title": r.item_title,
            "description": r.item_description,
            "timeframe": r.timeframe,
            "section": r.section,
            "created_at": r.completed_at.isoformat() if r.completed_at else None,
            "raw_item": r.raw_item,
        })

    return {"items": items, "has_more": has_more}


@api_router.delete("/brief/items/complete")
def mark_item_incomplete(
    request: Request,
    item_data: dict,
    db: Session = Depends(get_db),
):
    """
    Unmark a brief item (mark as incomplete).
    Body: {"title": "...", "source_id": "..."}
    """
    user = require_user(request, db)

    signature = generate_item_signature(item_data)

    completed = db.query(CompletedBriefItem).filter(
        CompletedBriefItem.user_id == user.id,
        CompletedBriefItem.item_signature == signature,
    ).first()

    if completed:
        db.delete(completed)
        db.commit()
        logger.info(f"[Brief] Item unmarked: {item_data.get('title')} for user {user.email}")
        return {"status": "unmarked"}

    return {"status": "not_found"}


@api_router.get("/brief/filtered-events")
def get_filtered_events(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Show user which recurring events are being auto-filtered and why.

    CRITICAL TWO-LEVEL SYSTEM:
    - Individual deletions are tracked by SIGNATURE (each unique event deleted separately)
    - Learning/filtering is by TITLE (if you delete 3+ events with same title, filter all future ones)
    """
    from app.services.canon import analyze_recurring_event_pattern

    user = require_user(request, db)

    # Get all unique titles from last 30 days
    titles = db.query(CompletedBriefItem.item_title).filter(
        CompletedBriefItem.user_id == user.id,
        CompletedBriefItem.item_title.isnot(None),
        CompletedBriefItem.completed_at >= datetime.now(timezone.utc) - timedelta(days=30)
    ).distinct().all()

    filtered_events = []

    for (title,) in titles:
        pattern = analyze_recurring_event_pattern(user.id, title, db)
        if pattern["should_filter"]:
            filtered_events.append({
                "title": title,
                "reason": pattern["reason"],
                "stats": pattern["stats"]
            })

    return {"filtered_events": filtered_events}


@api_router.post("/brief/unfilter-event")
def unfilter_event(
    request: Request,
    payload: dict,
    db: Session = Depends(get_db)
):
    """
    Allow user to re-enable a filtered recurring event.
    Stores preference in user preferences.
    """
    user = require_user(request, db)
    title = payload.get("title")

    if not title:
        return {"success": False, "error": "Title required"}

    # Get user preferences
    prefs = user.preferences or {}

    # Add to whitelist
    whitelisted = prefs.get("whitelisted_recurring_events", [])
    if title not in whitelisted:
        whitelisted.append(title)

    prefs["whitelisted_recurring_events"] = whitelisted
    user.preferences = prefs
    flag_modified(user, "preferences")
    db.commit()

    logger.info(f"[Brief] User {user.id[:8]} whitelisted recurring event: {title}")

    return {"success": True, "whitelisted": title}


@api_router.delete("/brief/unfilter-event")
def remove_whitelist_event(
    request: Request,
    payload: dict,
    db: Session = Depends(get_db)
):
    """
    Remove event from whitelist (allow it to be auto-filtered again).
    """
    user = require_user(request, db)
    title = payload.get("title")

    if not title:
        return {"success": False, "error": "Title required"}

    # Get user preferences
    prefs = user.preferences or {}
    whitelisted = prefs.get("whitelisted_recurring_events", [])

    if title in whitelisted:
        whitelisted.remove(title)
        prefs["whitelisted_recurring_events"] = whitelisted
        user.preferences = prefs
        flag_modified(user, "preferences")
        db.commit()

        logger.info(f"[Brief] User {user.id[:8]} removed whitelist for: {title}")
        return {"success": True, "removed": title}

    return {"success": False, "error": "Event not in whitelist"}


@api_router.post("/debug/reset-timeline")
def reset_timeline_debug(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    DEBUG ONLY: Reset timeline and deletion history.
    Allows testing the 3-strike system from scratch.
    """
    user = require_user(request, db)

    logger.warning("=" * 80)
    logger.warning(f"[DEBUG RESET] 🔄 STARTING RESET for user {user.email}")
    logger.warning("=" * 80)

    try:
        # 1. Clear ALL completion/deletion history
        deleted_count = db.query(CompletedBriefItem).filter(
            CompletedBriefItem.user_id == user.id
        ).delete()
        logger.warning(f"[DEBUG RESET] ✅ Deleted {deleted_count} completion/deletion records")

        # 2. Clear timeline cache
        plan = db.query(UserCanonicalPlan).filter(
            UserCanonicalPlan.user_id == user.id
        ).first()

        if plan:
            plan.approved_timeline = {
                "1d": {"urgent": [], "normal": []},
                "7d": {"urgent": [], "normal": []},
                "28d": {"urgent": [], "normal": []}
            }
            plan.updated_at = datetime.now(timezone.utc)
            flag_modified(plan, "approved_timeline")
            logger.warning("[DEBUG RESET] ✅ Cleared timeline cache")

        # 3. Clear any filtered/whitelisted events from preferences
        prefs = user.preferences or {}
        old_filtered = prefs.get('filtered_recurring_events', [])
        old_whitelisted = prefs.get('whitelisted_recurring_events', [])

        if old_filtered:
            logger.warning(f"[DEBUG RESET] Clearing filters: {old_filtered}")
        if old_whitelisted:
            logger.warning(f"[DEBUG RESET] Clearing whitelist: {old_whitelisted}")

        prefs['whitelisted_recurring_events'] = []
        prefs['filtered_recurring_events'] = []
        user.preferences = prefs
        flag_modified(user, "preferences")
        logger.warning("[DEBUG RESET] ✅ Cleared filter lists")

        db.commit()

        logger.warning("=" * 80)
        logger.warning(f"[DEBUG RESET] ✅ COMPLETE for {user.email}")
        logger.warning(f"[DEBUG RESET] Deleted {deleted_count} history items")
        logger.warning("[DEBUG RESET] Timeline will regenerate within 1 minute")
        logger.warning("=" * 80)

        return {
            "status": "success",
            "message": "Timeline and history reset successfully",
            "deleted_items": deleted_count,
            "next_steps": "Timeline will regenerate on next refresh (within 1 minute)"
        }

    except Exception as e:
        db.rollback()
        logger.error(f"[Debug Reset] Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/debug/timeline-logs")
def get_timeline_logs(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Download the timeline diagnostic log file.
    Only accessible to admins.
    """
    from fastapi.responses import FileResponse

    log_file = os.path.join(
        os.path.dirname(__file__),
        'logs',
        'timeline_diagnostics.log'
    )

    if not os.path.exists(log_file):
        raise HTTPException(status_code=404, detail="Log file not found")

    return FileResponse(
        log_file,
        media_type='text/plain',
        filename='timeline_diagnostics.log'
    )


@api_router.get("/debug/timeline-logs/tail")
def get_timeline_logs_tail(
    request: Request,
    lines: int = 500,
    db: Session = Depends(get_db)
):
    """
    Get last N lines of timeline diagnostic logs.
    Useful for quick checking without downloading entire file.
    """
    log_file = os.path.join(
        os.path.dirname(__file__),
        'logs',
        'timeline_diagnostics.log'
    )

    if not os.path.exists(log_file):
        return {"logs": "", "message": "Log file not found", "total_lines": 0, "showing_lines": 0}

    try:
        # Read last N lines
        with open(log_file, 'r') as f:
            all_lines = f.readlines()
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines

        return {
            "logs": ''.join(last_lines),
            "total_lines": len(all_lines),
            "showing_lines": len(last_lines)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/debug/timeline-logs/clear")
def clear_timeline_logs(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Clear the timeline diagnostic log file.
    Useful for starting fresh before a test.
    """
    log_file = os.path.join(
        os.path.dirname(__file__),
        'logs',
        'timeline_diagnostics.log'
    )

    if os.path.exists(log_file):
        os.remove(log_file)
        logger.warning(f"[Debug] Timeline log file cleared anonymously")
        return {"status": "cleared", "message": "Log file deleted"}

    return {"status": "not_found", "message": "Log file didn't exist"}


@api_router.get("/brief/check-deletion-pattern")
def check_deletion_pattern(
    request: Request,
    title: str,
    db: Session = Depends(get_db)
):
    """
    Check if an item's deletion pattern triggers the auto-filter threshold.
    Called after each deletion to see if we should prompt user.
    """
    from app.services.canon import analyze_recurring_event_pattern

    user = require_user(request, db)

    # Analyze deletion pattern
    pattern = analyze_recurring_event_pattern(
        user_id=user.id,
        item_title=title,
        db=db
    )

    # Determine if we should suggest or prompt
    deletion_rate = pattern["stats"]["deletion_rate"]
    deleted_count = pattern["stats"]["deleted_count"]

    return {
        "should_prompt": pattern["should_filter"],  # True if ≥3 deletions + ≥80% rate
        "should_suggest": deletion_rate >= 0.6 and deleted_count >= 3 and not pattern["should_filter"],  # True if ≥60% rate but not yet auto-filtering
        "deletion_count": deleted_count,
        "completion_count": pattern["stats"]["completed_count"],
        "total_count": pattern["stats"]["total_occurrences"],
        "deletion_rate": deletion_rate,
        "message": pattern.get("reason", ""),
        "suggestion": pattern.get("suggestion"),
        "title": title
    }


@api_router.post("/brief/filter-event")
def add_to_filter_list(
    request: Request,
    payload: dict,
    db: Session = Depends(get_db)
):
    """
    Add or remove an event title from the auto-filter list.
    When filtered=true, future events with this title won't appear in timeline.
    """
    user = require_user(request, db)

    title = payload.get("title")
    should_filter = payload.get("filter", True)

    if not title:
        raise HTTPException(status_code=400, detail="Title is required")

    # Get or create preferences
    prefs = user.preferences or {}
    filtered_events = prefs.get("filtered_recurring_events", [])

    if should_filter:
        # Add to filter list
        if title not in filtered_events:
            filtered_events.append(title)
            logger.info(f"[Filter] Added '{title}' to filter list for user {user.email}")
    else:
        # Remove from filter list (user wants to see it again)
        if title in filtered_events:
            filtered_events.remove(title)
            logger.info(f"[Filter] Removed '{title}' from filter list for user {user.email}")

    prefs["filtered_recurring_events"] = filtered_events
    user.preferences = prefs
    flag_modified(user, "preferences")

    db.commit()

    return {
        "status": "success",
        "title": title,
        "filtered": should_filter,
        "filtered_events": filtered_events,
        "message": f"{'Hiding' if should_filter else 'Showing'} all '{title}' events"
    }


@api_router.get("/brief/get-filtered-events")
def get_filtered_events_list(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Get list of events currently being auto-filtered for this user.
    Shows deletion stats for each filtered event.
    """
    from app.services.canon import analyze_recurring_event_pattern

    user = require_user(request, db)

    prefs = user.preferences or {}
    filtered_events = prefs.get("filtered_recurring_events", [])

    # Get deletion stats for each filtered event
    details = []
    for title in filtered_events:
        pattern = analyze_recurring_event_pattern(
            user_id=user.id,
            item_title=title,
            db=db
        )

        details.append({
            "title": title,
            "deletion_count": pattern["stats"]["deleted_count"],
            "total_count": pattern["stats"]["total_occurrences"],
            "deletion_rate": pattern["stats"]["deletion_rate"]
        })

    return {
        "filtered_events": details,
        "count": len(filtered_events)
    }


@api_router.get("/assistant/chat")
def get_personal_assistant_chat(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Get (or create) the user's personal assistant chat and room.
    """
    user = require_user(request, db)

    personal_room = get_or_create_personal_room(user.id, db)
    assistant_chat = get_or_create_personal_assistant_chat(user.id, db)

    return {
        "room_id": personal_room.id,
        "chat_id": assistant_chat.id,
        "room_name": personal_room.name,
        "chat_name": assistant_chat.name,
        "is_personal": True,
    }



@api_router.options("/brief/debug-context")
def debug_context_options():
    return {}

@api_router.get("/brief/debug-context")
def get_debug_context(request: Request, db: Session = Depends(get_db)):
    """
    Return raw context that AI sees for debugging.
    """
    user = require_user(request, db)
    
    from app.services.gmail import fetch_unread_emails
    from app.services.calendar import fetch_upcoming_events
    from models import Message, RoomMember, User
    from datetime import timedelta
    
    # Fetch same data AI sees
    emails = fetch_unread_emails(user, db)
    calendar_events = fetch_upcoming_events(user, db)
    
    # Get team activity
    room_ids = db.query(RoomMember.room_id).filter(
        RoomMember.user_id == user.id
    ).all()
    room_ids = [r[0] for r in room_ids]
    
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    messages = db.query(Message, User).join(
        User, Message.sender_id == User.id
    ).filter(
        Message.room_id.in_(room_ids),
        Message.created_at >= since,
        Message.sender_id != user.id
    ).order_by(Message.created_at.desc()).limit(50).all()
    
    # Format exactly as AI sees it
    email_context = "\n".join([
        f"- From: {e.get('from', 'Unknown')}, Subject: {e.get('subject', 'No subject')}, Date: {e.get('date', 'Unknown')}, Snippet: {e.get('snippet', '')[:100]}"
        for e in emails[:20]
    ]) if emails else "No unread emails"
    
    calendar_context = "\n".join([
        f"- {e.get('summary', 'Untitled')} at {e.get('start_time', e.get('start', 'TBD'))} ({e.get('location', 'No location')})"
        for e in calendar_events[:15]
    ]) if calendar_events else "No upcoming meetings"
    
    team_activity_context = ""
    if messages:
        activity_by_person = {}
        for msg, sender_user in messages:
            sender = sender_user.name or sender_user.email.split('@')[0]
            if sender not in activity_by_person:
                activity_by_person[sender] = []
            activity_by_person[sender].append(msg.content[:200])
        
        team_activity_context = "\n\n".join([
            f"{sender}:\n" + "\n".join([f"  - {msg}" for msg in msgs[:3]])
            for sender, msgs in list(activity_by_person.items())[:10]
        ])
    
    return {
        "user_email": user.email,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_sources": {
            "emails_count": len(emails),
            "calendar_events_count": len(calendar_events),
            "team_messages_count": len(messages)
        },
        "raw_context": {
            "emails": email_context,
            "calendar": calendar_context,
            "team_activity": team_activity_context or "No recent team activity"
        },
        "raw_data": {
            "emails": emails[:20],
            "calendar_events": calendar_events[:15],
            "team_messages": [
                {
                    "sender": sender_user.name or sender_user.email,
                    "content": msg.content,
                    "created_at": msg.created_at.isoformat()
                }
                for msg, sender_user in messages[:10]
            ]
        }
    }

# backend/main.py

@app.post("/admin/backfill-signatures")
async def backfill_signatures(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """One-time script to add signatures to existing canonical plan items"""
    
    # Optional: Add auth check
    # if current_user.email != "severin@parallelos.ai":
    #     raise HTTPException(403, "Admin only")
    
    import hashlib
    from sqlalchemy.orm.attributes import flag_modified
    
    def generate_signature(timeframe: str, priority: str, title: str) -> str:
        canonical_string = f"{timeframe}|{priority}|{title.strip().lower()}"
        return hashlib.md5(canonical_string.encode()).hexdigest()
    
    try:
        plans = db.query(UserCanonicalPlan).all()
        total_updated = 0
        total_items_fixed = 0
        
        for plan in plans:
            if not plan.approved_timeline:
                continue
            
            timeline = plan.approved_timeline
            updated = False
            items_fixed = 0
            
            for timeframe in ['1d', '7d', '28d']:
                if timeframe not in timeline:
                    continue
                
                for priority in ['critical', 'high', 'medium', 'low']:
                    if priority not in timeline[timeframe]:
                        continue
                    
                    items = timeline[timeframe][priority]
                    
                    for item in items:
                        if not item.get('signature'):
                            title = item.get('title', '')
                            signature = generate_signature(timeframe, priority, title)
                            item['signature'] = signature
                            updated = True
                            items_fixed += 1
                            logger.info(f"✅ Added signature: {title[:50]} -> {signature}")
            
            if updated:
                flag_modified(plan, 'approved_timeline')
                db.commit()
                total_updated += 1
                total_items_fixed += items_fixed
                logger.info(f"✅ Updated canonical plan for user {plan.user_id}: {items_fixed} items")
        
        return {
            "success": True,
            "plans_updated": total_updated,
            "items_fixed": total_items_fixed,
            "message": f"Backfilled {total_items_fixed} items across {total_updated} plans"
        }
        
    except Exception as e:
        logger.error(f"❌ Backfill error: {e}")
        db.rollback()
        raise HTTPException(500, f"Backfill failed: {str(e)}")









@app.on_event("startup")
async def on_startup():
    """Startup tasks for both SQLite and Postgres"""
    _log_startup_marker()
    db_check_start = time.perf_counter()
    try:
        if "sqlite" in str(engine.url).lower():
            logger.info("[Startup] SQLite detected - creating tables")
            try:
                Base.metadata.create_all(bind=engine)
            except Exception as exc:
                logger.warning(
                    "[Startup] SQLite schema init skipped (incompatible types): %s",
                    exc,
                )
        else:
            logger.info("[Startup] Using Postgres - skipping create_all")
    except Exception:
        _record_timing("db_init_ms", db_check_start)
        logger.error("[Startup] ❌ Database init failed", exc_info=True)
        raise
    _record_timing("db_init_ms", db_check_start)
    _log_startup_timings()
    try:
        from app.workers.canon_worker import start_canon_worker

        start_canon_worker()
        logger.info("[Startup] ✅ Canon worker started successfully")
    except Exception as e:
        logger.error(f"[Startup] ❌ Failed to start canon worker: {e}", exc_info=True)

    try:
        from app.workers.notification_worker import start_notification_worker

        start_notification_worker()
        logger.info("[Startup] ✅ Notification worker started successfully")
    except Exception as e:
        logger.error(f"[Startup] ❌ Failed to start notification worker: {e}", exc_info=True)

    logger.info(f"[Startup] ===== SERVER READY (Database: {engine.url.drivername}) =====")

_router_include_start = time.perf_counter()
api_router.include_router(org_graph.router)
api_router.include_router(org_stats.router)
api_router.include_router(outbound.router)
api_router.include_router(demo.router)

# Admin routes now use centralized auth from app.api.dependencies.auth
api_router.include_router(admin.router)
api_router.include_router(oauth_router_module.router)  # OAuth 2.1 PKCE endpoints
app.include_router(api_router)
app.include_router(api_v1_router)
app.include_router(graphs_router.router, prefix="/api/v1")
_record_timing("router_inclusion_ms", _router_include_start)
_record_timing("module_import_ms", _IMPORT_START)
