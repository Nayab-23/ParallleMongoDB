from datetime import datetime, timezone
import difflib
import json
import re
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, validator
from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db, require_workspace_member
from config import config
from models import AgentEditHistory, AgentProfile, ChatInstance, Message, Task, User, UserAction
from app.services.cache import TTLCache
from app.services.code_index import index_codebase, search_code_index
from app.services.rag import get_relevant_context

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_REQUEST_LEN = 8000
MAX_DIFF_LEN = 200_000
MAX_MESSAGE_SUMMARY_LEN = 500
MAX_MESSAGE_BODY_LEN = 4000
MAX_CONTEXT_MESSAGES = 20
MAX_FILE_CONTENT_LEN = 12000
MAX_FILE_CONTENT_HARD = 200_000
MAX_TOTAL_FILE_CONTENT = 400_000
MAX_FILE_CONTEXTS = 20
MAX_SEARCH_RESULTS = 200
MAX_COMMAND_OUTPUT_LEN = 4000
MAX_COMMAND_LEN = 400
MAX_COMMANDS = 6
MAX_COMMAND_RESULTS = 10
MAX_DIFF_SNIPPET_LEN = 6000
MAX_INLINE_PREFIX_LEN = 4000
MAX_INLINE_SUFFIX_LEN = 2000
MAX_INLINE_COMPLETIONS = 5
BLOCKED_PATH_SEGMENTS = {"__pycache__", ".git", "node_modules", ".venv", ".vscode"}
BLOCKED_EXTENSIONS = {".pyc", ".pyo", ".pyd", ".class", ".o", ".so", ".dll", ".dylib", ".exe"}
ALLOWED_NEW_FILE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".html",
    ".css",
    ".scss",
}
VSCODE_SYSTEM_PROMPT = (
    "You are the Parallel assistant. Be concise and helpful. "
    "If repository context is provided, use it to answer questions and do not claim you lack access. "
    "If the context is insufficient, ask the user to open the relevant files."
)
VSCODE_AGENT_SYSTEM_PROMPT = (
    "You are the Parallel code agent. Return ONLY valid JSON with keys "
    "'plan' (array of short strings), "
    "'edits' (array of objects with 'filePath', 'newText', optional 'diff', "
    "optional 'mode' (replace|diff|search_replace|insert), optional 'description', "
    "optional 'range', and optional 'searchReplace'), "
    "and 'commands' (array of objects with 'command' plus optional 'cwd', 'purpose', 'when'). "
    "Use relative file paths and keep edits scoped to the provided repo files. "
    "If no changes are needed, return empty edits and commands arrays."
)
VSCODE_INLINE_SYSTEM_PROMPT = (
    "You are a code completion engine. Return ONLY the code continuation. "
    "Do not include markdown, backticks, explanations, or the original prompt."
)
VSCODE_PLAN_SYSTEM_PROMPT = (
    "You are the Parallel code planner. Return ONLY valid JSON with keys "
    "'plan' (array of short strings), "
    "'files_to_read' (array of relative file paths), "
    "'files_to_modify' (array of relative file paths), "
    "'search_queries' (array of short strings), "
    "and optional 'reasoning'. "
    "Use relative paths from the allowed file list."
)
VSCODE_EXPLAIN_SYSTEM_PROMPT = (
    "You explain code for developers. Be concise, precise, and actionable."
)
VSCODE_TEST_SYSTEM_PROMPT = (
    "You generate tests for code. Return ONLY the test code, without markdown."
)

INLINE_COMPLETION_CACHE = TTLCache(ttl_seconds=20, max_items=1024)
PROPOSE_CACHE = TTLCache(ttl_seconds=120, max_items=256)
PLAN_CACHE = TTLCache(ttl_seconds=180, max_items=256)
EXPLAIN_CACHE = TTLCache(ttl_seconds=300, max_items=256)

SENSITIVE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"pat_[A-Za-z0-9]+\.[A-Za-z0-9]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{30,}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),
]


def _truncate(text: Optional[str], max_len: int) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len]


def _safe_json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True, default=str)


def _redact_sensitive_text(text: str) -> str:
    if not text:
        return ""
    redacted = text
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _filter_completion_items(items: List[str]) -> List[str]:
    return [_redact_sensitive_text(item) for item in items if item]


def _filter_agent_edits(edits: List[Any]) -> None:
    for edit in edits:
        if edit.newText:
            edit.newText = _redact_sensitive_text(edit.newText)
        if edit.diff:
            edit.diff = _redact_sensitive_text(edit.diff)
        if edit.description:
            edit.description = _redact_sensitive_text(edit.description)
        if edit.searchReplace and isinstance(edit.searchReplace, dict):
            for key in ("search", "replace"):
                if isinstance(edit.searchReplace.get(key), str):
                    edit.searchReplace[key] = _redact_sensitive_text(edit.searchReplace[key])


def _cache_key(*parts: Any) -> str:
    joined = "|".join(str(p) for p in parts if p is not None)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, joined))


def _ensure_scopes(request: Request, required_scopes: List[str]) -> None:
    scopes = getattr(request.state, "token_scopes", None)
    if scopes is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Personal access token with scopes required",
        )
    missing: List[str] = []
    for scope in required_scopes:
        if scope in scopes:
            continue
        if scope.endswith(":read") and "read" in scopes:
            continue
        if scope.endswith(":write") and "write" in scopes:
            continue
        missing.append(scope)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient scope",
        )


def _scope_enabled(scopes: Optional[List[str]], scope: str) -> bool:
    if scopes is None:
        return True
    if scope in scopes:
        return True
    if scope.endswith(":read") and "read" in scopes:
        return True
    if scope.endswith(":write") and "write" in scopes:
        return True
    return False


def _safe_relative_path(path: str) -> Optional[str]:
    if not path:
        return None
    normalized = os.path.normpath(path.replace("\\", "/"))
    if os.path.isabs(normalized):
        return None
    if ":" in normalized.split("/")[0]:
        return None
    if normalized.startswith(".."):
        return None
    # Prevent paths that normalize to "."
    if normalized in {".", ""}:
        return None
    return normalized


def _is_blocked_repo_path(path: str) -> bool:
    if not path:
        return True
    normalized = path.replace("\\", "/")
    segments = normalized.split("/")
    if any(segment in BLOCKED_PATH_SEGMENTS for segment in segments):
        return True
    _, ext = os.path.splitext(normalized)
    return ext.lower() in BLOCKED_EXTENSIONS


def _is_allowed_new_file(path: str) -> bool:
    _, ext = os.path.splitext(path)
    return ext.lower() in ALLOWED_NEW_FILE_EXTENSIONS


def _normalize_repo_path(path: str, root: Optional[str]) -> Optional[str]:
    if not path:
        return None
    normalized = os.path.normpath(path.replace("\\", "/"))
    if os.path.isabs(normalized):
        if not root:
            return None
        root_norm = os.path.normpath(root.replace("\\", "/"))
        try:
            if os.path.commonpath([normalized, root_norm]) != root_norm:
                return None
        except ValueError:
            return None
        rel = os.path.relpath(normalized, root_norm)
        return _safe_relative_path(rel)
    return _safe_relative_path(normalized)


def _assistant_chat_filter(query):
    """Restrict to assistant chats using name heuristic."""
    return query.filter(
        or_(
            func.lower(ChatInstance.name).like("%assistant%"),
            func.lower(ChatInstance.name).like("%parallel%"),
        )
    )


def _resolve_openai_client() -> tuple[Optional[Any], Optional[str]]:
    if not config.OPENAI_API_KEY:
        return None, "OPENAI_API_KEY is not set"
    if not config.OPENAI_MODEL:
        return None, "OPENAI_MODEL is not set"
    client = config.openai_client
    if not client:
        return None, "OpenAI client not configured"
    return client, None


