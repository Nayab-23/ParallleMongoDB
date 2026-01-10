"""
OAuth 2.1 Authorization Code + PKCE implementation for VS Code extension.

Endpoints:
- GET /oauth/authorize - Authorization endpoint (shows approval page)
- POST /oauth/authorize - Submit approval
- POST /oauth/token - Token endpoint (code exchange & refresh)
- POST /oauth/revoke - Token revocation
- GET /oauth/me - Token introspection (user info)
"""
import base64
import hashlib
import hmac
import logging
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlencode, urlparse, urlsplit, urlunsplit, urlunparse, parse_qsl, unquote_plus

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import config
from database import SessionLocal
from models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthRefreshToken,
    Room,
    RoomMember,
    User,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth", tags=["oauth"])

# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
ALGORITHM = "HS256"
AUTH_CODE_EXPIRE_MINUTES = 10
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour
REFRESH_TOKEN_EXPIRE_DAYS = 30

@dataclass
class CachedAuthCode:
    id: str
    client_id: str
    user_id: str
    redirect_uri: str
    scope: str
    code_challenge: str
    code_challenge_method: str
    expires_at: datetime
    used_at: Optional[datetime] = None

AUTH_CODE_CACHE: dict[str, CachedAuthCode] = {}

# Default scopes/redirects for VS Code OAuth client
DEFAULT_VSCODE_SCOPES = [
    "openid",
    "profile",
    "email",
    "tasks:read",
    "tasks:write",
    "chats:read",
    "chats:write",
    "messages:read",
    "files:read",
    "files:search",
    "workspaces:read",
    "edits:propose",
    "edits:apply",
    "commands:run",
    "terminal:write",
    "edits:undo",
    "completions:read",
    "index:read",
    "index:write",
    "explain:read",
    "tests:write",
    "git:read",
    "read",
    "write",
]
DEFAULT_VSCODE_REDIRECT_URIS = [
    "vscode://parallel.parallel-vscode/auth-callback",
    "vscode://parallelagent.parallel/auth-callback",
    "http://localhost:54321/callback",
    "http://127.0.0.1:54321/callback",
]
EXTRA_OAUTH_REDIRECT_URIS = [
    uri.strip()
    for uri in os.getenv("OAUTH_REDIRECT_URI_ALLOWLIST", "").split(",")
    if uri.strip()
]
EXTRA_OAUTH_SCOPES = [
    scope.strip()
    for scope in os.getenv("OAUTH_EXTRA_SCOPES", "").split(",")
    if scope.strip()
]

# Rate limiting state (in-memory; production should use Redis)
_rate_limit_state: dict[str, list[float]] = {}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _rate_limit(key: str, max_calls: int, window_seconds: int, request: Request):
    """Simple in-memory rate limiter."""
    import time
    now = time.time()
    addr = request.client.host if request.client else "anon"
    bucket_key = f"{key}:{addr}"
    entries = _rate_limit_state.setdefault(bucket_key, [])
    entries[:] = [ts for ts in entries if now - ts < window_seconds]
    if len(entries) >= max_calls:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )
    entries.append(now)


def _hash_token(token: str) -> str:
    """Hash a token for secure storage."""
    return hashlib.sha256(f"{SECRET_KEY}:{token}".encode()).hexdigest()

def _cache_auth_code(auth_code: OAuthAuthorizationCode) -> None:
    AUTH_CODE_CACHE[auth_code.id] = CachedAuthCode(
        id=auth_code.id,
        client_id=auth_code.client_id,
        user_id=auth_code.user_id,
        redirect_uri=auth_code.redirect_uri,
        scope=auth_code.scope,
        code_challenge=auth_code.code_challenge,
        code_challenge_method=auth_code.code_challenge_method,
        expires_at=auth_code.expires_at,
        used_at=auth_code.used_at,
    )

def _get_cached_auth_code(code: str) -> Optional[CachedAuthCode]:
    record = AUTH_CODE_CACHE.get(code)
    if not record:
        return None
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        AUTH_CODE_CACHE.pop(code, None)
        return None
    return record

def _mark_cached_auth_code_used(code: str) -> None:
    AUTH_CODE_CACHE.pop(code, None)


def _verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """Verify PKCE code_verifier against stored code_challenge."""
    if method != "S256":
        return False
    # S256: BASE64URL(SHA256(code_verifier))
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(computed_challenge, code_challenge)


def _merge_query(url: str, params: dict) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

