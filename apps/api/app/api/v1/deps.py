import hashlib
import hmac
import os
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import config
from database import SessionLocal
from models import ChatInstance, PersonalAccessToken, Room, RoomMember, Task, User, ChatRoomAccess
from app.services.system_agent import ensure_system_agent_exists

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = config.SECRET_KEY
ALGORITHM = config.ALGORITHM if hasattr(config, "ALGORITHM") else os.getenv("ALGORITHM", "HS256")
PAT_PEPPER = os.getenv("PAT_PEPPER", SECRET_KEY or "pat-secret")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_pat_secret(secret: str) -> str:
    return hashlib.sha256(f"{PAT_PEPPER}:{secret}".encode("utf-8")).hexdigest()


def _verify_pat(db: Session, token: str) -> Optional[PersonalAccessToken]:
    """
    Validate a PAT of the form pat_<id>.<secret>. Returns PAT row when valid.
    """
    if not token or not token.startswith("pat_") or "." not in token:
        return None
    prefix_and_id, secret = token.split(".", 1)
    pat_id = prefix_and_id
    if pat_id.startswith("pat_"):
        pat_id = pat_id[4:]

    pat: Optional[PersonalAccessToken] = (
        db.query(PersonalAccessToken)
        .filter(PersonalAccessToken.id == pat_id)
        .first()
    )
    if not pat:
        return None
    if pat.revoked_at is not None:
        return None
    if pat.expires_at:
        expires_at = pat.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return None

    if not hmac.compare_digest(hash_pat_secret(secret), pat.token_hash):
        return None

    pat.last_used_at = datetime.now(timezone.utc)
    db.add(pat)
    db.commit()
    db.refresh(pat)
    return pat