def _build_chat_history(db: Session, chat_id: str, max_messages: int) -> List[Dict[str, str]]:
    rows = (
        db.query(Message)
        .filter(
            Message.chat_instance_id == chat_id,
            Message.role.in_(["user", "assistant"]),
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(max_messages)
        .all()
    )
    rows.reverse()
    return [{"role": row.role, "content": row.content} for row in rows if row.content]


def _get_or_create_agent(db: Session, user: User) -> AgentProfile:
    agent = db.query(AgentProfile).filter(AgentProfile.user_id == user.id).first()
    if agent:
        return agent
    agent = AgentProfile(
        id=str(uuid.uuid4()),
        user_id=user.id,
        name=f"{user.name or user.email}'s Rep",
        persona_json={
            "style": "default",
            "description": f"AI representative for {user.name or user.email}",
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def _resolve_chat_instance(
    db: Session,
    workspace_id: str,
    chat_id: Optional[str],
    user: User,
) -> ChatInstance:
    if chat_id:
        chat = db.query(ChatInstance).filter(ChatInstance.id == chat_id).first()
        if not chat:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
        if chat.room_id != workspace_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Chat workspace mismatch")
        return chat

    chat = (
        db.query(ChatInstance)
        .filter(
            ChatInstance.room_id == workspace_id,
            func.lower(ChatInstance.name) == "parallel assistant",
        )
        .first()
    )
    if chat:
        return chat

    chat = ChatInstance(
        id=str(uuid.uuid4()),
        room_id=workspace_id,
        name="Parallel Assistant",
        created_by_user_id=user.id,
        created_at=datetime.now(timezone.utc),
        last_message_at=None,
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


class VSCodeMessage(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime


class VSCodeConversation(BaseModel):
    id: str
    title: str
    summary: str
    last_message_at: Optional[datetime]
    messages: Optional[List[VSCodeMessage]] = None


class VSCodeTask(BaseModel):
    id: str
    title: str
    status: str
    assignee_id: str
    updated_at: datetime


class VSCodeContextResponse(BaseModel):
    workspace_id: str
    fetched_at: datetime
    tasks: List[VSCodeTask]
    conversations: List[VSCodeConversation]


    metadata: Dict[str, Any] = Field(default_factory=dict)


class VSCodeChatResponse(BaseModel):
    request_id: str
    workspace_id: str
    chat_id: str
    user_message_id: str
    assistant_message_id: str
    reply: str
    model: str
    created_at: datetime
    duration_ms: int


def _collect_context_bundle(
    db: Session,
    workspace_id: str,
    current_user: User,
    *,
    tasks_limit: int,
    conversations_limit: int,
    messages_limit: int,
    include_messages: bool,
) -> VSCodeContextResponse:
    tasks = (
        db.query(Task)
        .filter(
            Task.workspace_id == workspace_id,
            Task.assignee_id == current_user.id,
            Task.deleted_at.is_(None),
        )
        .order_by(Task.updated_at.desc())
        .limit(tasks_limit)
        .all()
    )

    chats_query = db.query(ChatInstance).filter(ChatInstance.room_id == workspace_id)
    chats = (
        _assistant_chat_filter(chats_query)
        .order_by(
            func.coalesce(ChatInstance.last_message_at, ChatInstance.created_at).desc(),
            ChatInstance.id.asc(),
        )
        .limit(conversations_limit)
        .all()
    )

    conversations: List[VSCodeConversation] = []
    for chat in chats:
        # Summary from the most recent message
        last_message = (
            db.query(Message)
            .filter(Message.chat_instance_id == chat.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .first()
        )
        summary_text = last_message.content if last_message else chat.name
        summary = _truncate(summary_text, MAX_MESSAGE_SUMMARY_LEN)

        messages_payload: Optional[List[VSCodeMessage]] = None
        if include_messages:
            rows = (
                db.query(Message)
                .filter(Message.chat_instance_id == chat.id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(messages_limit)
                .all()
            )
            messages_payload = [
                VSCodeMessage(
                    id=row.id,
                    role=row.role,
                    content=_truncate(row.content, MAX_MESSAGE_BODY_LEN),
                    created_at=row.created_at,
                )
                for row in rows
            ]

        conversations.append(
            VSCodeConversation(
                id=chat.id,
                title=chat.name,
                summary=summary,
                last_message_at=chat.last_message_at or chat.created_at,
                messages=messages_payload,
            )
        )

    return VSCodeContextResponse(
        workspace_id=workspace_id,
        fetched_at=datetime.now(timezone.utc),
        tasks=[
            VSCodeTask(
                id=t.id,
                title=t.title,
                status=t.status,
                assignee_id=t.assignee_id,
                updated_at=t.updated_at or t.created_at,
            )
            for t in tasks
        ],
        conversations=conversations,
    )


@router.get(
    "/workspaces/{workspace_id}/vscode/context",
    response_model=VSCodeContextResponse,
    response_model_exclude_none=True,
)
def vscode_context_bundle(
    workspace_id: str,
    tasks_limit: int = Query(20, ge=1, le=200),
    conversations_limit: int = Query(5, ge=1, le=100),
    messages_limit: int = Query(20, ge=1, le=200),
    include_messages: bool = Query(False),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)

    if include_messages:
        _ensure_scopes(request, ["tasks:read", "chats:read", "messages:read"])
    else:
        _ensure_scopes(request, ["tasks:read", "chats:read"])

    return _collect_context_bundle(
        db,
        workspace_id,
        current_user,
        tasks_limit=tasks_limit,
        conversations_limit=conversations_limit,
        messages_limit=messages_limit,
        include_messages=include_messages,
    )


class RepoDiagnostic(BaseModel):
    file: str
    message: str
    severity: Optional[str] = None
    range: Optional[Dict] = None

    @validator("message")
    def _limit_message(cls, v: str) -> str:
        return _truncate(v, MAX_MESSAGE_BODY_LEN)


class RepoGuide(BaseModel):
    path: str
    content: str

    @validator("content")
    def _limit_content(cls, v: str) -> str:
        return _truncate(v, MAX_FILE_CONTENT_LEN)


class RepoSymbol(BaseModel):
    name: str
    kind: Optional[str] = None
    detail: Optional[str] = None
    file: Optional[str] = None
    range: Optional[Dict[str, Any]] = None


class RepoReference(BaseModel):
    file: str
    line: int
    character: int
    preview: Optional[str] = None

    @validator("preview")
    def _limit_preview(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _truncate(v, 240)


class RepoGitCommit(BaseModel):
    hash: str
    message: str
    author: Optional[str] = None
    date: Optional[str] = None


class RepoGitContext(BaseModel):
    branch: Optional[str] = None
    staged_files: List[str] = Field(default_factory=list)
    unstaged_files: List[str] = Field(default_factory=list)
    recent_commits: List[RepoGitCommit] = Field(default_factory=list)


class AgentRepoFile(BaseModel):
    absolute: Optional[str] = None
    relative: Optional[str] = None
    content: Optional[str] = None
    language: Optional[str] = None
    size: Optional[int] = None
    truncated: Optional[bool] = None

    @validator("content")
    def _limit_content(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if len(v) > MAX_FILE_CONTENT_HARD:
            raise ValueError("content too large")
        return v


class AgentRepoSearchResult(BaseModel):
    file: str
    line: Optional[int] = None
    preview: str

    @validator("preview")
    def _limit_preview(cls, v: str) -> str:
        return _truncate(v, 400)


class AgentRepoCommandResult(BaseModel):
    command: str
    cwd: Optional[str] = None
    exit_code: Optional[int] = Field(default=None, alias="exitCode")
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    duration_ms: Optional[int] = Field(default=None, alias="durationMs")

    class Config:
        populate_by_name = True

    @validator("stdout", "stderr")
    def _limit_output(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _truncate(v, MAX_COMMAND_OUTPUT_LEN)


class AgentRepoInfo(BaseModel):
    name: str
    root: Optional[str] = None
    selected_files: List[str] = Field(default_factory=list)
    open_files: List[str] = Field(default_factory=list)
    allow_new_files: bool = Field(default=False, alias="allowNewFiles")
    files: List[AgentRepoFile] = Field(default_factory=list)
    search_results: List[AgentRepoSearchResult] = Field(default_factory=list, alias="searchResults")
    command_results: List[AgentRepoCommandResult] = Field(default_factory=list, alias="commandResults")
    diff: Optional[str] = None
    git_diff_stat: Optional[str] = Field(default=None, alias="gitDiffStat")
    diagnostics: List[RepoDiagnostic] = Field(default_factory=list)
    guides: List[RepoGuide] = Field(default_factory=list)
    symbols: List[RepoSymbol] = Field(default_factory=list)
    references: List[RepoReference] = Field(default_factory=list)
    hover_info: Optional[str] = Field(default=None, alias="hoverInfo")
    git: Optional[RepoGitContext] = None
    semantic_context: List[Dict[str, Any]] = Field(default_factory=list, alias="semanticContext")

    class Config:
        populate_by_name = True


class VSCodeChatRequest(BaseModel):
    workspace_id: str
    message: str
    chat_id: Optional[str] = None
    repo: Optional[AgentRepoInfo] = None

    @validator("message")
    def _validate_message(cls, v: str) -> str:
        cleaned = (v or "").strip()
        if not cleaned:
            raise ValueError("message is required")
        return _truncate(cleaned, MAX_REQUEST_LEN)


class InlineCompletionCursor(BaseModel):
    line: int
    character: int


class InlineCompletionRequest(BaseModel):
    filePath: str = Field(alias="file_path")
    languageId: Optional[str] = Field(default=None, alias="language_id")
    prefix: str
    suffix: str
    cursor: InlineCompletionCursor
    maxCompletions: int = Field(default=1, ge=1, le=MAX_INLINE_COMPLETIONS, alias="max_completions")
    temperature: Optional[float] = None
    context: Optional[Dict[str, Any]] = None
    prompt: Optional[str] = None

    class Config:
        populate_by_name = True

    @validator("prefix")
    def _limit_prefix(cls, v: str) -> str:
        return _truncate(v, MAX_INLINE_PREFIX_LEN)

    @validator("suffix")
    def _limit_suffix(cls, v: str) -> str:
        return _truncate(v, MAX_INLINE_SUFFIX_LEN)


class InlineCompletionResponse(BaseModel):
    request_id: str
    completions: List[str]
    range: Dict[str, int]


class AgentContextOverrides(BaseModel):
    tasks: Optional[List[dict]] = None
    conversations: Optional[List[dict]] = None
    workspace_context_cursor: Optional[str] = None


class AgentOutputConfig(BaseModel):
    format: str = Field(default="fullText")
    max_files: int = Field(default=10, ge=1, le=50)
    max_commands: int = Field(default=5, ge=0, le=20)

    @validator("format")
    def _validate_format(cls, v: str) -> str:
        if v not in {"fullText"}:
            raise ValueError("Unsupported output format")
        return v


class AgentProposeRequest(BaseModel):
    request: str
    mode: str = Field(default="dry-run")
    repo: AgentRepoInfo
    context: AgentContextOverrides = Field(default_factory=AgentContextOverrides, alias="parallelContext")
    output: AgentOutputConfig = Field(default_factory=AgentOutputConfig)
    prompt: Optional[str] = None

    class Config:
        populate_by_name = True

    @validator("mode")
    def _validate_mode(cls, v: str) -> str:
        if v not in {"dry-run", "apply"}:
            raise ValueError("mode must be 'dry-run' or 'apply'")
        return v

    @validator("request")
    def _limit_request(cls, v: str) -> str:
        return _truncate(v, MAX_REQUEST_LEN)


class AgentEdit(BaseModel):
    filePath: str
    newText: Optional[str] = None
    diff: Optional[str] = None
    mode: Optional[str] = None
    description: Optional[str] = None
    range: Optional[Dict[str, Any]] = None
    originalLines: Optional[List[int]] = None
    searchReplace: Optional[Dict[str, Any]] = None


class AgentCommand(BaseModel):
    command: str
    cwd: Optional[str] = None
    purpose: Optional[str] = None
    when: Optional[str] = None


class AgentProposeResponse(BaseModel):
    plan: List[str]
    edits: List[AgentEdit]
    commands: List[AgentCommand] = Field(default_factory=list)
    dryRun: bool
    contextUsed: Dict[str, int]


class AgentPlanRequest(BaseModel):
    request: str
    repo: AgentRepoInfo
    context: AgentContextOverrides = Field(default_factory=AgentContextOverrides, alias="parallelContext")
    prompt: Optional[str] = None

    class Config:
        populate_by_name = True

    @validator("request")
    def _limit_request(cls, v: str) -> str:
        return _truncate(v, MAX_REQUEST_LEN)


class AgentPlanResponse(BaseModel):
    plan: List[str]
    files_to_read: List[str] = Field(default_factory=list)
    files_to_modify: List[str] = Field(default_factory=list)
    search_queries: List[str] = Field(default_factory=list)
    reasoning: Optional[str] = None


class AgentEditHistoryRequest(BaseModel):
    edit_id: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    files_modified: List[str]
    original_content: Dict[str, str]
    new_content: Dict[str, str]


class AgentUndoRequest(BaseModel):
    edit_id: str


class AgentExplainRequest(BaseModel):
    code: str
    file_path: Optional[str] = None
    cursor_position: Optional[Dict[str, int]] = None
    language: Optional[str] = None


class AgentExplainResponse(BaseModel):
    explanation: str


class AgentTestRequest(BaseModel):
    file_path: str
    function_name: str
    test_framework: str = "pytest"
    code: Optional[str] = None


class AgentTestResponse(BaseModel):
    file_path: str
    content: str


class CodeIndexFile(BaseModel):
    path: str
    content: str
    language: Optional[str] = None
    symbol: Optional[str] = None


class CodeIndexRequest(BaseModel):
    files: List[CodeIndexFile]


class CodeIndexResponse(BaseModel):
    indexed: int


class CodeSearchRequest(BaseModel):
    query: str
    limit: int = Field(default=8, ge=1, le=50)


class CodeSearchResponse(BaseModel):
    results: List[Dict[str, Any]]


class TerminalOutputRequest(BaseModel):
    command: str
    output: str
    exit_code: int
    cwd: Optional[str] = None


def _validate_agent_payload(payload: AgentProposeRequest) -> None:
    if payload.repo.diff and len(payload.repo.diff) > MAX_DIFF_LEN:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Diff too large",
        )
    if len(payload.request) > MAX_REQUEST_LEN:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Request too large",
        )
    total_content = 0
    for entry in payload.repo.files:
        if entry.content:
            total_content += len(entry.content)
    for guide in payload.repo.guides:
        if guide.content:
            total_content += len(guide.content)
    if total_content > MAX_TOTAL_FILE_CONTENT:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Repo file contents too large",
        )


def _collect_repo_files(repo: AgentRepoInfo) -> List[str]:
    raw_candidates: List[str] = []
    raw_candidates.extend(repo.selected_files or [])
    raw_candidates.extend(repo.open_files or [])
    if repo.files:
        for entry in repo.files:
            candidate = entry.relative or entry.absolute
            if candidate:
                raw_candidates.append(candidate)
    deduped: List[str] = []
    seen = set()
    for candidate in raw_candidates:
        safe = _normalize_repo_path(candidate, repo.root)
        if not safe or safe in seen or _is_blocked_repo_path(safe):
            continue
        seen.add(safe)
        deduped.append(safe)
    return deduped


def _collect_repo_file_contexts(repo: AgentRepoInfo) -> List[Dict[str, Any]]:
    contexts: List[Dict[str, Any]] = []
    seen = set()
    for entry in repo.files:
        if not entry.content:
            continue
        candidate = entry.relative or entry.absolute
        safe_path = _normalize_repo_path(candidate or "", repo.root)
        if not safe_path or safe_path in seen or _is_blocked_repo_path(safe_path):
            continue
        seen.add(safe_path)
        content = entry.content
        truncated = bool(entry.truncated) or len(content) > MAX_FILE_CONTENT_LEN
        contexts.append(
            {
                "path": safe_path,
                "language": entry.language,
                "size": entry.size or len(content),
                "truncated": truncated,
                "content": _truncate(content, MAX_FILE_CONTENT_LEN),
            }
        )
        if len(contexts) >= MAX_FILE_CONTEXTS:
            break
    return contexts


def _collect_repo_search_results(repo: AgentRepoInfo) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for entry in repo.search_results:
        safe_path = _normalize_repo_path(entry.file, repo.root)
        if not safe_path:
            continue
        results.append(
            {
                "file": safe_path,
                "line": entry.line,
                "preview": _truncate(entry.preview, 400),
            }
        )
        if len(results) >= MAX_SEARCH_RESULTS:
            break
    return results


def _collect_repo_guides(repo: AgentRepoInfo) -> List[Dict[str, Any]]:
    guides: List[Dict[str, Any]] = []
    seen = set()
    for guide in repo.guides:
        path = _safe_relative_path(guide.path)
        if not path or path in seen:
            continue
        seen.add(path)
        guides.append({"path": path, "content": _truncate(guide.content, MAX_FILE_CONTENT_LEN)})
        if len(guides) >= 6:
            break
    return guides


def _collect_semantic_context(repo: AgentRepoInfo) -> List[Dict[str, Any]]:
    contexts: List[Dict[str, Any]] = []
    for entry in repo.semantic_context[:10]:
        file_path = entry.get("file_path") or entry.get("file") or ""
        safe_path = _safe_relative_path(file_path) or file_path
        contexts.append(
            {
                "file": safe_path,
                "score": entry.get("score"),
                "content": _truncate(str(entry.get("content") or ""), MAX_FILE_CONTENT_LEN),
                "metadata": entry.get("metadata"),
            }
        )
    return contexts


def _collect_command_results(repo: AgentRepoInfo) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for entry in repo.command_results:
        cwd = _normalize_repo_path(entry.cwd, repo.root) if entry.cwd else None
        results.append(
            {
                "command": _truncate(entry.command, MAX_COMMAND_LEN),
                "cwd": cwd,
                "exitCode": entry.exit_code,
                "durationMs": entry.duration_ms,
                "stdout": _truncate(entry.stdout or "", MAX_COMMAND_OUTPUT_LEN),
                "stderr": _truncate(entry.stderr or "", MAX_COMMAND_OUTPUT_LEN),
            }
        )
        if len(results) >= MAX_COMMAND_RESULTS:
            break
    return results


def _collect_terminal_activity(
    db: Session,
    workspace_id: str,
    current_user: User,
    *,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    try:
        rows = (
            db.query(UserAction)
            .filter(UserAction.user_id == current_user.id, UserAction.tool == "terminal")
            .order_by(UserAction.timestamp.desc())
            .limit(limit * 3)
            .all()
        )
    except SQLAlchemyError:
        logger.warning("[VSCode Agent] Terminal activity query failed")
        return []
    activities: List[Dict[str, Any]] = []
    for row in rows:
        data = row.action_data or {}
        data_workspace = data.get("workspace_id")
        if data_workspace and data_workspace != workspace_id:
            continue
        activities.append(
            {
                "command": _truncate(str(data.get("command") or ""), 200),
                "output": _truncate(str(data.get("output") or ""), 1200),
                "exitCode": data.get("exit_code"),
                "cwd": data.get("cwd"),
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            }
        )
        if len(activities) >= limit:
            break
    return activities


def _build_file_content_map(repo: AgentRepoInfo) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for entry in repo.files:
        if not entry.content or entry.truncated:
            continue
        candidate = entry.relative or entry.absolute
        safe_path = _normalize_repo_path(candidate or "", repo.root)
        if not safe_path or safe_path in mapping or _is_blocked_repo_path(safe_path):
            continue
        mapping[safe_path] = entry.content
    return mapping


def _build_stub_edit(payload: AgentProposeRequest) -> List[AgentEdit]:
    candidates = _collect_repo_files(payload.repo)
    edits: List[AgentEdit] = []
    for path in candidates:
        safe_path = _safe_relative_path(path)
        if not safe_path:
            continue
        note = _truncate(payload.request, 200)
        new_text = (
            f"# Proposed edit for {safe_path}\n"
            f"# Request: {note}\n"
            "# TODO: Replace with agent-generated content.\n"
        )
        edits.append(
            AgentEdit(
                filePath=safe_path,
                newText=new_text,
                diff=None,
                mode="replace",
                description="Stub edit (LLM unavailable)",
            )
        )
        if len(edits) >= payload.output.max_files:
            break
    return edits


def _collect_rag_context_payload(
    db: Session,
    workspace_id: str,
    current_user: User,
    query: str,
) -> Optional[Dict[str, Any]]:
    if not query:
        return None
    try:
        ctx = get_relevant_context(
            db=db,
            query=query,
            room_ids=[workspace_id],
            user_id=current_user.id,
            limit=8,
        )
    except Exception:
        logger.exception("[VSCode Agent] RAG context retrieval failed")
        return None
    if not isinstance(ctx, dict):
        return None

    messages = ctx.get("messages", []) or []
    summarized = []
    for msg in messages[:6]:
        summarized.append(
            {
                "id": getattr(msg, "id", None),
                "sender": getattr(msg, "sender_name", None),
                "content": _truncate(getattr(msg, "content", "") or "", 300),
                "timestamp": msg.created_at.isoformat() if getattr(msg, "created_at", None) else None,
                "score": float(getattr(msg, "score", 0.0) or 0.0),
            }
        )

    room_members = ctx.get("room_members") or []
    recent_activity = ctx.get("recent_activity") or []
    timeline = ctx.get("timeline")

    return {
        "messages": summarized,
        "roomMembers": room_members[:10],
        "recentActivity": recent_activity[:10],
        "timeline": timeline,
    }


def _permissions_snapshot(request: Request) -> Dict[str, bool]:
    scopes = getattr(request.state, "token_scopes", None)
    return {
        "readFiles": _scope_enabled(scopes, "files:read"),
        "searchFiles": _scope_enabled(scopes, "files:search"),
        "applyEdits": _scope_enabled(scopes, "edits:apply"),
        "runCommands": _scope_enabled(scopes, "commands:run"),
    }


def _validate_repo_context(repo: Optional[AgentRepoInfo]) -> None:
    if not repo:
        return
    total_content = 0
    for entry in repo.files:
        if entry.content:
            total_content += len(entry.content)
    for guide in repo.guides:
        if guide.content:
            total_content += len(guide.content)
    if total_content > MAX_TOTAL_FILE_CONTENT:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Repo file contents too large",
        )


def _build_chat_context(
    repo: AgentRepoInfo,
    repo_files: List[str],
    file_contexts: List[Dict[str, Any]],
    search_results: List[Dict[str, Any]],
    permissions: Dict[str, bool],
    terminal_activity: Optional[List[Dict[str, Any]]] = None,
) -> str:
    lines: List[str] = []
    lines.append(f"# Repo\nname: {repo.name}")
    if repo.root:
        lines.append(f"root: {repo.root}")
    if permissions:
        lines.append(f"# Permissions\n{_safe_json_dumps(permissions)}")
    if repo_files:
        lines.append(f"# Allowed files\n{', '.join(repo_files[:40])}")
    if repo.git_diff_stat:
        lines.append(f"# Git Diff\n{_truncate(repo.git_diff_stat, 400)}")
    if repo.git:
        lines.append(f"# Git Context\n{_safe_json_dumps(repo.git.model_dump())}")
    if terminal_activity:
        lines.append(f"# Terminal Activity\n{_safe_json_dumps(terminal_activity)}")
    if repo.guides:
        guide_blocks = [
            f"## {g['path']}\n{g['content']}" for g in _collect_repo_guides(repo)
        ]
        lines.append("# Project Guides\n" + "\n\n".join(guide_blocks))
    if repo.diagnostics:
        diag_lines = [
            f"- [{d.severity or 'info'}] {d.file}: {_truncate(d.message, 180)}"
            for d in repo.diagnostics[:10]
        ]
        lines.append("# Diagnostics\n" + "\n".join(diag_lines))
    if repo.symbols:
        lines.append(f"# Symbols\n{_safe_json_dumps([s.model_dump() for s in repo.symbols[:40]])}")
    if repo.references:
        lines.append(
            f"# References\n{_safe_json_dumps([r.model_dump() for r in repo.references[:60]])}"
        )
    if repo.hover_info:
        lines.append(f"# Hover Info\n{_truncate(repo.hover_info, 1200)}")
    if file_contexts:
        file_sections: List[str] = []
        for entry in file_contexts:
            meta: List[str] = []
            if entry.get("language"):
                meta.append(f"lang={entry['language']}")
            if entry.get("truncated"):
                meta.append("truncated")
            header = entry["path"]
            if meta:
                header = f"{header} ({', '.join(meta)})"
            file_sections.append(f"## {header}\n{entry.get('content', '')}")
        lines.append("# File Context\n" + "\n\n".join(file_sections))
    if search_results:
        lines.append(f"# Search Results\n{_safe_json_dumps(search_results)}")
    semantic_context = _collect_semantic_context(repo)
    if semantic_context:
        lines.append(f"# Semantic Context\n{_safe_json_dumps(semantic_context)}")
    return "\n\n".join(lines)


def _build_agent_prompt(
    payload: AgentProposeRequest,
    context_data: VSCodeContextResponse,
    repo_files: List[str],
    file_contexts: List[Dict[str, Any]],
    search_results: List[Dict[str, Any]],
    command_results: List[Dict[str, Any]],
    rag_context: Optional[Dict[str, Any]],
    permissions: Dict[str, bool],
    terminal_activity: Optional[List[Dict[str, Any]]],
) -> str:
    base = payload.prompt or ""
    lines: List[str] = []
    if base:
        lines.append(base)
    else:
        lines.append(f"# User Request\n{_truncate(payload.request, 1000)}")
        lines.append(f"# Mode\n{payload.mode}")
    if permissions:
        lines.append(f"# Permissions\n{_safe_json_dumps(permissions)}")
    if repo_files:
        lines.append(f"# Allowed files\n{', '.join(repo_files[:40])}")
    if payload.repo.git_diff_stat:
        lines.append(f"# Git Diff\n{_truncate(payload.repo.git_diff_stat, 400)}")
    if payload.repo.git:
        lines.append(f"# Git Context\n{_safe_json_dumps(payload.repo.git.model_dump())}")
    if payload.repo.diff:
        lines.append(f"# Working Diff\n{_truncate(payload.repo.diff, MAX_DIFF_SNIPPET_LEN)}")
    if terminal_activity:
        lines.append(f"# Terminal Activity\n{_safe_json_dumps(terminal_activity)}")
    if payload.repo.diagnostics:
        diag_lines = [
            f"- [{d.severity or 'info'}] {d.file}: {_truncate(d.message, 180)}"
            for d in payload.repo.diagnostics[:10]
        ]
        lines.append("# Diagnostics\n" + "\n".join(diag_lines))
    if payload.repo.guides:
        guide_blocks = [
            f"## {g['path']}\n{g['content']}" for g in _collect_repo_guides(payload.repo)
        ]
        lines.append("# Project Guides\n" + "\n\n".join(guide_blocks))
    if payload.repo.symbols:
        lines.append(
            f"# Symbols\n{_safe_json_dumps([s.model_dump() for s in payload.repo.symbols[:40]])}"
        )
    if payload.repo.references:
        lines.append(
            f"# References\n{_safe_json_dumps([r.model_dump() for r in payload.repo.references[:60]])}"
        )
    if payload.repo.hover_info:
        lines.append(f"# Hover Info\n{_truncate(payload.repo.hover_info, 1200)}")
    tasks = payload.context.tasks or [t.model_dump(mode="json") for t in context_data.tasks]
    conversations = payload.context.conversations or [
        {"id": c.id, "title": c.title, "summary": c.summary} for c in context_data.conversations
    ]
    if tasks:
        lines.append(f"# Tasks\n{_safe_json_dumps(tasks[:5])}")
    if conversations:
        lines.append(f"# Conversations\n{_safe_json_dumps(conversations[:5])}")
    if rag_context:
        lines.append(f"# Parallel Knowledge Base\n{_safe_json_dumps(rag_context)}")
    semantic_context = _collect_semantic_context(payload.repo)
    if semantic_context:
        lines.append(f"# Semantic Code Context\n{_safe_json_dumps(semantic_context)}")
    if file_contexts:
        file_sections: List[str] = []
        for entry in file_contexts:
            meta: List[str] = []
            if entry.get("language"):
                meta.append(f"lang={entry['language']}")
            if entry.get("truncated"):
                meta.append("truncated")
            header = entry["path"]
            if meta:
                header = f"{header} ({', '.join(meta)})"
            file_sections.append(f"## {header}\n{entry.get('content', '')}")
        lines.append("# File Context\n" + "\n\n".join(file_sections))
    if search_results:
        lines.append(f"# Search Results\n{_safe_json_dumps(search_results)}")
    if command_results:
        lines.append(f"# Command Results\n{_safe_json_dumps(command_results)}")
    lines.append(
        "# Output\n"
        f"Return JSON for plan + edits + commands. Max files: {payload.output.max_files}. "
        f"Max commands: {payload.output.max_commands}."
    )
    return "\n\n".join(lines)


def _build_plan_prompt(
    payload: AgentPlanRequest,
    repo_files: List[str],
    context_data: VSCodeContextResponse,
    rag_context: Optional[Dict[str, Any]],
) -> str:
    lines: List[str] = []
    lines.append(f"# User Request\n{_truncate(payload.request, 1000)}")
    if repo_files:
        lines.append(f"# Allowed files\n{', '.join(repo_files[:80])}")
    if payload.repo.git_diff_stat:
        lines.append(f"# Git Diff\n{_truncate(payload.repo.git_diff_stat, 400)}")
    if payload.repo.diagnostics:
        diag_lines = [
            f"- [{d.severity or 'info'}] {d.file}: {_truncate(d.message, 180)}"
            for d in payload.repo.diagnostics[:10]
        ]
        lines.append("# Diagnostics\n" + "\n".join(diag_lines))
    if payload.repo.guides:
        guide_blocks = [
            f"## {g['path']}\n{g['content']}" for g in _collect_repo_guides(payload.repo)
        ]
        lines.append("# Project Guides\n" + "\n\n".join(guide_blocks))
    tasks = payload.context.tasks or [t.model_dump(mode="json") for t in context_data.tasks]
    if tasks:
        lines.append(f"# Tasks\n{_safe_json_dumps(tasks[:6])}")
    if rag_context:
        lines.append(f"# Parallel Knowledge Base\n{_safe_json_dumps(rag_context)}")
    lines.append(
        "# Output\nReturn JSON for plan + files_to_read + files_to_modify + search_queries."
    )
    return "\n\n".join(lines)


def _build_inline_prompt(request: InlineCompletionRequest) -> str:
    parts: List[str] = []
    if request.prompt:
        parts.append(request.prompt)
    else:
        parts.append("# Task\nComplete the code at the cursor.")
    parts.append(f"# Language\n{request.languageId or 'unknown'}")
    if request.context:
        parts.append(f"# Context\n{_safe_json_dumps(request.context)}")
    parts.append("# Prefix\n" + _truncate(request.prefix, MAX_INLINE_PREFIX_LEN))
    parts.append("# Suffix\n" + _truncate(request.suffix, MAX_INLINE_SUFFIX_LEN))
    parts.append("# Output\nReturn only the completion text.")
    return "\n\n".join(parts)


def _extract_json(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    trimmed = raw.strip()
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        start = trimmed.find("{")
        end = trimmed.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(trimmed[start : end + 1])
        except json.JSONDecodeError:
            return None


def _normalize_completion(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    if "```" in cleaned:
        parts = [line for line in cleaned.splitlines() if "```" not in line]
        cleaned = "\n".join(parts).strip()
    return cleaned


def _normalize_plan(plan_raw: Any) -> List[str]:
    if isinstance(plan_raw, list):
        return [
            _truncate(str(item), 200)
            for item in plan_raw
            if item is not None and str(item).strip()
        ]
    if isinstance(plan_raw, str):
        return [
            _truncate(line.strip("- ").strip(), 200)
            for line in plan_raw.splitlines()
            if line.strip()
        ]
    return []


def _normalize_plan_files(
    files_raw: Any,
    allowed_files: List[str],
    *,
    limit: int = 30,
) -> List[str]:
    if isinstance(files_raw, str):
        candidates = [line.strip() for line in files_raw.splitlines() if line.strip()]
    elif isinstance(files_raw, list):
        candidates = [str(item).strip() for item in files_raw if item is not None]
    else:
        return []
    allowed = set(allowed_files)
    results: List[str] = []
    for candidate in candidates:
        safe = _safe_relative_path(candidate)
        if not safe or _is_blocked_repo_path(safe):
            continue
        if allowed and safe not in allowed:
            continue
        if safe in results:
            continue
        results.append(safe)
        if len(results) >= limit:
            break
    return results


def _normalize_search_queries(raw: Any, limit: int = 6) -> List[str]:
    if isinstance(raw, str):
        candidates = [line.strip() for line in raw.splitlines() if line.strip()]
    elif isinstance(raw, list):
        candidates = [str(item).strip() for item in raw if item is not None]
    else:
        return []
    results: List[str] = []
    for candidate in candidates:
        trimmed = candidate.strip()
        if not trimmed:
            continue
        results.append(_truncate(trimmed, 80))
        if len(results) >= limit:
            break
    return results


def _normalize_edits(
    edits_raw: Any,
    allowed_files: List[str],
    max_files: int,
    allow_new_files: bool = False,
) -> List[AgentEdit]:
    if not isinstance(edits_raw, list):
        return []
    allowed = set(allowed_files)
    normalized: List[AgentEdit] = []
    for item in edits_raw:
        if not isinstance(item, dict):
            continue
        file_path = item.get("filePath") or item.get("path") or item.get("file")
        new_text = item.get("newText") or item.get("content")
        diff = item.get("diff")
        mode = item.get("mode") or "replace"
        description = item.get("description")
        range_data = item.get("range") or item.get("insertRange") or item.get("targetRange")
        original_lines = item.get("originalLines") or item.get("original_lines")
        search_replace = item.get("searchReplace") or item.get("search_replace")
        if not file_path or not isinstance(new_text, str):
            if mode in {"diff", "search_replace"}:
                pass
            else:
                continue
        safe_path = _safe_relative_path(str(file_path))
        if not safe_path:
            continue
        if _is_blocked_repo_path(safe_path):
            continue
        if allowed and safe_path not in allowed:
            if not allow_new_files or not _is_allowed_new_file(safe_path):
                continue
        clipped_text = _truncate(new_text, MAX_DIFF_LEN) if isinstance(new_text, str) else None
        if mode in {"replace", "insert"} and (not clipped_text or not clipped_text.strip()):
            continue
        if mode == "search_replace" and not isinstance(search_replace, dict):
            continue
        if mode == "diff" and not diff and not clipped_text:
            continue
        normalized.append(
            AgentEdit(
                filePath=safe_path,
                newText=clipped_text,
                diff=str(diff) if diff is not None else None,
                mode=str(mode) if mode else None,
                description=str(description) if description else None,
                range=range_data if isinstance(range_data, dict) else None,
                originalLines=original_lines if isinstance(original_lines, list) else None,
                searchReplace=search_replace if isinstance(search_replace, dict) else None,
            )
        )
        if len(normalized) >= max_files:
            break
    return normalized


def _normalize_commands(commands_raw: Any, max_commands: int) -> List[AgentCommand]:
    if not isinstance(commands_raw, list):
        return []
    normalized: List[AgentCommand] = []
    for item in commands_raw:
        if isinstance(item, str):
            command = item
            cwd = None
            purpose = None
            when = None
        elif isinstance(item, dict):
            command = item.get("command") or item.get("cmd")
            cwd = item.get("cwd") or item.get("workingDirectory")
            purpose = item.get("purpose") or item.get("reason")
            when = item.get("when")
        else:
            continue
        if not command:
            continue
        safe_cwd = _safe_relative_path(str(cwd)) if cwd else None
        normalized.append(
            AgentCommand(
                command=_truncate(str(command), MAX_COMMAND_LEN),
                cwd=safe_cwd,
                purpose=_truncate(str(purpose), 200) if purpose else None,
                when=_truncate(str(when), 80) if when else None,
            )
        )
        if len(normalized) >= max_commands:
            break
    return normalized


def _attach_diffs(edits: List[AgentEdit], file_contents: Dict[str, str]) -> None:
    for edit in edits:
        if edit.diff:
            continue
        if edit.newText is None:
            continue
        original = file_contents.get(edit.filePath)
        if original is None:
            continue
        if original == edit.newText:
            continue
        diff_lines = difflib.unified_diff(
            original.splitlines(keepends=True),
            edit.newText.splitlines(keepends=True),
            fromfile=f"a/{edit.filePath}",
            tofile=f"b/{edit.filePath}",
        )
        diff_text = "".join(diff_lines)
        if diff_text:
            edit.diff = _truncate(diff_text, MAX_DIFF_LEN)


def _get_bearer_credentials(request: Request) -> Optional[HTTPAuthorizationCredentials]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return None


def _error_response(request_id: str, status_code: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "request_id": request_id,
            "error": error,
            "detail": detail,
        },
    )


@router.post(
    "/workspaces/{workspace_id}/vscode/agent/complete",
    response_model=InlineCompletionResponse,
)
def inline_complete(
    payload: InlineCompletionRequest,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)
    _ensure_scopes(request, ["completions:read", "files:read"])

    request_id = str(uuid.uuid4())
    client, config_error = _resolve_openai_client()
    if config_error:
        raise HTTPException(status_code=503, detail=config_error)

    key = _cache_key(
        "inline",
        workspace_id,
        payload.filePath,
        payload.prefix[-2000:],
        payload.suffix[:500],
        payload.maxCompletions,
    )
    cached = INLINE_COMPLETION_CACHE.get(key)
    if cached:
        return InlineCompletionResponse(
            request_id=request_id,
            completions=_filter_completion_items(cached),
            range=_cursor_range(payload.cursor),
        )

    prompt = _build_inline_prompt(payload)
    model = config.OPENAI_INLINE_MODEL
    temperature = payload.temperature if payload.temperature is not None else config.OPENAI_INLINE_TEMPERATURE
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": VSCODE_INLINE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            n=payload.maxCompletions,
            max_tokens=160,
        )
    except Exception:
        logger.exception("[VSCode Inline] LLM call failed")
        raise HTTPException(status_code=502, detail="Inline completion failed")

    completions: List[str] = []
    for choice in completion.choices:
        text = _normalize_completion(choice.message.content or "")
        if not text or text in completions:
            continue
        completions.append(text)

    safe_completions = _filter_completion_items(completions)
    if safe_completions:
        INLINE_COMPLETION_CACHE.set(key, safe_completions)

    return InlineCompletionResponse(
        request_id=request_id,
        completions=safe_completions,
        range=_cursor_range(payload.cursor),
    )


@router.post("/workspaces/{workspace_id}/vscode/agent/complete-stream")
async def inline_complete_stream(
    payload: InlineCompletionRequest,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)
    _ensure_scopes(request, ["completions:read", "files:read"])

    request_id = str(uuid.uuid4())
    client, config_error = _resolve_openai_client()

    key = _cache_key(
        "inline",
        workspace_id,
        payload.filePath,
        payload.prefix[-2000:],
        payload.suffix[:500],
        payload.maxCompletions,
    )
    cached = INLINE_COMPLETION_CACHE.get(key)

    async def generate():
        if config_error:
            yield _sse_event({"type": "error", "message": config_error})
            return
        if cached:
            yield _sse_event(
                {
                    "type": "final",
                    "completions": _filter_completion_items(cached),
                    "range": _cursor_range(payload.cursor),
                }
            )
            return
        prompt = _build_inline_prompt(payload)
        temperature = payload.temperature if payload.temperature is not None else config.OPENAI_INLINE_TEMPERATURE
        raw_parts: List[str] = []
        try:
            stream = client.chat.completions.create(
                model=config.OPENAI_INLINE_MODEL,
                messages=[
                    {"role": "system", "content": VSCODE_INLINE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=160,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if not delta:
                    continue
                raw_parts.append(delta)
                yield _sse_event({"type": "delta", "text": _redact_sensitive_text(delta)})
        except Exception:
            logger.exception("[VSCode Inline] Streaming LLM call failed")
            yield _sse_event({"type": "error", "message": "Inline completion failed"})
            return

        completion_text = _normalize_completion("".join(raw_parts))
        completions: List[str] = []
        if completion_text:
            completions = [_redact_sensitive_text(completion_text)]
            INLINE_COMPLETION_CACHE.set(key, completions)
        yield _sse_event(
            {
                "type": "final",
                "completions": completions,
                "range": _cursor_range(payload.cursor),
            }
        )

    return StreamingResponse(generate(), media_type="text/event-stream")


def _cursor_range(cursor: InlineCompletionCursor) -> Dict[str, int]:
    return {
        "startLine": cursor.line,
        "startCharacter": cursor.character,
        "endLine": cursor.line,
        "endCharacter": cursor.character,
    }


@router.post("/workspaces/{workspace_id}/vscode/agent/propose", response_model=AgentProposeResponse)
def agent_propose_edits(
    payload: AgentProposeRequest,
    workspace_id: str,
    stream: bool = Query(False, description="Reserved for future streaming support"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if stream:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Streaming not implemented yet",
        )

    require_workspace_member(workspace_id, current_user, db)
    _validate_agent_payload(payload)
    required_scopes = ["chats:read", "tasks:read", "edits:propose"]
    if payload.mode == "apply":
        required_scopes.append("edits:apply")
    has_file_contents = any(entry.content for entry in payload.repo.files)
    if has_file_contents:
        required_scopes.append("files:read")
    if payload.repo.search_results:
        required_scopes.append("files:search")
    if payload.repo.command_results:
        required_scopes.append("commands:run")
    _ensure_scopes(request, required_scopes)

    # Pull lightweight context counts
    context_data = _collect_context_bundle(
        db,
        workspace_id,
        current_user,
        tasks_limit=5,
        conversations_limit=3,
        messages_limit=5,
        include_messages=False,
    )
    rag_context = _collect_rag_context_payload(db, workspace_id, current_user, payload.request)
    terminal_activity = _collect_terminal_activity(db, workspace_id, current_user)
    permissions = _permissions_snapshot(request)
    file_contexts = _collect_repo_file_contexts(payload.repo)
    search_results = _collect_repo_search_results(payload.repo)
    command_results = _collect_command_results(payload.repo)
    semantic_context = _collect_semantic_context(payload.repo)
    file_content_map = _build_file_content_map(payload.repo)

    context_used = {
        "tasks": len(payload.context.tasks or context_data.tasks),
        "conversations": len(payload.context.conversations or context_data.conversations),
        "rag_messages": len(rag_context.get("messages", [])) if rag_context else 0,
        "rag_room_members": len(rag_context.get("roomMembers", [])) if rag_context else 0,
        "rag_recent_activity": len(rag_context.get("recentActivity", [])) if rag_context else 0,
        "file_contexts": len(file_contexts),
        "search_results": len(search_results),
        "command_results": len(command_results),
        "semantic_context": len(semantic_context),
    }

    plan = [
        f"Understand request: {_truncate(payload.request, 200)}",
        "Review provided repository files and diagnostics",
        "Draft safe, scoped edits for local application",
    ]
    repo_files = _collect_repo_files(payload.repo)
    cache_key = _cache_key(
        "propose",
        workspace_id,
        payload.request,
        ",".join(repo_files[:40]),
        payload.repo.git_diff_stat or "",
        payload.repo.diff or "",
    )
    cached = PROPOSE_CACHE.get(cache_key)
    if cached:
        return AgentProposeResponse(**cached)
    max_commands = min(payload.output.max_commands, MAX_COMMANDS)
    client, config_error = _resolve_openai_client()
    if config_error:
        logger.warning("[VSCode Agent] LLM not configured: %s", config_error)
        edits = _build_stub_edit(payload)
        commands = []
    else:
        prompt = _build_agent_prompt(
            payload,
            context_data,
            repo_files,
            file_contexts,
            search_results,
            command_results,
            rag_context,
            permissions,
            terminal_activity,
        )
        try:
            completion = client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": VSCODE_AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=config.OPENAI_AGENT_TEMPERATURE,
                response_format={"type": "json_object"},
            )
            raw = (completion.choices[0].message.content or "").strip()
            parsed = _extract_json(raw)
            if not parsed:
                logger.warning("[VSCode Agent] LLM returned non-JSON response")
                edits = _build_stub_edit(payload)
                commands = []
            else:
                plan = _normalize_plan(parsed.get("plan")) or plan
                edits = _normalize_edits(
                    parsed.get("edits"),
                    repo_files,
                    payload.output.max_files,
                    payload.repo.allow_new_files,
                )
                commands = _normalize_commands(parsed.get("commands"), max_commands)
                if not edits:
                    edits = _build_stub_edit(payload)
        except Exception:
            logger.exception("[VSCode Agent] LLM call failed")
            edits = _build_stub_edit(payload)
            commands = []

    _attach_diffs(edits, file_content_map)
    _filter_agent_edits(edits)
    if not permissions.get("runCommands", False):
        commands = []

    response = AgentProposeResponse(
        plan=plan,
        edits=edits,
        commands=commands,
        dryRun=payload.mode == "dry-run",
        contextUsed=context_used,
    )
    PROPOSE_CACHE.set(cache_key, response.model_dump())
    return response


@router.post("/workspaces/{workspace_id}/vscode/agent/propose-stream")
async def propose_edits_stream(
    payload: AgentProposeRequest,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)
    _validate_agent_payload(payload)
    required_scopes = ["chats:read", "tasks:read", "edits:propose"]
    if payload.mode == "apply":
        required_scopes.append("edits:apply")
    has_file_contents = any(entry.content for entry in payload.repo.files)
    if has_file_contents:
        required_scopes.append("files:read")
    if payload.repo.search_results:
        required_scopes.append("files:search")
    if payload.repo.command_results:
        required_scopes.append("commands:run")
    _ensure_scopes(request, required_scopes)

    context_data = _collect_context_bundle(
        db,
        workspace_id,
        current_user,
        tasks_limit=5,
        conversations_limit=3,
        messages_limit=5,
        include_messages=False,
    )
    rag_context = _collect_rag_context_payload(db, workspace_id, current_user, payload.request)
    permissions = _permissions_snapshot(request)
    file_contexts = _collect_repo_file_contexts(payload.repo)
    search_results = _collect_repo_search_results(payload.repo)
    command_results = _collect_command_results(payload.repo)
    file_content_map = _build_file_content_map(payload.repo)
    repo_files = _collect_repo_files(payload.repo)

    prompt = _build_agent_prompt(
        payload,
        context_data,
        repo_files,
        file_contexts,
        search_results,
        command_results,
        rag_context,
        permissions,
        terminal_activity,
    )

    cache_key = _cache_key(
        "propose",
        workspace_id,
        payload.request,
        ",".join(repo_files[:40]),
        payload.repo.git_diff_stat or "",
        payload.repo.diff or "",
    )
    cached = PROPOSE_CACHE.get(cache_key)

    async def generate():
        if cached:
            yield _sse_event({"type": "final", "response": cached})
            return

        client, config_error = _resolve_openai_client()
        if config_error:
            yield _sse_event({"type": "error", "message": config_error})
            return

        yield _sse_event({"type": "status", "message": "streaming"})
        raw_parts: List[str] = []
        try:
            stream = client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": VSCODE_AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=config.OPENAI_AGENT_TEMPERATURE,
                response_format={"type": "json_object"},
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if not delta:
                    continue
                raw_parts.append(delta)
                yield _sse_event({"type": "delta", "text": delta})
        except Exception:
            logger.exception("[VSCode Agent] streaming LLM call failed")
            yield _sse_event({"type": "error", "message": "LLM streaming failed"})
            return

        raw = "".join(raw_parts).strip()
        parsed = _extract_json(raw)
        if not parsed:
            yield _sse_event({"type": "error", "message": "LLM returned invalid JSON."})
            return
        else:
            plan = _normalize_plan(parsed.get("plan")) or [
                f"Understand request: {_truncate(payload.request, 200)}",
                "Review provided repository files and diagnostics",
                "Draft safe, scoped edits for local application",
            ]
            edits = _normalize_edits(
                parsed.get("edits"),
                repo_files,
                payload.output.max_files,
                payload.repo.allow_new_files,
            )
            commands = _normalize_commands(parsed.get("commands"), min(payload.output.max_commands, MAX_COMMANDS))
        _attach_diffs(edits, file_content_map)
        _filter_agent_edits(edits)
        if not permissions.get("runCommands", False):
            commands = []
        response = AgentProposeResponse(
            plan=plan,
            edits=edits,
            commands=commands,
            dryRun=payload.mode == "dry-run",
            contextUsed={
                "tasks": len(payload.context.tasks or context_data.tasks),
                "conversations": len(payload.context.conversations or context_data.conversations),
                "rag_messages": len(rag_context.get("messages", [])) if rag_context else 0,
                "rag_room_members": len(rag_context.get("roomMembers", [])) if rag_context else 0,
                "rag_recent_activity": len(rag_context.get("recentActivity", [])) if rag_context else 0,
                "file_contexts": len(file_contexts),
                "search_results": len(search_results),
                "command_results": len(command_results),
                "semantic_context": len(_collect_semantic_context(payload.repo)),
            },
        )
        payload_dict = response.model_dump()
        PROPOSE_CACHE.set(cache_key, payload_dict)
        yield _sse_event({"type": "final", "response": payload_dict})

    return StreamingResponse(generate(), media_type="text/event-stream")


def _sse_event(payload: Dict[str, Any], event: str = "message") -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=True)}\n\n"


@router.post("/workspaces/{workspace_id}/vscode/agent/plan", response_model=AgentPlanResponse)
def agent_plan(
    payload: AgentPlanRequest,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)
    _ensure_scopes(request, ["tasks:read", "chats:read", "edits:propose"])
    _validate_repo_context(payload.repo)

    context_data = _collect_context_bundle(
        db,
        workspace_id,
        current_user,
        tasks_limit=5,
        conversations_limit=3,
        messages_limit=0,
        include_messages=False,
    )
    rag_context = _collect_rag_context_payload(db, workspace_id, current_user, payload.request)
    repo_files = _collect_repo_files(payload.repo)

    cache_key = _cache_key(
        "plan",
        workspace_id,
        payload.request,
        ",".join(repo_files[:50]),
        payload.repo.git_diff_stat or "",
    )
    cached = PLAN_CACHE.get(cache_key)
    if cached:
        return AgentPlanResponse(**cached)

    client, config_error = _resolve_openai_client()
    if config_error:
        raise HTTPException(status_code=503, detail=config_error)

    prompt = _build_plan_prompt(payload, repo_files, context_data, rag_context)
    try:
        completion = client.chat.completions.create(
            model=config.OPENAI_PLAN_MODEL,
            messages=[
                {"role": "system", "content": VSCODE_PLAN_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=config.OPENAI_AGENT_TEMPERATURE,
        )
    except Exception:
        logger.exception("[VSCode Plan] LLM call failed")
        raise HTTPException(status_code=502, detail="Planning failed")

    raw = (completion.choices[0].message.content or "").strip()
    parsed = _extract_json(raw) or {}
    plan = _normalize_plan(parsed.get("plan")) or [
        "Review repository context",
        "Identify target files and supporting dependencies",
        "Plan safe edits",
    ]
    files_to_read = _normalize_plan_files(parsed.get("files_to_read"), repo_files, limit=30)
    files_to_modify = _normalize_plan_files(parsed.get("files_to_modify"), repo_files, limit=20)
    search_queries = _normalize_search_queries(parsed.get("search_queries"))
    response = AgentPlanResponse(
        plan=plan,
        files_to_read=files_to_read,
        files_to_modify=files_to_modify,
        search_queries=search_queries,
        reasoning=_truncate(str(parsed.get("reasoning") or ""), 400) if parsed.get("reasoning") else None,
    )
    PLAN_CACHE.set(cache_key, response.model_dump())
    return response


@router.post("/workspaces/{workspace_id}/vscode/agent/explain", response_model=AgentExplainResponse)
def agent_explain(
    payload: AgentExplainRequest,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)
    _ensure_scopes(request, ["explain:read"])
    client, config_error = _resolve_openai_client()
    if config_error:
        raise HTTPException(status_code=503, detail=config_error)

    cache_key = _cache_key("explain", workspace_id, payload.file_path, payload.code[:2000])
    cached = EXPLAIN_CACHE.get(cache_key)
    if cached:
        return AgentExplainResponse(explanation=cached)

    prompt = (
        f"# File\n{payload.file_path or 'unknown'}\n"
        f"# Language\n{payload.language or 'unknown'}\n"
        f"# Code\n{_truncate(payload.code, MAX_FILE_CONTENT_LEN)}"
    )
    completion = client.chat.completions.create(
        model=config.OPENAI_EXPLAIN_MODEL,
        messages=[
            {"role": "system", "content": VSCODE_EXPLAIN_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    answer = _redact_sensitive_text((completion.choices[0].message.content or "").strip())
    EXPLAIN_CACHE.set(cache_key, answer)
    return AgentExplainResponse(explanation=answer)


@router.post("/workspaces/{workspace_id}/vscode/agent/generate-tests", response_model=AgentTestResponse)
def generate_tests(
    payload: AgentTestRequest,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)
    _ensure_scopes(request, ["tests:write", "files:read"])
    client, config_error = _resolve_openai_client()
    if config_error:
        raise HTTPException(status_code=503, detail=config_error)

    prompt_lines = [
        f"# Target file\n{payload.file_path}",
        f"# Function\n{payload.function_name}",
        f"# Test framework\n{payload.test_framework}",
    ]
    if payload.code:
        prompt_lines.append(f"# Code\n{_truncate(payload.code, MAX_FILE_CONTENT_LEN)}")
    prompt_lines.append("# Output\nReturn only the test code.")
    prompt = "\n\n".join(prompt_lines)

    completion = client.chat.completions.create(
        model=config.OPENAI_TESTS_MODEL,
        messages=[
            {"role": "system", "content": VSCODE_TEST_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    test_code = _redact_sensitive_text((completion.choices[0].message.content or "").strip())
    return AgentTestResponse(file_path=payload.file_path, content=test_code)


@router.post("/workspaces/{workspace_id}/vscode/agent/edits/record")
def record_agent_edit(
    payload: AgentEditHistoryRequest,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)
    _ensure_scopes(request, ["edits:apply", "edits:undo"])
    edit_id = payload.edit_id or str(uuid.uuid4())
    history = AgentEditHistory(
        id=edit_id,
        workspace_id=workspace_id,
        user_id=current_user.id,
        description=payload.description,
        source=payload.source,
        files_modified=payload.files_modified,
        original_content=payload.original_content,
        new_content=payload.new_content,
        created_at=datetime.now(timezone.utc),
    )
    db.add(history)
    db.commit()
    return {"status": "ok", "edit_id": edit_id}


@router.post("/workspaces/{workspace_id}/vscode/agent/undo")
def undo_agent_edit(
    payload: AgentUndoRequest,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)
    _ensure_scopes(request, ["edits:undo"])
    history = (
        db.query(AgentEditHistory)
        .filter(
            AgentEditHistory.id == payload.edit_id,
            AgentEditHistory.workspace_id == workspace_id,
            AgentEditHistory.user_id == current_user.id,
        )
        .first()
    )
    if not history:
        raise HTTPException(status_code=404, detail="Edit history not found")
    return {
        "edit_id": history.id,
        "files": history.original_content,
    }


@router.post("/workspaces/{workspace_id}/vscode/index", response_model=CodeIndexResponse)
def code_index(
    payload: CodeIndexRequest,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)
    _ensure_scopes(request, ["index:write"])
    indexed = index_codebase(
        db,
        workspace_id=workspace_id,
        files=[f.model_dump() for f in payload.files],
    )
    return CodeIndexResponse(indexed=indexed)


@router.post("/workspaces/{workspace_id}/vscode/index/search", response_model=CodeSearchResponse)
def code_index_search(
    payload: CodeSearchRequest,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)
    _ensure_scopes(request, ["index:read"])
    results = search_code_index(db, workspace_id=workspace_id, query=payload.query, limit=payload.limit)
    return CodeSearchResponse(results=results)


@router.post("/workspaces/{workspace_id}/vscode/terminal/output")
def capture_terminal_output(
    payload: TerminalOutputRequest,
    workspace_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_workspace_member(workspace_id, current_user, db)
    _ensure_scopes(request, ["terminal:write"])
    action = UserAction(
        user_id=current_user.id,
        tool="terminal",
        action_type="command_run",
        action_data={
            "command": _truncate(payload.command, MAX_COMMAND_LEN),
            "output": _truncate(payload.output, MAX_COMMAND_OUTPUT_LEN),
            "exit_code": payload.exit_code,
            "cwd": payload.cwd,
            "workspace_id": workspace_id,
        },
        timestamp=datetime.now(timezone.utc),
    )
    db.add(action)
    db.commit()
    return {"status": "ok"}


@router.post("/vscode/chat", response_model=VSCodeChatResponse)
def vscode_chat(
    payload: VSCodeChatRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    request_id = str(uuid.uuid4())
    start_time = time.monotonic()
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    logger.info(
        "[VSCode Chat][%s] Request received path=%s workspace=%s chat_id=%s",
        request_id,
        request.url.path,
        payload.workspace_id,
        payload.chat_id or "-",
    )

    try:
        credentials = _get_bearer_credentials(request)
        try:
            current_user = get_current_user(request=request, authorization=credentials, db=db)
            logger.info(
                "[VSCode Chat][%s] Auth allowed user=%s",
                request_id,
                current_user.id,
            )
        except HTTPException as exc:
            logger.info(
                "[VSCode Chat][%s] Auth denied status=%s detail=%s",
                request_id,
                exc.status_code,
                exc.detail,
            )
            status_code = exc.status_code
            return _error_response(request_id, status_code, "auth_denied", str(exc.detail))

        try:
            require_workspace_member(payload.workspace_id, current_user, db)
        except HTTPException as exc:
            logger.info(
                "[VSCode Chat][%s] Workspace denied user=%s workspace=%s status=%s detail=%s",
                request_id,
                current_user.id,
                payload.workspace_id,
                exc.status_code,
                exc.detail,
            )
            status_code = exc.status_code
            return _error_response(request_id, status_code, "workspace_denied", str(exc.detail))

        try:
            _ensure_scopes(request, ["chats:write"])
        except HTTPException as exc:
            logger.info(
                "[VSCode Chat][%s] Scope denied user=%s scopes=%s detail=%s",
                request_id,
                current_user.id,
                getattr(request.state, "token_scopes", None),
                exc.detail,
            )
            status_code = exc.status_code
            return _error_response(request_id, status_code, "scope_denied", str(exc.detail))

        client, config_error = _resolve_openai_client()
        if config_error:
            logger.warning("[VSCode Chat][%s] LLM config error: %s", request_id, config_error)
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return _error_response(request_id, status_code, "llm_not_configured", config_error)

        _validate_repo_context(payload.repo)
        permissions = _permissions_snapshot(request)
        terminal_activity = _collect_terminal_activity(db, payload.workspace_id, current_user)
        repo_context_text = ""
        if payload.repo:
            repo_files = _collect_repo_files(payload.repo)
            file_contexts = _collect_repo_file_contexts(payload.repo)
            search_results = _collect_repo_search_results(payload.repo)
            if not permissions.get("readFiles", True):
                repo_files = []
                file_contexts = []
            if not permissions.get("searchFiles", True):
                search_results = []
            if (
                repo_files
                or file_contexts
                or search_results
                or payload.repo.git_diff_stat
                or payload.repo.diagnostics
            ):
                repo_context_text = _build_chat_context(
                    payload.repo,
                    repo_files,
                    file_contexts,
                    search_results,
                    permissions,
                    terminal_activity,
                )

        chat = _resolve_chat_instance(db, payload.workspace_id, payload.chat_id, current_user)
        history = _build_chat_history(db, chat.id, MAX_CONTEXT_MESSAGES)

        now = datetime.now(timezone.utc)
        user_msg = Message(
            id=str(uuid.uuid4()),
            room_id=payload.workspace_id,
            chat_instance_id=chat.id,
            sender_id=f"user:{current_user.id}",
            sender_name=current_user.name,
            role="user",
            content=payload.message,
            user_id=current_user.id,
            created_at=now,
        )
        db.add(user_msg)
        chat.last_message_at = now
        db.add(chat)
        db.commit()
        db.refresh(user_msg)

        messages_payload = [{"role": "system", "content": VSCODE_SYSTEM_PROMPT}]
        if repo_context_text:
            messages_payload.append({"role": "system", "content": repo_context_text})
        messages_payload.extend(history)
        messages_payload.append({"role": "user", "content": payload.message})
        model = config.OPENAI_MODEL
        logger.info(
            "[VSCode Chat][%s] LLM call started model=%s messages=%s",
            request_id,
            model,
            len(messages_payload),
        )
        try:
            completion = client.chat.completions.create(model=model, messages=messages_payload)
        except Exception:
            logger.exception("[VSCode Chat][%s] LLM call failed", request_id)
            status_code = status.HTTP_502_BAD_GATEWAY
            return _error_response(
                request_id,
                status_code,
                "llm_call_failed",
                "LLM call failed. Check server logs and model configuration.",
            )

        answer = _redact_sensitive_text((completion.choices[0].message.content or "").strip())
        logger.info("[VSCode Chat][%s] LLM call finished", request_id)

        if not answer:
            status_code = status.HTTP_502_BAD_GATEWAY
            return _error_response(
                request_id,
                status_code,
                "llm_empty_response",
                "LLM returned an empty response.",
            )

        agent = _get_or_create_agent(db, current_user)
        bot_msg = Message(
            id=str(uuid.uuid4()),
            room_id=payload.workspace_id,
            chat_instance_id=chat.id,
            sender_id=f"agent:{agent.id}",
            sender_name=agent.name,
            role="assistant",
            content=answer,
            user_id=current_user.id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(bot_msg)
        chat.last_message_at = bot_msg.created_at
        db.add(chat)
        db.commit()
        db.refresh(bot_msg)

        duration_ms = int((time.monotonic() - start_time) * 1000)
        status_code = status.HTTP_200_OK
        return VSCodeChatResponse(
            request_id=request_id,
            workspace_id=payload.workspace_id,
            chat_id=chat.id,
            user_message_id=user_msg.id,
            assistant_message_id=bot_msg.id,
            reply=answer,
            model=model,
            created_at=bot_msg.created_at,
            duration_ms=duration_ms,
        )
    except HTTPException as exc:
        logger.info(
            "[VSCode Chat][%s] Request error status=%s detail=%s",
            request_id,
            exc.status_code,
            exc.detail,
        )
        status_code = exc.status_code
        return _error_response(request_id, status_code, "request_error", str(exc.detail))
    except Exception:
        logger.exception("[VSCode Chat][%s] Unexpected error", request_id)
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return _error_response(
            request_id,
            status_code,
            "internal_error",
            "Unexpected error while processing chat request.",
        )
    finally:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "[VSCode Chat][%s] Response sent status=%s duration_ms=%s",
            request_id,
            status_code,
            duration_ms,
        )
