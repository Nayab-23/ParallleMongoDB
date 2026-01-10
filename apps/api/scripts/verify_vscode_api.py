import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Stable, isolated test settings
os.environ.setdefault("DATABASE_URL", "sqlite:///./verify_vscode_api.db")
os.environ.setdefault("RAG_ENABLED", "false")
os.environ.setdefault("SECRET_KEY", "verifysecret")

from app.api.v1 import events as events_module  # noqa: E402
from app.api.v1 import router as api_v1_router  # noqa: E402
import app.api.v1.deps as deps  # noqa: E402
from app.core.settings import get_settings  # noqa: E402
import database  # noqa: E402
from database import Base  # noqa: E402
from models import (  # noqa: E402
    ChatInstance,
    ChatRoomAccess,
    DailyBrief,
    MemoryRecord,
    Message,
    Organization,
    PersonalAccessToken,
    Room,
    RoomMember,
    Task,
    User,
    WorkspaceEvent,
)
import main as main_app_module  # noqa: E402


# --- helpers and setup -------------------------------------------------------

SECRET_KEY = os.environ["SECRET_KEY"]


def configure_db():
    db_url = os.environ["DATABASE_URL"]
    url = make_url(db_url)
    connect_args = {"check_same_thread": False} if url.get_backend_name().startswith("sqlite") else {}
    engine = create_engine(
        db_url,
        future=True,
        connect_args=connect_args,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    # Rebind shared session/engine used across the app
    database.engine = engine
    database.SessionLocal = SessionLocal
    deps.SessionLocal = SessionLocal
    events_module.SessionLocal = SessionLocal

    # Create only the tables we exercise here (avoid pgvector on SQLite)
    tables = [
        Organization.__table__,
        User.__table__,
        Room.__table__,
        RoomMember.__table__,
        ChatInstance.__table__,
        ChatRoomAccess.__table__,
        Message.__table__,
        Task.__table__,
        PersonalAccessToken.__table__,
        WorkspaceEvent.__table__,
        DailyBrief.__table__,
    ]
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    elif engine.dialect.name != "sqlite":
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    Base.metadata.drop_all(bind=engine, tables=tables)
    Base.metadata.create_all(bind=engine, tables=tables)

    # RAG fallback expects the memories table to exist even in SQLite
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS memories"))
        if engine.dialect.name == "sqlite":
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY,
                        agent_id TEXT,
                        room_id TEXT,
                        user_id TEXT,
                        content TEXT,
                        importance_score REAL,
                        embedding TEXT,
                        metadata_json TEXT,
                        created_at TEXT
                    )
                    """
                )
            )
        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY,
                        agent_id TEXT,
                        room_id TEXT,
                        user_id TEXT,
                        content TEXT,
                        importance_score REAL,
                        embedding VECTOR(1536),
                        metadata_json JSONB,
                        created_at TIMESTAMPTZ
                    )
                    """
                )
            )
    return SessionLocal


def seed_data(SessionLocal):
    db = SessionLocal()
    try:
        org = Organization(id="org1", name="Org 1")
        user1 = User(id="u1", email="u1@example.com", name="User One", role="member", org_id=org.id)
        user2 = User(id="u2", email="u2@example.com", name="User Two", role="member", org_id=org.id)
        ws1 = Room(id="ws1", org_id=org.id, name="Workspace One")
        ws2 = Room(id="ws2", org_id=org.id, name="Workspace Two")
        chat1 = ChatInstance(id="chat1", room_id=ws1.id, name="WS1 Chat")
        chat2 = ChatInstance(id="chat2", room_id=ws2.id, name="WS2 Chat")
        m1 = RoomMember(id="rm1", room_id=ws1.id, user_id=user1.id, role_in_room="owner")
        m2 = RoomMember(id="rm2", room_id=ws2.id, user_id=user2.id, role_in_room="owner")
        db.add_all([org, user1, user2, ws1, ws2, chat1, chat2, m1, m2])
        db.commit()
    finally:
        db.close()


def make_app() -> FastAPI:
    get_settings(refresh=True)
    app = FastAPI(title="VS Code Extension API Verify")
    app.include_router(api_v1_router)
    return app