def _normalize_auth_code(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return raw
    value = raw.strip()
    # Handle codes that arrive double-encoded or wrapped as a query string.
    for _ in range(2):
        decoded = unquote_plus(value)
        if decoded == value:
            break
        value = decoded.strip()
    if "code=" in value:
        parsed = dict(parse_qsl(value, keep_blank_values=True))
        candidate = parsed.get("code")
        if candidate:
            return candidate.strip()
    return value

def _normalize_redirect_uri(uri: str) -> str:
    if not uri:
        return uri
    try:
        parsed = urlparse(uri)
    except Exception:
        return uri
    if parsed.scheme in {"http", "https"}:
        host = parsed.hostname or ""
        if host in {"localhost", "127.0.0.1", "::1"}:
            netloc = "localhost"
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            return urlunparse(
                (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
            )
    return uri


def _frontend_login_url() -> str:
    return (
        os.getenv("FRONTEND_LOGIN_URL")
        or os.getenv("FRONTEND_APP_URL")
        or "/api/oauth/login"
    )


def _create_access_token(
    user_id: str,
    client_id: str,
    scope: str,
    expires_delta: Optional[timedelta] = None,
) -> tuple[str, str, datetime]:
    """Create a JWT access token. Returns (token, jti, expires_at)."""
    jti = str(uuid.uuid4())
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": user_id,
        "client_id": client_id,
        "scope": scope,
        "jti": jti,
        "iat": datetime.now(timezone.utc),
        "exp": expire,
        "token_type": "access",
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token, jti, expire


def _create_refresh_token() -> str:
    """Create a cryptographically secure refresh token."""
    return secrets.token_urlsafe(32)


def _get_current_user_from_cookie(request: Request, db: Session) -> Optional[User]:
    """Get current user from session cookie (for web-based authorization)."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            return None
    except JWTError:
        return None
    return db.get(User, user_id)


def _validate_redirect_uri(client: OAuthClient, redirect_uri: str) -> bool:
    """Validate redirect_uri against client's registered URIs (exact match)."""
    allowed = list(client.redirect_uris or [])
    if client.id == "vscode-extension":
        allowed.extend(DEFAULT_VSCODE_REDIRECT_URIS)
    allowed.extend(EXTRA_OAUTH_REDIRECT_URIS)
    normalized = _normalize_redirect_uri(redirect_uri)
    normalized_allowed = {_normalize_redirect_uri(uri) for uri in allowed}
    return normalized in normalized_allowed


def _validate_scopes(client: OAuthClient, requested_scopes: str) -> tuple[bool, list[str]]:
    """Validate requested scopes against client's allowed scopes."""
    allowed = set(client.allowed_scopes or [])
    if client.id == "vscode-extension":
        allowed.update(DEFAULT_VSCODE_SCOPES)
    allowed.update(EXTRA_OAUTH_SCOPES)
    requested = set(requested_scopes.split()) if requested_scopes else set()
    if not requested:
        return True, sorted(allowed)
    invalid = requested - allowed
    if invalid:
        return False, list(invalid)
    return True, sorted(requested)


# ==============================================================================
# Pydantic Models
# ==============================================================================

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: Optional[str] = None
    scope: str


class TokenErrorResponse(BaseModel):
    error: str
    error_description: Optional[str] = None


class OAuthMeResponse(BaseModel):
    id: str
    email: str
    name: str
    scope: str


class ConnectedApp(BaseModel):
    client_id: str
    name: str
    scopes: List[str]
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class ConnectedAppsResponse(BaseModel):
    apps: List[ConnectedApp]


class RevokeConnectedAppRequest(BaseModel):
    client_id: str


# ==============================================================================
# Authorization Endpoint
# ==============================================================================

@router.get("/authorize")
async def authorize_get(
    request: Request,
    response_type: str = Query(...),
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    scope: str = Query(default=""),
    state: str = Query(default=""),
    code_challenge: str = Query(...),
    code_challenge_method: str = Query(default="S256"),
    workspace_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    OAuth 2.1 Authorization Endpoint.
    
    If user is logged in, show approval page.
    If not logged in, redirect to login with return URL.
    """
    # Rate limit
    _rate_limit("oauth_authorize", max_calls=30, window_seconds=60, request=request)
    
    # Validate response_type
    if response_type != "code":
        return _error_redirect(
            redirect_uri, state, "unsupported_response_type",
            "Only 'code' response type is supported"
        )
    
    # Validate client
    client = db.query(OAuthClient).filter(OAuthClient.id == client_id).first()
    if not client or not client.is_active:
        return _error_redirect(
            redirect_uri, state, "invalid_client",
            "Unknown or inactive client"
        )
    
    # Validate redirect_uri (MUST be exact match)
    if not _validate_redirect_uri(client, redirect_uri):
        # Don't redirect to unvalidated URI - return error directly
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid redirect_uri"
        )
    
    # Validate PKCE (required for public clients)
    if client.client_type == "public" and not code_challenge:
        return _error_redirect(
            redirect_uri, state, "invalid_request",
            "PKCE code_challenge required for public clients"
        )
    
    if code_challenge_method != "S256":
        return _error_redirect(
            redirect_uri, state, "invalid_request",
            "Only S256 code_challenge_method is supported"
        )
    
    # Validate scopes
    valid_scopes, scope_result = _validate_scopes(client, scope)
    if not valid_scopes:
        return _error_redirect(
            redirect_uri, state, "invalid_scope",
            f"Invalid scopes: {', '.join(scope_result)}"
        )
    final_scope = " ".join(scope_result)
    
    # Check if user is logged in
    user = _get_current_user_from_cookie(request, db)
    
    if not user:
        # Redirect to frontend login (or fallback server login) with return URL
        login_url = _merge_query(_frontend_login_url(), {"return_to": str(request.url)})
        return RedirectResponse(url=login_url, status_code=302)
    
    # Load workspaces for selection
    workspaces = (
        db.query(Room)
        .join(RoomMember, RoomMember.room_id == Room.id)
        .filter(RoomMember.user_id == user.id)
        .order_by(Room.name.asc())
        .all()
    )
    workspace_options = [{"id": w.id, "name": w.name} for w in workspaces]
    selected_workspace_id = workspace_id
    if selected_workspace_id:
        valid_ids = {w["id"] for w in workspace_options}
        if selected_workspace_id not in valid_ids:
            return _error_redirect(
                redirect_uri,
                state,
                "invalid_request",
                "Invalid workspace selection",
            )
    elif workspace_options:
        selected_workspace_id = workspace_options[0]["id"]

    # Show approval page
    return _render_approval_page(
        client=client,
        user=user,
        scope=final_scope,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        workspaces=workspace_options,
        workspace_id=selected_workspace_id,
    )


@router.post("/authorize")
async def authorize_post(
    request: Request,
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    scope: str = Form(...),
    state: str = Form(default=""),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form(default="S256"),
    workspace_id: Optional[str] = Form(default=None),
    action: str = Form(...),  # "approve" or "deny"
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Handle approval form submission.
    """
    # Rate limit
    _rate_limit("oauth_authorize_post", max_calls=20, window_seconds=60, request=request)
    
    # Verify user is logged in
    user = _get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Verify CSRF token (simple check - in production, use proper CSRF)
    expected_csrf = _hash_token(f"csrf:{user.id}:{client_id}")[:32]
    if not hmac.compare_digest(csrf_token, expected_csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    
    # Validate client
    client = db.query(OAuthClient).filter(OAuthClient.id == client_id).first()
    if not client or not client.is_active:
        return _error_redirect(redirect_uri, state, "invalid_client", "Unknown client")
    
    # Validate redirect_uri again
    if not _validate_redirect_uri(client, redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")
    
    # Handle denial
    if action == "deny":
        return _error_redirect(redirect_uri, state, "access_denied", "User denied authorization")
    
    if workspace_id:
        membership = (
            db.query(RoomMember)
            .filter(RoomMember.user_id == user.id, RoomMember.room_id == workspace_id)
            .first()
        )
        if not membership:
            raise HTTPException(status_code=403, detail="Invalid workspace selection")

    # Generate authorization code
    code = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=AUTH_CODE_EXPIRE_MINUTES)
    
    auth_code = OAuthAuthorizationCode(
        id=code,
        client_id=client_id,
        user_id=user.id,
        redirect_uri=redirect_uri,
        scope=scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        expires_at=expires_at,
    )
    db.add(auth_code)
    db.commit()
    _cache_auth_code(auth_code)
    
    logger.info(f"[OAuth] Authorization code issued for user {user.id[:8]}... client {client_id}")
    
    # Redirect back to client with code
    params = {"code": code}
    if state:
        params["state"] = state
    if workspace_id:
        params["workspace_id"] = workspace_id
    
    redirect_url = f"{redirect_uri}?{urlencode(params)}"
    return RedirectResponse(url=redirect_url, status_code=302)


@router.get("/login")
async def oauth_login_page(
    request: Request,
    return_to: str = Query(...),
):
    """
    Simple login page for OAuth flow.
    In production, this would integrate with your main login UI.
    """
    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sign In - Parallel</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                   background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                   min-height: 100vh; display: flex; align-items: center; justify-content: center; margin: 0; }}
            .card {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                    width: 100%; max-width: 400px; }}
            h1 {{ margin: 0 0 8px; color: #1a1a2e; font-size: 24px; }}
            p {{ color: #666; margin: 0 0 24px; }}
            input {{ width: 100%; padding: 12px; margin: 8px 0; border: 1px solid #ddd; border-radius: 8px;
                    box-sizing: border-box; font-size: 16px; }}
            button {{ width: 100%; padding: 14px; background: #667eea; color: white; border: none;
                     border-radius: 8px; font-size: 16px; cursor: pointer; margin-top: 16px; }}
            button:hover {{ background: #5a6fd6; }}
            .error {{ color: #e53935; margin-top: 16px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Sign in to Parallel</h1>
            <p>Sign in to authorize the VS Code extension</p>
            <form method="POST" action="/api/oauth/login">
                <input type="hidden" name="return_to" value="{return_to}" />
                <input type="email" name="email" placeholder="Email" required />
                <input type="password" name="password" placeholder="Password" required />
                <button type="submit">Sign In</button>
            </form>
        </div>
    </body>
    </html>
    """)


@router.post("/login")
async def oauth_login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    return_to: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Handle login form submission for OAuth flow.
    """
    from app.api.auth_routes import verify_password
    from models import UserCredential
    
    # Rate limit
    _rate_limit("oauth_login", max_calls=10, window_seconds=60, request=request)
    
    # Verify credentials
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return HTMLResponse(content=_login_error_page(return_to, "Invalid credentials"), status_code=401)
    
    cred = db.get(UserCredential, user.id)
    if not cred or not verify_password(password, cred.password_hash):
        return HTMLResponse(content=_login_error_page(return_to, "Invalid credentials"), status_code=401)
    
    # Create session cookie and redirect back to authorization
    from app.api.auth_routes import create_access_token, set_auth_cookie
    token = create_access_token({"sub": user.id})
    
    response = RedirectResponse(url=return_to, status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        max_age=60 * 60 * 24 * 7,
        path="/",
        domain=config.COOKIE_DOMAIN,
    )
    return response


# ==============================================================================
# Token Endpoint
# ==============================================================================

@router.post("/token", response_model=TokenResponse)
async def token_endpoint(
    request: Request,
    grant_type: str = Form(...),
    code: Optional[str] = Form(default=None),
    redirect_uri: Optional[str] = Form(default=None),
    code_verifier: Optional[str] = Form(default=None),
    refresh_token: Optional[str] = Form(default=None),
    client_id: str = Form(...),
    scope: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
):
    """
    OAuth 2.1 Token Endpoint.
    
    Supports:
    - grant_type=authorization_code (with PKCE)
    - grant_type=refresh_token
    """
    # Rate limit
    _rate_limit("oauth_token", max_calls=20, window_seconds=60, request=request)
    
    # Validate client
    client = db.query(OAuthClient).filter(OAuthClient.id == client_id).first()
    if not client or not client.is_active:
        return _token_error("invalid_client", "Unknown or inactive client")
    
    if grant_type == "authorization_code":
        return await _handle_authorization_code_grant(
            db, client, code, redirect_uri, code_verifier
        )
    elif grant_type == "refresh_token":
        return await _handle_refresh_token_grant(
            db, client, refresh_token, scope
        )
    else:
        return _token_error("unsupported_grant_type", f"Grant type '{grant_type}' not supported")


async def _handle_authorization_code_grant(
    db: Session,
    client: OAuthClient,
    code: Optional[str],
    redirect_uri: Optional[str],
    code_verifier: Optional[str],
) -> JSONResponse:
    """Handle authorization_code grant type."""
    if not code or not redirect_uri or not code_verifier:
        return _token_error("invalid_request", "Missing required parameters")
    code = _normalize_auth_code(code)
    redirect_uri = redirect_uri.strip()
    code_verifier = code_verifier.strip()
    
    # Find authorization code
    auth_code = db.query(OAuthAuthorizationCode).filter(
        OAuthAuthorizationCode.id == code
    ).first()
    
    if not auth_code:
        auth_code = _get_cached_auth_code(code)
        if not auth_code:
            logger.warning(
                "[OAuth] Authorization code not found (client=%s code_prefix=%s len=%s)",
                client.id,
                (code or "")[:8],
                len(code or ""),
            )
            return _token_error("invalid_grant", "Invalid authorization code")
    
    # Check if already used (one-time use)
    if auth_code.used_at is not None:
        # Possible token replay attack - revoke all tokens for this code
        logger.warning(f"[OAuth] Authorization code reuse detected: {code[:8]}...")
        return _token_error("invalid_grant", "Authorization code already used")
    
    # Check expiration (normalize timezone for SQLite compatibility)
    expires_at = auth_code.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        return _token_error("invalid_grant", "Authorization code expired")
    
    # Verify client_id matches
    if auth_code.client_id != client.id:
        return _token_error("invalid_grant", "Client mismatch")
    
    # Verify redirect_uri matches
    if _normalize_redirect_uri(auth_code.redirect_uri) != _normalize_redirect_uri(redirect_uri):
        # Allow mismatch for VS Code extension if both URIs are registered/allowed.
        if client.id != "vscode-extension":
            return _token_error("invalid_grant", "Redirect URI mismatch")
        if not (_validate_redirect_uri(client, redirect_uri) and _validate_redirect_uri(client, auth_code.redirect_uri)):
            return _token_error("invalid_grant", "Redirect URI mismatch")
    
    # Verify PKCE
    if not _verify_pkce(code_verifier, auth_code.code_challenge, auth_code.code_challenge_method):
        return _token_error("invalid_grant", "Invalid code_verifier")
    
    # Mark code as used
    auth_code.used_at = datetime.now(timezone.utc)
    if isinstance(auth_code, CachedAuthCode):
        _mark_cached_auth_code_used(code)
    else:
        db.add(auth_code)
    
    # Issue tokens
    return _issue_tokens(db, client, auth_code.user_id, auth_code.scope)


async def _handle_refresh_token_grant(
    db: Session,
    client: OAuthClient,
    refresh_token_value: Optional[str],
    requested_scope: Optional[str],
) -> JSONResponse:
    """Handle refresh_token grant type with rotation."""
    if not refresh_token_value:
        return _token_error("invalid_request", "Missing refresh_token")
    
    # Find refresh token
    token_hash = _hash_token(refresh_token_value)
    refresh_token = db.query(OAuthRefreshToken).filter(
        OAuthRefreshToken.token_hash == token_hash
    ).first()
    
    if not refresh_token:
        return _token_error("invalid_grant", "Invalid refresh token")
    
    # Check if revoked
    if refresh_token.revoked_at is not None:
        logger.warning(f"[OAuth] Revoked refresh token used: {refresh_token.id[:8]}...")
        return _token_error("invalid_grant", "Refresh token revoked")
    
    # Check if already rotated (replaced)
    if refresh_token.replaced_by_id is not None:
        # Token reuse - possible theft, revoke entire chain
        logger.warning(f"[OAuth] Refresh token reuse detected: {refresh_token.id[:8]}... - revoking chain")
        _revoke_token_chain(db, refresh_token)
        return _token_error("invalid_grant", "Refresh token already used")
    
    # Check expiration (normalize timezone for SQLite compatibility)
    if refresh_token.expires_at:
        expires_at = refresh_token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            return _token_error("invalid_grant", "Refresh token expired")
    
    # Verify client matches
    if refresh_token.client_id != client.id:
        return _token_error("invalid_grant", "Client mismatch")
    
    # Validate requested scope (must be subset of original)
    final_scope = refresh_token.scope
    if requested_scope:
        original_scopes = set(refresh_token.scope.split())
        requested_scopes = set(requested_scope.split())
        if not requested_scopes.issubset(original_scopes):
            return _token_error("invalid_scope", "Cannot expand scope on refresh")
        final_scope = requested_scope
    
    # Issue new tokens (rotation)
    return _issue_tokens(
        db, client, refresh_token.user_id, final_scope,
        old_refresh_token=refresh_token
    )


def _issue_tokens(
    db: Session,
    client: OAuthClient,
    user_id: str,
    scope: str,
    old_refresh_token: Optional[OAuthRefreshToken] = None,
) -> JSONResponse:
    """Issue access and refresh tokens."""
    # Create access token (JWT)
    access_token, jti, access_expires = _create_access_token(
        user_id, client.id, scope,
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    # Create refresh token
    new_refresh_value = _create_refresh_token()
    refresh_expires = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    new_refresh = OAuthRefreshToken(
        id=str(uuid.uuid4()),
        token_hash=_hash_token(new_refresh_value),
        client_id=client.id,
        user_id=user_id,
        scope=scope,
        expires_at=refresh_expires,
    )
    db.add(new_refresh)
    
    # Record access token
    access_record = OAuthAccessToken(
        id=jti,
        token_hash=_hash_token(access_token)[:64],
        client_id=client.id,
        user_id=user_id,
        refresh_token_id=new_refresh.id,
        scope=scope,
        expires_at=access_expires,
    )
    db.add(access_record)
    
    # If rotating, mark old token as replaced
    if old_refresh_token:
        old_refresh_token.replaced_by_id = new_refresh.id
        db.add(old_refresh_token)
    
    db.commit()
    
    logger.info(f"[OAuth] Tokens issued for user {user_id[:8]}... client {client.id}")
    
    return JSONResponse(content={
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "refresh_token": new_refresh_value,
        "scope": scope,
    })


def _revoke_token_chain(db: Session, token: OAuthRefreshToken):
    """Revoke a refresh token and all tokens in its chain."""
    now = datetime.now(timezone.utc)
    
    # Revoke this token
    token.revoked_at = now
    db.add(token)
    
    # Revoke any tokens that replaced this one
    next_token = db.query(OAuthRefreshToken).filter(
        OAuthRefreshToken.id == token.replaced_by_id
    ).first() if token.replaced_by_id else None
    
    while next_token:
        next_token.revoked_at = now
        db.add(next_token)
        next_token = db.query(OAuthRefreshToken).filter(
            OAuthRefreshToken.id == next_token.replaced_by_id
        ).first() if next_token.replaced_by_id else None
    
    db.commit()


# ==============================================================================
# Revoke Endpoint
# ==============================================================================

@router.post("/revoke")
async def revoke_endpoint(
    request: Request,
    token: str = Form(...),
    token_type_hint: Optional[str] = Form(default=None),
    client_id: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    OAuth 2.0 Token Revocation (RFC 7009).
    Revokes refresh tokens and associated access tokens.
    """
    # Rate limit
    _rate_limit("oauth_revoke", max_calls=20, window_seconds=60, request=request)
    
    # Validate client
    client = db.query(OAuthClient).filter(OAuthClient.id == client_id).first()
    if not client or not client.is_active:
        # Per RFC 7009, invalid client should still return 200
        return JSONResponse(content={}, status_code=200)
    
    token_hash = _hash_token(token)
    
    # Try to find as refresh token first
    refresh = db.query(OAuthRefreshToken).filter(
        OAuthRefreshToken.token_hash == token_hash,
        OAuthRefreshToken.client_id == client_id,
    ).first()
    
    if refresh and refresh.revoked_at is None:
        _revoke_token_chain(db, refresh)
        logger.info(f"[OAuth] Refresh token revoked: {refresh.id[:8]}...")
    
    # Also check if it's an access token (by jti in hash)
    access = db.query(OAuthAccessToken).filter(
        OAuthAccessToken.token_hash == token_hash[:64],
        OAuthAccessToken.client_id == client_id,
    ).first()
    
    if access and access.revoked_at is None:
        access.revoked_at = datetime.now(timezone.utc)
        db.add(access)
        db.commit()
        logger.info(f"[OAuth] Access token revoked: {access.id[:8]}...")
    
    # Always return 200 per RFC 7009
    return JSONResponse(content={}, status_code=200)


# ==============================================================================
# Token Introspection / Me Endpoint
# ==============================================================================

@router.get("/me", response_model=OAuthMeResponse)
async def oauth_me(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Get current user info from OAuth access token.
    Used by VS Code extension to verify token and get user info.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    token = auth_header[7:]
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        scope = payload.get("scope", "")
        token_type = payload.get("token_type")
        
        if not user_id or token_type != "access":
            raise HTTPException(status_code=401, detail="Invalid token")
        
        # Check if token is revoked
        jti = payload.get("jti")
        if jti:
            access_record = db.query(OAuthAccessToken).filter(
                OAuthAccessToken.id == jti
            ).first()
            if access_record and access_record.revoked_at:
                raise HTTPException(status_code=401, detail="Token revoked")
        
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        return OAuthMeResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            scope=scope,
        )
        
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ==============================================================================
# Connected Apps Management
# ==============================================================================

@router.get("/apps", response_model=ConnectedAppsResponse)
async def list_connected_apps(
    request: Request,
    db: Session = Depends(get_db),
):
    user = _get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    now = datetime.now(timezone.utc)
    tokens = (
        db.query(OAuthRefreshToken)
        .filter(
            OAuthRefreshToken.user_id == user.id,
            OAuthRefreshToken.revoked_at.is_(None),
        )
        .all()
    )

    if not tokens:
        return ConnectedAppsResponse(apps=[])

    tokens_by_client: dict[str, list[OAuthRefreshToken]] = {}
    for token in tokens:
        expires_at = token.expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at and expires_at < now:
            continue
        tokens_by_client.setdefault(token.client_id, []).append(token)

    if not tokens_by_client:
        return ConnectedAppsResponse(apps=[])

    clients = (
        db.query(OAuthClient)
        .filter(OAuthClient.id.in_(list(tokens_by_client.keys())))
        .all()
    )
    client_lookup = {client.id: client for client in clients}

    apps: List[ConnectedApp] = []
    for client_id, refresh_tokens in tokens_by_client.items():
        client = client_lookup.get(client_id)
        if not client:
            continue
        scopes: set[str] = set()
        created_at = None
        last_used_at = None
        expires_at = None
        for token in refresh_tokens:
            if token.scope:
                scopes.update(token.scope.split())
            created_at = token.created_at if created_at is None else min(created_at, token.created_at)
            last_used_at = token.created_at if last_used_at is None else max(last_used_at, token.created_at)
            if token.expires_at:
                token_exp = token.expires_at
                if token_exp.tzinfo is None:
                    token_exp = token_exp.replace(tzinfo=timezone.utc)
                expires_at = token_exp if expires_at is None else max(expires_at, token_exp)

        apps.append(
            ConnectedApp(
                client_id=client.id,
                name=client.name,
                scopes=sorted(scopes),
                created_at=created_at or now,
                last_used_at=last_used_at,
                expires_at=expires_at,
            )
        )

    apps.sort(key=lambda app: app.last_used_at or app.created_at, reverse=True)
    return ConnectedAppsResponse(apps=apps)


@router.post("/apps/revoke")
async def revoke_connected_app(
    payload: RevokeConnectedAppRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    client = db.query(OAuthClient).filter(OAuthClient.id == payload.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="OAuth client not found")

    now = datetime.now(timezone.utc)
    refresh_query = db.query(OAuthRefreshToken).filter(
        OAuthRefreshToken.user_id == user.id,
        OAuthRefreshToken.client_id == payload.client_id,
        OAuthRefreshToken.revoked_at.is_(None),
    )
    refresh_count = refresh_query.count()

    if refresh_count == 0:
        raise HTTPException(status_code=404, detail="No active sessions for client")

    refresh_query.update({OAuthRefreshToken.revoked_at: now}, synchronize_session=False)
    db.query(OAuthAccessToken).filter(
        OAuthAccessToken.user_id == user.id,
        OAuthAccessToken.client_id == payload.client_id,
        OAuthAccessToken.revoked_at.is_(None),
    ).update({OAuthAccessToken.revoked_at: now}, synchronize_session=False)

    db.commit()
    logger.info(
        "[OAuth] Revoked %s sessions for user %s client %s",
        refresh_count,
        user.id[:8],
        payload.client_id,
    )

    return JSONResponse(content={"revoked": True, "count": refresh_count})


# ==============================================================================
# Helper Functions
# ==============================================================================

def _error_redirect(redirect_uri: str, state: str, error: str, error_description: str) -> RedirectResponse:
    """Redirect back to client with error."""
    params = {"error": error, "error_description": error_description}
    if state:
        params["state"] = state
    return RedirectResponse(url=f"{redirect_uri}?{urlencode(params)}", status_code=302)


def _token_error(error: str, description: str, status_code: int = 400) -> JSONResponse:
    """Return token endpoint error response."""
    return JSONResponse(
        content={"error": error, "error_description": description, "detail": description},
        status_code=status_code,
    )


def _render_approval_page(
    client: OAuthClient,
    user: User,
    scope: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    workspaces: List[dict],
    workspace_id: Optional[str],
) -> HTMLResponse:
    """Render the OAuth approval page."""
    csrf_token = _hash_token(f"csrf:{user.id}:{client.id}")[:32]
    
    scope_list = scope.split() if scope else []
    scope_html = "".join(f"<li>{s}</li>" for s in scope_list) if scope_list else "<li>Basic access</li>"

    workspace_html = ""
    workspace_input = ""
    if workspaces:
        if len(workspaces) == 1:
            workspace_name = workspaces[0]["name"]
            workspace_value = workspaces[0]["id"]
            workspace_html = f"""
            <div class="scopes">
                <h3>Workspace</h3>
                <p>{workspace_name}</p>
            </div>
            """
            workspace_input = f'<input type="hidden" name="workspace_id" value="{workspace_value}" />'
        else:
            options = []
            for workspace in workspaces:
                selected = " selected" if workspace["id"] == workspace_id else ""
                options.append(
                    f'<option value="{workspace["id"]}"{selected}>{workspace["name"]}</option>'
                )
            workspace_html = f"""
            <div class="scopes">
                <h3>Workspace</h3>
                <select name="workspace_id">
                    {''.join(options)}
                </select>
            </div>
            """
    else:
        workspace_html = """
        <div class="scopes">
            <h3>Workspace</h3>
            <p>No workspaces found. You can authorize now and select a workspace later.</p>
        </div>
        """
    
    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Authorize - Parallel</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                   background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                   min-height: 100vh; display: flex; align-items: center; justify-content: center; margin: 0; }}
            .card {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                    width: 100%; max-width: 450px; }}
            h1 {{ margin: 0 0 8px; color: #1a1a2e; font-size: 24px; }}
            .app-name {{ color: #667eea; font-weight: 600; }}
            p {{ color: #666; margin: 0 0 24px; line-height: 1.5; }}
            .user {{ background: #f5f5f5; padding: 12px 16px; border-radius: 8px; margin: 16px 0;
                    display: flex; align-items: center; gap: 12px; }}
            .user-avatar {{ width: 40px; height: 40px; background: #667eea; border-radius: 50%;
                          display: flex; align-items: center; justify-content: center; color: white; font-weight: 600; }}
            .user-info {{ flex: 1; }}
            .user-name {{ font-weight: 500; color: #1a1a2e; }}
            .user-email {{ font-size: 14px; color: #666; }}
            .scopes {{ margin: 20px 0; }}
            .scopes h3 {{ font-size: 14px; color: #666; margin: 0 0 8px; text-transform: uppercase; letter-spacing: 0.5px; }}
            .scopes ul {{ margin: 0; padding: 0 0 0 20px; color: #333; }}
            .scopes li {{ margin: 4px 0; }}
            select {{ width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; background: white; }}
            .buttons {{ display: flex; gap: 12px; margin-top: 24px; }}
            button {{ flex: 1; padding: 14px; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; }}
            .btn-deny {{ background: #f5f5f5; color: #666; }}
            .btn-deny:hover {{ background: #e5e5e5; }}
            .btn-approve {{ background: #667eea; color: white; }}
            .btn-approve:hover {{ background: #5a6fd6; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Authorize <span class="app-name">{client.name}</span></h1>
            <p>This application wants to access your Parallel account.</p>
            
            <div class="user">
                <div class="user-avatar">{user.name[0].upper() if user.name else 'U'}</div>
                <div class="user-info">
                    <div class="user-name">{user.name}</div>
                    <div class="user-email">{user.email}</div>
                </div>
            </div>
            
            <div class="scopes">
                <h3>Permissions requested</h3>
                <ul>{scope_html}</ul>
            </div>

            {workspace_html}
            
            <form method="POST" action="/api/oauth/authorize">
                <input type="hidden" name="client_id" value="{client.id}" />
                <input type="hidden" name="redirect_uri" value="{redirect_uri}" />
                <input type="hidden" name="scope" value="{scope}" />
                <input type="hidden" name="state" value="{state}" />
                <input type="hidden" name="code_challenge" value="{code_challenge}" />
                <input type="hidden" name="code_challenge_method" value="{code_challenge_method}" />
                <input type="hidden" name="csrf_token" value="{csrf_token}" />
                {workspace_input}
                
                <div class="buttons">
                    <button type="submit" name="action" value="deny" class="btn-deny">Deny</button>
                    <button type="submit" name="action" value="approve" class="btn-approve">Authorize</button>
                </div>
            </form>
        </div>
    </body>
    </html>
    """)


def _login_error_page(return_to: str, error: str) -> str:
    """Render login error page."""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sign In - Parallel</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                   background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                   min-height: 100vh; display: flex; align-items: center; justify-content: center; margin: 0; }}
            .card {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                    width: 100%; max-width: 400px; }}
            h1 {{ margin: 0 0 8px; color: #1a1a2e; font-size: 24px; }}
            p {{ color: #666; margin: 0 0 24px; }}
            input {{ width: 100%; padding: 12px; margin: 8px 0; border: 1px solid #ddd; border-radius: 8px;
                    box-sizing: border-box; font-size: 16px; }}
            button {{ width: 100%; padding: 14px; background: #667eea; color: white; border: none;
                     border-radius: 8px; font-size: 16px; cursor: pointer; margin-top: 16px; }}
            button:hover {{ background: #5a6fd6; }}
            .error {{ color: #e53935; margin-top: 16px; padding: 12px; background: #ffebee; border-radius: 8px; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Sign in to Parallel</h1>
            <p>Sign in to authorize the VS Code extension</p>
            <form method="POST" action="/api/oauth/login">
                <input type="hidden" name="return_to" value="{return_to}" />
                <input type="email" name="email" placeholder="Email" required />
                <input type="password" name="password" placeholder="Password" required />
                <button type="submit">Sign In</button>
            </form>
            <div class="error">{error}</div>
        </div>
    </body>
    </html>
    """
