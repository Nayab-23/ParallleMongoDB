import os
import uuid
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request as StarletteRequest
from pydantic import BaseModel

from database import SessionLocal
from models import (
    User as UserORM,
    UserCredential as UserCredentialORM,
    Organization as OrganizationORM,
    Room as RoomORM,
    RoomMember as RoomMemberORM,
    UserOut,
    CreateUserRequest,
    AuthLoginRequest,
    ActivateRequest,
)
from config import config
from app.api.dependencies.auth import (
    is_platform_admin_user,
    maybe_persist_platform_admin,
    parse_admin_emails,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="")

SECRET_KEY = config.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440
AUTH_COOKIE_NAME = "access_token"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

oauth = OAuth()
google = oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=60))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


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


def generate_invite_code() -> str:
    return secrets.token_urlsafe(8)


def ensure_admin_org(db: Session, user: UserORM) -> OrganizationORM | None:
    admin_emails = parse_admin_emails()
    if not is_platform_admin_user(user, admin_emails):
        return None
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
    db.flush()

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

    logger.info(f"[ADMIN ORG] Created admin org for {user.email}")
    return org


def get_current_user(request: Request, db: Session = Depends(get_db)) -> UserORM:
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
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = db.get(UserORM, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    admin_emails = parse_admin_emails()
    maybe_persist_platform_admin(user, db, admin_emails)
    return user


@router.post("/auth/register", response_model=UserOut)
def register(payload: CreateUserRequest, db: Session = Depends(get_db)):
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

    # Create personal room + PA chat for the new user
    try:
        from models import Room as RoomORM, RoomMember as RoomMemberORM, ChatInstance as ChatInstanceORM

        personal_room = RoomORM(
            id=str(uuid.uuid4()),
            org_id=user.org_id,
            name=f"{user.name}'s Room",
            project_summary="",
            memory_summary="",
            created_at=datetime.now(timezone.utc),
        )
        db.add(personal_room)

        membership = RoomMemberORM(
            id=str(uuid.uuid4()),
            room_id=personal_room.id,
            user_id=user.id,
            role_in_room="owner",
        )
        db.add(membership)

        pa_chat = ChatInstanceORM(
            id=str(uuid.uuid4()),
            room_id=personal_room.id,
            name="Parallel Assistant",
            created_by_user_id=user.id,
            created_at=datetime.now(timezone.utc),
            last_message_at=datetime.now(timezone.utc),
        )
        db.add(pa_chat)

        db.commit()
        logger.info(f"[Signup] Created personal room + PA chat for {user.email}")
    except Exception as e:
        logger.warning(f"[Signup] Failed to create personal room/PA chat: {e}")

    token = create_access_token({"sub": user.id})
    user_out = UserOut.model_validate(user)
    data = jsonable_encoder(user_out)
    resp = JSONResponse(content=data)
    set_auth_cookie(resp, token)
    return resp


@router.post("/auth/login")
def login(payload: AuthLoginRequest, db: Session = Depends(get_db)):
    user = db.query(UserORM).filter(UserORM.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    cred = db.get(UserCredentialORM, user.id)
    if not cred or not verify_password(payload.password, cred.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    try:
        ensure_admin_org(db, user)
    except Exception:
        logger.exception("Failed to ensure admin org on login")

    token = create_access_token({"sub": user.id})
    resp = JSONResponse({"ok": True})
    set_auth_cookie(resp, token)
    return resp


@router.post("/auth/logout")
def logout():
    resp = JSONResponse({"ok": True})
    clear_auth_cookie(resp)
    return resp


@router.get("/auth/google/login")
async def google_login(request: StarletteRequest):
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI") or f"{BACKEND_URL}/api/auth/google/callback"
    return await google.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback")
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

    try:
        ensure_admin_org(db, user)
    except Exception:
        logger.exception("Failed to ensure admin org on Google callback")

    token_str = create_access_token({"sub": user.id})
    frontend_app_url = os.getenv("FRONTEND_APP_URL") or config.FRONTEND_APP_URL
    resp = RedirectResponse(url=frontend_app_url)
    set_auth_cookie(resp, token_str)
    return resp


@router.get("/debug/google")
def debug_google():
    return {
        "GOOGLE_REDIRECT_URI": os.getenv("GOOGLE_REDIRECT_URI"),
        "computed_redirect_uri": os.getenv("GOOGLE_REDIRECT_URI") or f"{BACKEND_URL}/api/auth/google/callback",
    }


@router.get("/me")
def read_me(current_user: UserORM = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(UserORM).filter(UserORM.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    needs_invite = user.org_id is None
    admin_emails = parse_admin_emails()
    is_platform_admin = is_platform_admin_user(user, admin_emails)

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "org_id": user.org_id,
        "permissions": user.permissions,
        "needs_invite": needs_invite,
        "is_platform_admin": is_platform_admin,
    }


@router.post("/org/join")
def join_organization(
    payload: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)
    code = (payload or {}).get("invite_code")
    if not code:
        raise HTTPException(status_code=400, detail="invite_code is required")
    org = db.query(OrganizationORM).filter(OrganizationORM.invite_code == code).first()
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


@router.post("/activate", response_model=UserOut)
def activate_account(
    payload: ActivateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if payload.role:
        if config.ROLE_OPTIONS and payload.role not in config.ROLE_OPTIONS:
            raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(config.ROLE_OPTIONS)}")
        user.role = payload.role
    if not user.role:
        user.role = "Member"
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