def _get_user_from_jwt(db: Session, token: str, request: Optional[Request] = None) -> Optional[User]:
    """
    Decode JWT token and return user. Supports both session JWTs and OAuth access tokens.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            return None
        
        # Check if this is an OAuth access token
        token_type = payload.get("token_type")
        if token_type == "access":
            # OAuth access token - check if revoked
            from models import OAuthAccessToken
            jti = payload.get("jti")
            if jti:
                access_record = db.query(OAuthAccessToken).filter(
                    OAuthAccessToken.id == jti
                ).first()
                if access_record and access_record.revoked_at:
                    return None
            
            # Set scopes from OAuth token
            if request:
                scope = payload.get("scope", "")
                request.state.token_scopes = scope.split() if scope else []
        
    except JWTError:
        return None
    return db.get(User, user_id)


def get_current_user(
    request: Request,
    authorization: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    logger.info("[AUTH] Checking authentication for request to %s", request.url.path)
    user: User | None = None

    # Prefer PAT from Authorization header
    if authorization and authorization.scheme.lower() == "bearer":
        token = authorization.credentials
        pat = _verify_pat(db, token)
        if pat:
            request.state.token_scopes = pat.scopes or []
            user = pat.user
            logger.info(
                "[AUTH] Authenticated via PAT as user_id=%s email=%s",
                getattr(user, "id", None),
                getattr(user, "email", None),
            )
        else:
            # Try OAuth/JWT in Authorization header
            user = _get_user_from_jwt(db, token, request)
            if user:
                logger.info(
                    "[AUTH] Authenticated via Authorization header as user_id=%s email=%s",
                    getattr(user, "id", None),
                    getattr(user, "email", None),
                )

    # Legacy cookie auth fallback
    if user is None:
        cookie_token = request.cookies.get("access_token")
        if cookie_token:
            user = _get_user_from_jwt(db, cookie_token, request)
            if user:
                logger.info(
                    "[AUTH] Authenticated via cookie as user_id=%s email=%s",
                    getattr(user, "id", None),
                    getattr(user, "email", None),
                )

    if not user:
        logger.warning("[AUTH] Authentication failed - no valid user found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        ensure_system_agent_exists(user.id, db)
    except Exception as exc:
        logger.warning("Failed to ensure system agent exists", extra={"error": str(exc)})

    return user



def require_workspace_member(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Room:
    room = db.query(Room).filter(Room.id == workspace_id).first()
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    membership = (
        db.query(RoomMember)
        .filter(RoomMember.room_id == workspace_id, RoomMember.user_id == current_user.id)
        .first()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden for workspace")
    return room


def require_scope(required_scope: str):
    """
    Minimal PAT scope enforcement. JWT-based auth bypasses scope checks to avoid blocking
    internal/legacy callers that do not use PAT scopes.
    """

    def _checker(request: Request):
        scopes = getattr(request.state, "token_scopes", None)
        if scopes is None:
            return
        if required_scope in scopes:
            return
        if required_scope.endswith(":read") and "read" in scopes:
            return
        if required_scope.endswith(":write") and "write" in scopes:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient scope",
        )

    return _checker


# Simple in-memory rate limiter keyed by path + user/addr
_rate_limit_state: dict[str, list[float]] = {}


def rate_limit_dep(key: str, *, max_calls: int, window_seconds: int):
    def dependency(request: Request, current_user: User = Depends(get_current_user)):
        import time

        now = time.time()
        uid = getattr(current_user, "id", None)
        addr = request.client.host if request.client else "anon"
        bucket_key = f"{key}:{uid or addr}"
        entries = _rate_limit_state.setdefault(bucket_key, [])
        entries[:] = [ts for ts in entries if now - ts < window_seconds]
        if len(entries) >= max_calls:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
            )
        entries.append(now)

    return dependency


def get_chat_for_user(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatInstance:
    chat = db.query(ChatInstance).filter(ChatInstance.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")
    require_workspace_member(chat.room_id, current_user, db)
    return chat


def get_chat_room_ids(chat_id: str, db: Session) -> list[str]:
    """
    Fetch all room_ids a chat is linked to via chat_room_access.
    Falls back to the chat's primary room_id if no links exist.
    """
    room_ids = [
        rid for (rid,) in db.query(ChatRoomAccess.room_id).filter(ChatRoomAccess.chat_id == chat_id).all()
    ]
    return room_ids


def get_chat_for_user_m2m(
    chat_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatInstance:
    """
    M2M-aware chat authorization:
    - Load chat by id
    - Allowed rooms = chat_room_access entries (fallback to chat.room_id)
    - User must be a member of at least one allowed room
    """
    chat = db.query(ChatInstance).filter(ChatInstance.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found")

    chat_rooms = get_chat_room_ids(chat_id, db)
    if not chat_rooms and chat.room_id:
        chat_rooms = [chat.room_id]

    if not chat_rooms:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chat has no accessible rooms")

    user_room_ids = {
        rid for (rid,) in db.query(RoomMember.room_id).filter(RoomMember.user_id == current_user.id).all()
    }

    if not user_room_ids.intersection(set(chat_rooms)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden for chat")

    return chat


def resolve_workspace_chat_ids(workspace_id: str, db: Session, *, logger_obj: Optional[logging.Logger] = None):
    """
    Return a deduped list of chat_ids associated to a workspace via chat_room_access or legacy room_id.
    """
    access_ids = [
        cid for (cid,) in db.query(ChatRoomAccess.chat_id).filter(ChatRoomAccess.room_id == workspace_id).all()
    ]
    legacy_ids = [cid for (cid,) in db.query(ChatInstance.id).filter(ChatInstance.room_id == workspace_id).all()]

    combined = list(dict.fromkeys(access_ids + legacy_ids))
    legacy_only = [cid for cid in legacy_ids if cid not in set(access_ids)]

    if logger_obj and legacy_only:
        logger_obj.info(
            "[ChatResolver] Legacy room_id contributed %s chats for workspace %s",
            len(legacy_only),
            workspace_id,
        )

    return combined


def get_task_for_user(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task or not task.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    require_workspace_member(task.workspace_id, current_user, db)
    return task
