import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from config import config

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db, hash_pat_secret, rate_limit_dep, require_scope
from models import PersonalAccessToken, RoomMember, User, VSCodeAuthCode

router = APIRouter()

VSCODE_AUTH_CODE_TTL_SECONDS = int(os.getenv("VSCODE_AUTH_CODE_TTL_SECONDS", "120"))
VSCODE_DEFAULT_REDIRECT = os.getenv(
    "VSCODE_AUTH_REDIRECT_URI",
    "vscode://parallel.parallel-vscode/auth-callback",
)
VSCODE_LOGIN_URL = os.getenv("VSCODE_AUTH_LOGIN_URL", config.FRONTEND_APP_URL)
VSCODE_DEFAULT_SCOPES = [
    "read",
    "write",
    "tasks:read",
    "tasks:write",
    "chats:read",
    "chats:write",
    "files:read",
    "files:search",
    "edits:propose",
    "edits:apply",
    "edits:undo",
    "commands:run",
    "terminal:write",
    "workspaces:read",
    "messages:read",
    "completions:read",
    "index:read",
    "index:write",
    "explain:read",
    "tests:write",
    "git:read",
]
VSCODE_ALLOWED_REDIRECT_PREFIXES = tuple(
    p.strip()
    for p in os.getenv(
        "VSCODE_AUTH_ALLOWED_REDIRECT_PREFIXES",
        "vscode://,http://localhost,http://127.0.0.1",
    ).split(",")
    if p.strip()
)


def _optional_current_user(request: Request, db: Session) -> Optional[User]:
    auth_header = request.headers.get("Authorization", "")
    credentials = None
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    try:
        return get_current_user(request, authorization=credentials, db=db)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            return None
        raise


def _merge_query(url: str, params: dict) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _resolve_redirect_uri(redirect_uri: Optional[str]) -> str:
    candidate = redirect_uri or VSCODE_DEFAULT_REDIRECT
    if not candidate.startswith(VSCODE_ALLOWED_REDIRECT_PREFIXES):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")
    return candidate


class PATCreateRequest(BaseModel):
    name: str
    scopes: List[str] = []
    expires_at: Optional[datetime] = None


class PATMetadata(BaseModel):
    id: str
    name: str
    scopes: List[str]
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PATCreateResponse(BaseModel):
    token: str
    pat: PATMetadata


class VSCodeAuthExchangeRequest(BaseModel):
    auth_code: str


class WorkspaceMembership(BaseModel):
    id: str
    name: str
    role: Optional[str] = None


class MeResponse(BaseModel):
    id: str
    name: str
    email: str
    workspaces: List[WorkspaceMembership]


@router.get("/me", response_model=MeResponse)
def me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_scope("workspaces:read")),
):
    memberships = (
        db.query(RoomMember)
        .filter(RoomMember.user_id == current_user.id)
        .all()
    )
    workspace_list = [
        WorkspaceMembership(
            id=m.room_id,
            name=getattr(m.room, "name", None) or "",
            role=m.role_in_room,
        )
        for m in memberships
    ]
    return MeResponse(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        workspaces=workspace_list,
    )


@router.post("/auth/pat", response_model=PATCreateResponse, status_code=status.HTTP_201_CREATED)
def create_pat(
    payload: PATCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_dep("create_pat", max_calls=10, window_seconds=60)),
):
    pat_id = str(uuid.uuid4())
    # Keep token short enough for bcrypt hashing limits
    secret = secrets.token_urlsafe(24)
    token_value = f"pat_{pat_id}.{secret}"

    pat = PersonalAccessToken(
        id=pat_id,
        user_id=current_user.id,
        name=payload.name,
        scopes=payload.scopes or [],
        token_hash=hash_pat_secret(secret),
        created_at=datetime.now(timezone.utc),
        expires_at=payload.expires_at,
    )
    db.add(pat)
    db.commit()
    db.refresh(pat)

    return PATCreateResponse(token=token_value, pat=pat)


@router.get("/auth/pat", response_model=List[PATMetadata])
def list_pats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tokens = (
        db.query(PersonalAccessToken)
        .filter(PersonalAccessToken.user_id == current_user.id)
        .order_by(PersonalAccessToken.created_at.desc())
        .all()
    )
    return tokens


@router.delete("/auth/pat/{pat_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_pat(
    pat_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pat = (
        db.query(PersonalAccessToken)
        .filter(PersonalAccessToken.id == pat_id, PersonalAccessToken.user_id == current_user.id)
        .first()
    )
    if not pat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PAT not found")
    if pat.revoked_at is None:
        pat.revoked_at = datetime.now(timezone.utc)
        db.add(pat)
        db.commit()
    return None


@router.get("/auth/vscode/start")
def vscode_auth_start(
    request: Request,
    redirect_uri: Optional[str] = None,
    db: Session = Depends(get_db),
):
    current_user = _optional_current_user(request, db)
    if not current_user:
        login_url = _merge_query(VSCODE_LOGIN_URL, {"return_to": str(request.url)})
        return RedirectResponse(url=login_url, status_code=status.HTTP_302_FOUND)

    code = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=VSCODE_AUTH_CODE_TTL_SECONDS)

    auth_code = VSCodeAuthCode(
        code_hash=hash_pat_secret(code),
        user_id=current_user.id,
        created_at=now,
        expires_at=expires_at,
    )
    db.add(auth_code)
    db.commit()

    redirect_target = _resolve_redirect_uri(redirect_uri)
    redirect_target = _merge_query(redirect_target, {"code": code})
    return RedirectResponse(url=redirect_target, status_code=status.HTTP_302_FOUND)


@router.post("/auth/vscode/exchange", response_model=PATCreateResponse)
def vscode_auth_exchange(
    payload: VSCodeAuthExchangeRequest,
    db: Session = Depends(get_db),
):
    code = (payload.auth_code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="auth_code is required")

    code_hash = hash_pat_secret(code)
    record = (
        db.query(VSCodeAuthCode)
        .filter(VSCodeAuthCode.code_hash == code_hash)
        .first()
    )
    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired auth code")
    if record.used_at is not None:
        raise HTTPException(status_code=400, detail="Auth code already used")

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=400, detail="Auth code expired")

    now = datetime.now(timezone.utc)
    record.used_at = now

    pat_id = str(uuid.uuid4())
    secret = secrets.token_urlsafe(24)
    token_value = f"pat_{pat_id}.{secret}"
    pat = PersonalAccessToken(
        id=pat_id,
        user_id=record.user_id,
        name="VS Code Extension",
        scopes=VSCODE_DEFAULT_SCOPES,
        token_hash=hash_pat_secret(secret),
        created_at=now,
    )

    db.add(record)
    db.add(pat)
    db.commit()
    db.refresh(pat)
    return PATCreateResponse(token=token_value, pat=pat)