def auth_header(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_jwt(user_id: str) -> str:
    return jwt.encode({"sub": user_id}, SECRET_KEY, algorithm="HS256")


def create_pat(client: TestClient, jwt_header: Dict[str, str], name: str, expires_at: Optional[datetime] = None):
    payload = {"name": name, "scopes": ["read", "write"]}
    if expires_at:
        payload["expires_at"] = expires_at.isoformat()
    resp = client.post("/api/v1/auth/pat", json=payload, headers=jwt_header)
    return resp


def post_message(client: TestClient, token: str, chat_id: str, content: str, metadata: Optional[Dict] = None):
    meta = metadata or {}
    resp = client.post(
        f"/api/v1/chats/{chat_id}/messages",
        json={"content": content, "metadata": meta},
        headers=auth_header(token),
    )
    return resp


def post_task(
    client: TestClient,
    token: str,
    workspace_id: str,
    title: Optional[str] = None,
    status: Optional[str] = None,
):
    payload = {"title": title or f"Task-{uuid.uuid4().hex[:6]}", "status": status or "new"}
    resp = client.post(
        f"/api/v1/workspaces/{workspace_id}/tasks",
        json=payload,
        headers=auth_header(token),
    )
    return resp


def patch_task(client: TestClient, token: str, task_id: str, **fields):
    resp = client.patch(f"/api/v1/tasks/{task_id}", json=fields, headers=auth_header(token))
    return resp


def delete_task(client: TestClient, token: str, task_id: str):
    return client.delete(f"/api/v1/tasks/{task_id}", headers=auth_header(token))


def list_tasks(client: TestClient, token: str, workspace_id: str, **params):
    return client.get(
        f"/api/v1/workspaces/{workspace_id}/tasks",
        params=params,
        headers=auth_header(token),
    )


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


def format_result(idx: int, result: CheckResult) -> str:
    status = "PASS" if result.passed else "FAIL"
    suffix = f" - {result.detail}" if result.detail else ""
    return f"{idx}. {status} {result.name}{suffix}"


def debug_log(message: str) -> None:
    if os.getenv("VERIFY_VSCODE_DEBUG"):
        print(message)


# --- individual checks ------------------------------------------------------

def check_route_registration(client: TestClient, main_app, token: str, jwt_header: Dict[str, str], state: Dict) -> CheckResult:
    expected_paths = {
        "/api/v1/me",
        "/api/v1/auth/pat",
        "/api/v1/auth/pat/{pat_id}",
        "/api/v1/workspaces",
        "/api/v1/workspaces/{workspace_id}/chats",
        "/api/v1/chats/{chat_id}/messages",
        "/api/v1/workspaces/{workspace_id}/tasks",
        "/api/v1/tasks/{task_id}",
        "/api/v1/workspaces/{workspace_id}/context-bundle",
        "/api/v1/workspaces/{workspace_id}/rag/search",
        "/api/v1/events",
    }
    main_paths = {route.path for route in main_app.routes}
    missing_paths = sorted(p for p in expected_paths if p not in main_paths)
    if missing_paths:
        return CheckResult("OpenAPI routing", False, f"Missing routes in main.py: {', '.join(missing_paths)}")

    resp_me = client.get("/api/v1/me", headers=auth_header(token))
    if resp_me.status_code != 200:
        return CheckResult("OpenAPI routing", False, f"/me returned {resp_me.status_code}")
    ws_ids = {w["id"] for w in resp_me.json().get("workspaces", [])}
    if "ws1" not in ws_ids:
        return CheckResult("OpenAPI routing", False, "/me missing workspace membership")

    resp_workspaces = client.get("/api/v1/workspaces", headers=auth_header(token))
    if resp_workspaces.status_code != 200:
        return CheckResult("OpenAPI routing", False, f"/workspaces returned {resp_workspaces.status_code}")

    resp_chats = client.get(
        "/api/v1/workspaces/ws1/chats",
        params={"updated_after": None, "limit": 5},
        headers=auth_header(token),
    )
    if resp_chats.status_code != 200:
        return CheckResult("OpenAPI routing", False, f"/workspaces/{{workspace_id}}/chats returned {resp_chats.status_code}")

    resp_messages = client.get(f"/api/v1/chats/chat1/messages", headers=auth_header(token))
    if resp_messages.status_code != 200:
        return CheckResult("OpenAPI routing", False, f"/chats/{{chat_id}}/messages returned {resp_messages.status_code}")

    msg_resp = post_message(
        client,
        token,
        "chat1",
        "route check message",
        metadata={"source": "verify-script", "file_path": "sample.py"},
    )
    if msg_resp.status_code != 201 or not msg_resp.json().get("metadata"):
        return CheckResult("OpenAPI routing", False, "Message creation failed or metadata not echoed")
    state["route_message_id"] = msg_resp.json()["id"]

    list_resp = list_tasks(client, token, "ws1", limit=5)
    if list_resp.status_code != 200:
        return CheckResult("OpenAPI routing", False, f"/workspaces/{{workspace_id}}/tasks returned {list_resp.status_code}")

    create_resp = post_task(client, token, "ws1", title="Route check task")
    if create_resp.status_code != 201:
        return CheckResult("OpenAPI routing", False, f"Task creation failed with {create_resp.status_code}")
    task_id = create_resp.json()["id"]
    state["route_task_id"] = task_id

    patch_resp = patch_task(client, token, task_id, status="in_progress")
    if patch_resp.status_code != 200:
        return CheckResult("OpenAPI routing", False, f"Task patch failed with {patch_resp.status_code}")

    delete_resp = delete_task(client, token, task_id)
    if delete_resp.status_code != 204:
        return CheckResult("OpenAPI routing", False, f"Task delete failed with {delete_resp.status_code}")

    ctx_resp = client.get(
        "/api/v1/workspaces/ws1/context-bundle",
        headers=auth_header(token),
    )
    if ctx_resp.status_code != 200:
        return CheckResult("OpenAPI routing", False, f"Context bundle failed with {ctx_resp.status_code}")

    rag_resp = client.post(
        "/api/v1/workspaces/ws1/rag/search",
        json={"query": "hello", "top_k": 5},
        headers=auth_header(token),
    )
    if rag_resp.status_code != 200:
        return CheckResult("OpenAPI routing", False, f"RAG search failed with {rag_resp.status_code}")

    # Ensure PAT creation path is wired via JWT as well
    pat_resp = create_pat(client, jwt_header, "routing-check")
    if pat_resp.status_code != 201:
        return CheckResult("OpenAPI routing", False, f"PAT creation failed with {pat_resp.status_code}")

    return CheckResult("OpenAPI routing", True, "All required /api/v1 routes reachable and registered in main.py")


def check_pat_security(client: TestClient, SessionLocal, primary_pat: str, jwt_header: Dict[str, str], state: Dict) -> CheckResult:
    create_resp = create_pat(client, jwt_header, "security-main")
    if create_resp.status_code != 201:
        return CheckResult("PAT security", False, f"PAT creation failed with {create_resp.status_code}")
    token = create_resp.json()["token"]
    pat_id = create_resp.json()["pat"]["id"]
    state["pat_under_test"] = pat_id

    list_resp = client.get("/api/v1/auth/pat", headers=auth_header(token))
    if list_resp.status_code != 200:
        return CheckResult("PAT security", False, f"PAT listing failed with {list_resp.status_code}")
    if any("token" in item for item in list_resp.json()):
        return CheckResult("PAT security", False, "PAT listing exposed raw token")

    secret = token.split(".", 1)[1]
    db = SessionLocal()
    try:
        pat_row = db.query(PersonalAccessToken).filter(PersonalAccessToken.id == pat_id).first()
        if not pat_row:
            return CheckResult("PAT security", False, "PAT row missing after creation")
        expected_hash = deps.hash_pat_secret(secret)
        if pat_row.token_hash != expected_hash:
            return CheckResult("PAT security", False, "Stored token hash mismatch")
        if secret in pat_row.token_hash:
            return CheckResult("PAT security", False, "Secret stored in plaintext")
    finally:
        db.close()

    # Expired token should be rejected
    expired_resp = create_pat(
        client,
        jwt_header,
        "expired",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    if expired_resp.status_code != 201:
        return CheckResult("PAT security", False, "Could not create expired PAT for validation")
    expired_token = expired_resp.json()["token"]
    expired_check = client.get("/api/v1/workspaces", headers=auth_header(expired_token))
    if expired_check.status_code != 401:
        return CheckResult("PAT security", False, f"Expired PAT not rejected (got {expired_check.status_code})")

    # Revocation should invalidate token
    revoke_target = create_pat(client, jwt_header, "revocable")
    if revoke_target.status_code != 201:
        return CheckResult("PAT security", False, "Could not create revocation PAT")
    revoke_token = revoke_target.json()["token"]
    revoke_id = revoke_target.json()["pat"]["id"]
    revoke_resp = client.delete(f"/api/v1/auth/pat/{revoke_id}", headers=auth_header(revoke_token))
    if revoke_resp.status_code != 204:
        return CheckResult("PAT security", False, f"PAT revoke failed with {revoke_resp.status_code}")
    post_revoke = client.get("/api/v1/workspaces", headers=auth_header(revoke_token))
    if post_revoke.status_code != 401:
        return CheckResult("PAT security", False, f"Revoked PAT still authorized (got {post_revoke.status_code})")

    # Listing with primary PAT should never reveal tokens
    list_with_primary = client.get("/api/v1/auth/pat", headers=auth_header(primary_pat))
    if list_with_primary.status_code != 200:
        return CheckResult("PAT security", False, f"PAT listing via primary token failed ({list_with_primary.status_code})")
    leaking = [item for item in list_with_primary.json() if "token" in item or "token_hash" in item]
    if leaking:
        return CheckResult("PAT security", False, "PAT listing leaked token data")

    return CheckResult("PAT security", True, "Tokens only returned on creation, hashed at rest, and revoked/expired tokens fail auth")


def check_auth_semantics(client: TestClient, state: Dict, pat_user1: str, pat_user2: str, task_id: str) -> CheckResult:
    # 401 for unauthenticated
    unauth = client.get("/api/v1/workspaces")
    if unauth.status_code != 401:
        return CheckResult("Auth semantics", False, f"Unauthenticated access returned {unauth.status_code}")

    # Member can access own workspace
    ws_ok = client.get("/api/v1/workspaces/ws1/tasks", headers=auth_header(pat_user1))
    if ws_ok.status_code != 200:
        return CheckResult("Auth semantics", False, f"Member access failed with {ws_ok.status_code}")

    # Non-member blocked on workspace-scoped endpoints
    ws_forbidden = client.get("/api/v1/workspaces/ws1/tasks", headers=auth_header(pat_user2))
    if ws_forbidden.status_code != 403:
        return CheckResult("Auth semantics", False, f"Non-member workspace access returned {ws_forbidden.status_code}")

    # ID-only endpoints still enforce membership
    chat_forbidden = client.get("/api/v1/chats/chat1/messages", headers=auth_header(pat_user2))
    if chat_forbidden.status_code != 403:
        return CheckResult("Auth semantics", False, f"Non-member chat access returned {chat_forbidden.status_code}")

    task_forbidden = patch_task(client, pat_user2, task_id, title="not allowed")
    if task_forbidden.status_code != 403:
        return CheckResult("Auth semantics", False, f"Non-member task patch returned {task_forbidden.status_code}")

    # Member cannot cross into other workspace
    other_ws = client.get("/api/v1/workspaces/ws2/tasks", headers=auth_header(pat_user1))
    if other_ws.status_code != 403:
        return CheckResult("Auth semantics", False, f"Cross-workspace access returned {other_ws.status_code}")

    return CheckResult("Auth semantics", True, "401/403 semantics enforced and ID-only endpoints are workspace-scoped")


def check_delta_sync(client: TestClient, SessionLocal, token: str, state: Dict) -> CheckResult:
    cutoff = datetime.now(timezone.utc).isoformat()
    time.sleep(0.02)
    after_cutoff_resp = post_task(client, token, "ws1", title="Delta new task")
    if after_cutoff_resp.status_code != 201:
        return CheckResult("Delta sync", False, f"Task creation for delta failed ({after_cutoff_resp.status_code})")
    after_id = after_cutoff_resp.json()["id"]

    list_after = list_tasks(client, token, "ws1", updated_after=cutoff, limit=10)
    if list_after.status_code != 200:
        return CheckResult("Delta sync", False, f"updated_after filter failed ({list_after.status_code})")
    ids_after = {item["id"] for item in list_after.json()["items"]}
    if after_id not in ids_after:
        return CheckResult("Delta sync", False, "updated_after filter did not include new task")

    # Soft delete surfaces deleted_at
    delete_resp = delete_task(client, token, after_id)
    if delete_resp.status_code != 204:
        return CheckResult("Delta sync", False, f"Soft delete failed ({delete_resp.status_code})")
    deleted_list = list_tasks(client, token, "ws1", limit=10)
    deleted_items = {i["id"]: i for i in deleted_list.json()["items"]}
    if after_id not in deleted_items or deleted_items[after_id]["deleted_at"] is None:
        return CheckResult("Delta sync", False, "Deleted task missing deleted_at in listings")

    # Cursor pagination stability
    pagination_cutoff = datetime.now(timezone.utc).isoformat()
    time.sleep(0.02)
    paginated_ids = []
    for _ in range(3):
        resp = post_task(client, token, "ws1", title=f"Page task {uuid.uuid4().hex[:4]}")
        if resp.status_code != 201:
            return CheckResult("Delta sync", False, f"Task creation for pagination failed ({resp.status_code})")
        paginated_ids.append(resp.json()["id"])

    page1 = list_tasks(client, token, "ws1", updated_after=pagination_cutoff, limit=2)
    if page1.status_code != 200:
        return CheckResult("Delta sync", False, f"First page failed ({page1.status_code})")
    items1 = page1.json()["items"]
    cursor = page1.json().get("next_cursor")
    seen_ids = [i["id"] for i in items1]
    if cursor:
        page2 = list_tasks(client, token, "ws1", updated_after=pagination_cutoff, cursor=cursor, limit=2)
        if page2.status_code != 200:
            return CheckResult("Delta sync", False, f"Second page failed ({page2.status_code})")
        seen_ids.extend([i["id"] for i in page2.json()["items"]])

    if len(seen_ids) != len(set(seen_ids)):
        return CheckResult("Delta sync", False, "Cursor pagination returned duplicate tasks")
    missing = set(paginated_ids) - set(seen_ids)
    if missing:
        return CheckResult("Delta sync", False, f"Cursor pagination dropped tasks: {', '.join(missing)}")

    # Chat updated_after correctness
    chat_cutoff = datetime.now(timezone.utc).isoformat()
    time.sleep(0.02)
    chat_msg = post_message(client, token, "chat1", "chat delta message")
    if chat_msg.status_code != 201:
        return CheckResult("Delta sync", False, f"Chat message creation failed ({chat_msg.status_code})")
    chat_list = client.get(
        "/api/v1/workspaces/ws1/chats",
        params={"updated_after": chat_cutoff, "limit": 10},
        headers=auth_header(token),
    )
    if chat_list.status_code != 200 or "chat1" not in {c["id"] for c in chat_list.json()["items"]}:
        return CheckResult("Delta sync", False, "updated_after filter on chats did not include chat1")

    return CheckResult("Delta sync", True, "updated_after filters, soft-delete flags, and cursor pagination are stable")


def check_context_bundle(client: TestClient, SessionLocal, token: str) -> CheckResult:
    # Create messages with distinct recency
    old_msg = post_message(client, token, "chat1", "old context message")
    if old_msg.status_code != 201:
        return CheckResult("Context bundle", False, "Failed to create old context message")
    old_id = old_msg.json()["id"]
    db = SessionLocal()
    try:
        row = db.query(Message).filter(Message.id == old_id).first()
        if row:
            row.created_at = datetime.now(timezone.utc) - timedelta(hours=30)
            row.updated_at = row.created_at
            db.add(row)
            db.commit()
    finally:
        db.close()

    recent_msg = post_message(client, token, "chat1", "recent context message")
    if recent_msg.status_code != 201:
        return CheckResult("Context bundle", False, "Failed to create recent context message")

    open_task = post_task(client, token, "ws1", title="Context open task")
    if open_task.status_code != 201:
        return CheckResult("Context bundle", False, "Failed to create open task")
    done_task = post_task(client, token, "ws1", title="Context done task", status="done")
    if done_task.status_code != 201:
        return CheckResult("Context bundle", False, "Failed to create done task")

    resp = client.get(
        "/api/v1/workspaces/ws1/context-bundle",
        params={"max_chats": 1, "max_messages": 2, "max_tasks": 3, "recent_hours": 24},
        headers=auth_header(token),
    )
    if resp.status_code != 200:
        return CheckResult("Context bundle", False, f"Context bundle request failed ({resp.status_code})")
    body = resp.json()

    if len(body.get("recent_chats", [])) > 1:
        return CheckResult("Context bundle", False, "max_chats limit not enforced")
    msg_ids = {m["message_id"] for m in body.get("recent_messages", [])}
    if old_id in msg_ids:
        return CheckResult("Context bundle", False, "recent_hours filter did not drop stale messages")
    task_titles = {t["title"] for t in body.get("open_tasks", [])}
    if "Context done task" in task_titles:
        return CheckResult("Context bundle", False, "Closed tasks leaked into open_tasks")

    return CheckResult("Context bundle", True, "Bundle respects limits, recency, and only shows open tasks/messages")


def check_rag(client: TestClient, SessionLocal, token_user1: str, token_user2: str) -> CheckResult:
    ws1_msg = post_message(client, token_user1, "chat1", "workspace one rag text")
    if ws1_msg.status_code != 201:
        return CheckResult("RAG search", False, "Failed to create ws1 message for RAG")

    ws2_resp = post_message(client, token_user2, "chat2", "workspace two secret rag text")
    if ws2_resp.status_code != 201:
        return CheckResult("RAG search", False, "Failed to create ws2 message for RAG")

    rag_resp = client.post(
        "/api/v1/workspaces/ws1/rag/search",
        json={"query": "workspace", "top_k": 5},
        headers=auth_header(token_user1),
    )
    if rag_resp.status_code != 200:
        return CheckResult("RAG search", False, f"RAG search failed ({rag_resp.status_code})")
    results = rag_resp.json()
    if not results:
        return CheckResult("RAG search", False, "RAG returned no results for workspace messages")
    first = results[0]
    required_keys = {"source_id", "source_type", "text", "score", "metadata"}
    if not required_keys.issubset(first.keys()):
        return CheckResult("RAG search", False, "RAG result missing expected keys")

    if any("workspace two" in r["text"] for r in results):
        return CheckResult("RAG search", False, "Cross-workspace results leaked into RAG response")

    forbidden = client.post(
        "/api/v1/workspaces/ws1/rag/search",
        json={"query": "workspace"},
        headers=auth_header(token_user2),
    )
    if forbidden.status_code != 403:
        return CheckResult("RAG search", False, f"Non-member RAG access returned {forbidden.status_code}")

    return CheckResult("RAG search", True, "Endpoint wired with expected chunk schema and workspace scoping")


def _collect_sse_events_from_response(
    streaming_response,
    max_events: int = 5,
    timeout_s: float = 5.0,
) -> List[Dict]:
    events: List[Dict] = []

    async def _consume():
        iterator = streaming_response.body_iterator
        start = time.monotonic()
        while len(events) < max_events:
            remaining = timeout_s - (time.monotonic() - start)
            if remaining <= 0:
                return
            try:
                chunk = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
            except (StopAsyncIteration, asyncio.TimeoutError):
                return
            text = chunk.decode() if isinstance(chunk, (bytes, bytearray)) else str(chunk)
            for line in text.splitlines():
                if line.startswith("data: "):
                    payload = json.loads(line[len("data: ") :])
                    events.append(payload)
                    if len(events) >= max_events:
                        return

    asyncio.run(_consume())
    return events


def check_sse_events(client: TestClient, token: str) -> CheckResult:
    from app.api.v1.events import stream_events
    from models import User, WorkspaceEvent

    baseline_id = 0
    with events_module.SessionLocal() as db:
        row = db.query(WorkspaceEvent.id).order_by(WorkspaceEvent.id.desc()).first()
        if row:
            baseline_id = row[0]

    # Prime events
    msg_resp = post_message(client, token, "chat1", "sse message")
    if msg_resp.status_code != 201:
        return CheckResult("SSE events", False, "Failed to create message for SSE")
    task_resp = post_task(client, token, "ws1", title="SSE task")
    if task_resp.status_code != 201:
        return CheckResult("SSE events", False, "Failed to create task for SSE")
    task_id = task_resp.json()["id"]
    upd_resp = patch_task(client, token, task_id, status="in_progress")
    if upd_resp.status_code != 200:
        return CheckResult("SSE events", False, "Failed to update task for SSE")
    del_resp = delete_task(client, token, task_id)
    if del_resp.status_code != 204:
        return CheckResult("SSE events", False, "Failed to delete task for SSE")

    user = None
    with events_module.SessionLocal() as db:
        user = db.query(User).filter(User.id == "u1").first()
    if not user:
        return CheckResult("SSE events", False, "Test user missing for SSE validation")

    response = asyncio.run(stream_events(workspace_id="ws1", since_event_id=baseline_id, current_user=user))
    if "text/event-stream" not in (response.media_type or ""):
        return CheckResult("SSE events", False, "SSE content-type missing")
    events = _collect_sse_events_from_response(response, max_events=4, timeout_s=8.0)

    if not events:
        return CheckResult("SSE events", False, "No events received from SSE stream")

    required_types = {"chat.message.created", "task.created", "task.updated", "task.deleted"}
    got_types = {e["type"] for e in events}
    if not required_types.issubset(got_types):
        return CheckResult("SSE events", False, f"Missing event types: {', '.join(required_types - got_types)}")
    sample = events[-1]
    expected_keys = {"event_id", "type", "workspace_id", "resource_id", "timestamp", "payload"}
    if not expected_keys.issubset(sample.keys()):
        return CheckResult("SSE events", False, "Event payload missing required fields")

    last_id = max(e["event_id"] for e in events)
    new_msg = post_message(client, token, "chat1", "sse resume message")
    if new_msg.status_code != 201:
        return CheckResult("SSE events", False, "Failed to create resume message for SSE")
    resume_response = asyncio.run(
        stream_events(workspace_id="ws1", since_event_id=last_id, current_user=user)
    )
    resume_events = _collect_sse_events_from_response(resume_response, max_events=2)
    if not resume_events or not all(e["event_id"] > last_id for e in resume_events):
        return CheckResult("SSE events", False, "since_event_id did not resume correctly")

    return CheckResult("SSE events", True, "SSE stream emits expected events with resumable cursor")


def main():
    SessionLocal = configure_db()
    seed_data(SessionLocal)
    app = make_app()
    client = TestClient(app, raise_server_exceptions=False)

    user1_jwt = make_jwt("u1")
    user2_jwt = make_jwt("u2")
    pat_resp = create_pat(client, auth_header(user1_jwt), "primary")
    if pat_resp.status_code != 201:
        print("Failed to create primary PAT; cannot continue")
        sys.exit(1)
    primary_pat = pat_resp.json()["token"]
    pat_user2_resp = create_pat(client, auth_header(user2_jwt), "user2")
    if pat_user2_resp.status_code != 201:
        print("Failed to create PAT for user2; cannot continue")
        sys.exit(1)
    user2_pat = pat_user2_resp.json()["token"]

    state: Dict[str, str] = {}
    results: List[CheckResult] = []

    debug_log("Running routing check")
    results.append(check_route_registration(client, main_app_module.app, primary_pat, auth_header(user1_jwt), state))
    debug_log("Running PAT security check")
    results.append(check_pat_security(client, SessionLocal, primary_pat, auth_header(user1_jwt), state))
    debug_log("Running auth semantics check")
    results.append(check_auth_semantics(client, state, primary_pat, user2_pat, state.get("route_task_id", "")))
    debug_log("Running delta sync check")
    results.append(check_delta_sync(client, SessionLocal, primary_pat, state))
    debug_log("Running context bundle check")
    results.append(check_context_bundle(client, SessionLocal, primary_pat))
    debug_log("Running RAG check")
    results.append(check_rag(client, SessionLocal, primary_pat, user2_pat))
    debug_log("Running SSE events check")
    results.append(check_sse_events(client, primary_pat))

    failed = [r for r in results if not r.passed]
    for idx, res in enumerate(results, start=1):
        print(format_result(idx, res))

    if failed:
        print(
            "\nExtension readiness verdict: FAIL — "
            f"{len(failed)} check(s) failed. Inspect the above items for details."
        )
        sys.exit(1)
    else:
        print(
            "\nExtension readiness verdict: PASS — all checks succeeded for the VS Code extension API surface."
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
