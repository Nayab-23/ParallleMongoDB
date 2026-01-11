"""
Minimal API surface for Web ↔ Extension demo loop
Uses MongoDB Atlas, Fireworks AI, Voyage embeddings only
No SQLAlchemy, no Postgres, no OpenAI

Endpoints:
  1. POST /api/chats - Create chat
  2. GET /api/chats - List chats
  3. GET /api/chats/{id}/messages - Get messages
  4. POST /api/chats/{id}/dispatch - Send task to extension
  5. GET /api/v1/extension/tasks/{id} - Task status
  6. GET /api/v1/workspaces/{id}/sync - Sync poll
  7. GET /api/v1/events - SSE stream
  8. POST /api/v1/workspaces/{id}/vscode/agent/edits/record - Record edit
  9. POST /api/v1/vscode/chat - Extension chat
  10. GET /api/me - Get current user
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pymongo import DESCENDING
from pymongo.collection import Collection

# Import from hack_main.py
from hack_main import _get_demo_db, _fireworks_client, CONFIG, get_demo_user
from logutil import log_event, log_error

# ============================================
# CONSTANTS
# ============================================

DEMO_WORKSPACE_ID = "1"
DEMO_USER_ID = "demo-user-1"
DEMO_USER_NAME = "Demo User"
DEMO_WORKSPACE_NAME = "Demo Workspace"

# ============================================
# DEMO USER MAP
# ============================================
DEMO_USER_MAP = {
    "alice": {"user_id": "demo-alice", "name": "Alice", "workspace_id": "1"},
    "bob": {"user_id": "demo-bob", "name": "Bob", "workspace_id": "1"},
}

# ============================================
# PYDANTIC MODELS
# ============================================

class CreateChatRequest(BaseModel):
    name: str


class ChatOut(BaseModel):
    id: str
    chat_id: str
    name: str
    workspace_id: str = DEMO_WORKSPACE_ID
    created_at: str
    updated_at: str
    last_message_at: Optional[str] = None


class MessageOut(BaseModel):
    id: str
    message_id: str
    chat_id: str
    role: str  # "user" | "assistant" | "system"
    content: str
    sender_id: Optional[str] = None
    sender_name: Optional[str] = None
    created_at: str
    metadata: Optional[Dict[str, Any]] = None


class DispatchRequest(BaseModel):
    mode: str = "vscode"
    content: str
    repo_id: Optional[str] = None
    task_type: Optional[str] = None
    patch: Optional[Dict[str, Any]] = None
    to_user_id: Optional[str] = None  # optional override for task recipient


class DispatchResponse(BaseModel):
    task_id: str
    status: str
    message: Optional[str] = None


class TaskStatusOut(BaseModel):
    task_id: str
    status: str  # "pending", "running", "done", "error"
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


class SyncItem(BaseModel):
    entity_type: str  # "task" | "message"
    id: str
    payload: Any
    created_at: str
    updated_at: str
    deleted: bool = False


class SyncResponse(BaseModel):
    items: List[SyncItem]
    next_cursor: Optional[str] = None
    done: bool = True


class RecordEditRequest(BaseModel):
    edit_id: str
    description: str
    source: str = "vscode-extension"
    files_modified: List[str]
    original_content: Optional[Dict[str, str]] = None
    new_content: Optional[Dict[str, str]] = None


class VSCodeChatRequest(BaseModel):
    workspace_id: str = DEMO_WORKSPACE_ID
    chat_id: str
    message: str
    repo: Optional[Dict[str, Any]] = None


class VSCodeChatResponse(BaseModel):
    request_id: str
    workspace_id: str
    chat_id: str
    user_message_id: str
    assistant_message_id: str
    reply: str
    model: str
    created_at: str
    duration_ms: int


class UserOut(BaseModel):
    id: str
    name: str
    email: str = "demo@parallel.ai"
    workspace_id: str = DEMO_WORKSPACE_ID


class WorkspaceOut(BaseModel):
    id: str
    name: Optional[str] = None


class BootstrapResponse(BaseModel):
    user: UserOut
    workspaces: List[WorkspaceOut]


class ContextTask(BaseModel):
    id: str
    title: Optional[str] = None
    status: Optional[str] = None


class ContextConversation(BaseModel):
    id: str
    title: Optional[str] = None
    summary: Optional[str] = None
    lastMessages: Optional[List[Dict[str, str]]] = None


class ContextResponse(BaseModel):
    tasks: List[ContextTask]
    conversations: List[ContextConversation]


# ============================================
# ROUTER
# ============================================

router = APIRouter()


# ============================================
# HELPERS
# ============================================

def _get_collection(name: str) -> Collection:
    """Get MongoDB collection"""
    db = _get_demo_db()
    return db[name]


def _now_iso() -> str:
    """Current timestamp in ISO format"""
    return datetime.now(timezone.utc).isoformat()


def _generate_id() -> str:
    """Generate UUID"""
    return str(uuid.uuid4())


def _emit_event(entity_type: str, entity_id: str, payload: Any):
    """Emit event for SSE subscribers"""
    events_col = _get_collection("events")
    event_doc = {
        "event_id": _generate_id(),
        "workspace_id": DEMO_WORKSPACE_ID,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload": payload,
        "created_at": datetime.now(timezone.utc),
    }
    events_col.insert_one(event_doc)


def _create_chat_doc(workspace_id: str, name: str) -> Dict[str, Any]:
    chats_col = _get_collection("chats")
    now = _now_iso()
    chat_id = _generate_id()
    doc = {
        "chat_id": chat_id,
        "name": name,
        "workspace_id": workspace_id,
        "created_at": now,
        "updated_at": now,
        "last_message_at": None,
    }
    chats_col.insert_one(doc)
    return doc


def _list_chats_for_workspace(
    workspace_id: str,
    limit: int,
    cursor: Optional[str],
) -> tuple[List[Dict[str, Any]], Optional[str]]:
    chats_col = _get_collection("chats")
    query = {"workspace_id": workspace_id}
    if cursor:
        query["updated_at"] = {"$lt": cursor}

    docs = list(
        chats_col.find(query)
        .sort("updated_at", DESCENDING)
        .limit(limit + 1)
    )

    has_more = len(docs) > limit
    if has_more:
        docs = docs[:limit]

    items = [
        {
            "id": doc["chat_id"],
            "chat_id": doc["chat_id"],
            "name": doc["name"],
            "last_message_at": doc.get("last_message_at"),
            "updated_at": doc["updated_at"],
        }
        for doc in docs
    ]

    next_cursor = docs[-1]["updated_at"] if has_more and docs else None
    return items, next_cursor


# ============================================
# ENDPOINTS
# ============================================

# 0. GET /api/v1/bootstrap - Demo bootstrap info
@router.get("/api/v1/bootstrap", response_model=BootstrapResponse)
async def bootstrap(request: Request):
    demo = get_demo_user(request)
    return BootstrapResponse(
        user=UserOut(
            id=demo["user_id"],
            name=demo["name"],
            email=f"{demo['key']}@demo.local",
            workspace_id=demo["workspace_id"],
        ),
        workspaces=[
            WorkspaceOut(
                id=demo["workspace_id"],
                name=DEMO_WORKSPACE_NAME,
            )
        ],
    )

# 1. POST /api/chats - Create chat
@router.post("/api/chats", response_model=ChatOut)
async def create_chat(req: CreateChatRequest, request: Request):
    """Create a new chat session"""
    demo = get_demo_user(request)
    doc = _create_chat_doc(demo["workspace_id"], req.name)

    return ChatOut(
        id=doc["chat_id"],
        chat_id=doc["chat_id"],
        name=doc["name"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


# 2. GET /api/chats - List chats
@router.get("/api/chats", response_model=Dict[str, Any])
async def list_chats(
    request: Request,
    limit: int = Query(50, ge=1, le=100),
    cursor: Optional[str] = None,
):
    """List all chats for demo workspace"""
    demo = get_demo_user(request)
    items, next_cursor = _list_chats_for_workspace(demo["workspace_id"], limit, cursor)

    return {
        "items": items,
        "next_cursor": next_cursor,
    }


# 3. GET /api/chats/{chat_id}/messages - Get messages
@router.get("/api/chats/{chat_id}/messages", response_model=List[MessageOut])
async def get_chat_messages(
    chat_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
):
    """Get messages for a chat"""
    demo = get_demo_user(request)
    messages_col = _get_collection("messages")

    # Ensure chat belongs to workspace (best-effort)
    docs = list(
        messages_col.find({"chat_id": chat_id, "workspace_id": demo["workspace_id"]})
        .sort("created_at", DESCENDING)
        .limit(limit)
    )

    # Reverse to get chronological order
    docs.reverse()

    return [
        MessageOut(
            id=doc["message_id"],
            message_id=doc["message_id"],
            chat_id=doc["chat_id"],
            role=doc["role"],
            content=doc["content"],
            sender_id=doc.get("sender_id"),
            sender_name=doc.get("sender_name"),
            created_at=doc["created_at"],
            metadata=doc.get("metadata"),
        )
        for doc in docs
    ]


# 3b. GET /api/v1/chats/{chat_id}/messages - Extension chat history
@router.get("/api/v1/chats/{chat_id}/messages", response_model=List[MessageOut])
async def get_chat_messages_v1(
    chat_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
):
    return await get_chat_messages(chat_id=chat_id, request=request, limit=limit)


# 3c. GET /api/v1/workspaces/{workspace_id}/chats - List chats
@router.get("/api/v1/workspaces/{workspace_id}/chats", response_model=Dict[str, Any])
async def list_chats_v1(
    workspace_id: str,
    limit: int = Query(50, ge=1, le=100),
    cursor: Optional[str] = None,
):
    items, next_cursor = _list_chats_for_workspace(workspace_id, limit, cursor)
    return {"items": items, "next_cursor": next_cursor}


# 3d. POST /api/v1/workspaces/{workspace_id}/chats - Create chat
@router.post("/api/v1/workspaces/{workspace_id}/chats", response_model=ChatOut)
async def create_chat_v1(
    workspace_id: str,
    req: CreateChatRequest,
    request: Request,
):
    demo = get_demo_user(request)
    # ignore provided workspace_id and use demo workspace for demo mode
    doc = _create_chat_doc(demo["workspace_id"], req.name)
    return ChatOut(
        id=doc["chat_id"],
        chat_id=doc["chat_id"],
        name=doc["name"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


# 4. POST /api/chats/{chat_id}/dispatch - Send task to extension
@router.post("/api/chats/{chat_id}/dispatch", response_model=DispatchResponse)
async def dispatch_chat(chat_id: str, req: DispatchRequest, request: Request):
    """Dispatch message as task to VS Code extension"""

    demo = get_demo_user(request)
    current_user_id = demo["user_id"]
    current_user_name = demo["name"]
    workspace_id = demo["workspace_id"]

    # Save user message
    messages_col = _get_collection("messages")
    user_msg_id = _generate_id()
    now = _now_iso()

    messages_col.insert_one({
        "message_id": user_msg_id,
        "chat_id": chat_id,
        "role": "user",
        "content": req.content,
        "sender_id": current_user_id,
        "sender_name": current_user_name,
        "workspace_id": workspace_id,
        "created_at": now,
        "metadata": {"mode": req.mode, "repo_id": req.repo_id},
    })

    # Create task
    tasks_col = _get_collection("tasks")
    task_id = _generate_id()

    # Determine recipient: explicit override else same user (for demo MVP)
    to_user = req.to_user_id if req.to_user_id else current_user_id

    task_doc = {
        "task_id": task_id,
        "workspace_id": workspace_id,
        "chat_id": chat_id,
        "repo_id": req.repo_id,
        "task_type": req.task_type or "EXECUTE",
        "status": "pending",
        "from_user_id": current_user_id,
        "to_user_id": to_user,
        "payload": {
            "content": req.content,
            "mode": req.mode,
            "patch": req.patch,
        },
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }

    tasks_col.insert_one(task_doc)

    # Emit event for SSE subscribers (include from/to so subscribers can filter)
    _emit_event("task", task_id, task_doc)

    # Update chat timestamp
    chats_col = _get_collection("chats")
    chats_col.update_one(
        {"chat_id": chat_id},
        {"$set": {"updated_at": now, "last_message_at": now}}
    )

    return DispatchResponse(
        task_id=task_id,
        status="pending",
        message=f"Task {task_id} created and sent to extension",
    )


# 5. GET /api/v1/extension/tasks/{task_id} - Task status
@router.get("/api/v1/extension/tasks/{task_id}", response_model=TaskStatusOut)
async def get_task_status(task_id: str, request: Request):
    """Get task status (visible only to involved demo users)"""
    demo = get_demo_user(request)
    tasks_col = _get_collection("tasks")

    doc = tasks_col.find_one({"task_id": task_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Task not found")

    # Only allow involved users to see task
    current_user = demo["user_id"]
    if current_user not in (doc.get("from_user_id"), doc.get("to_user_id")):
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskStatusOut(
        task_id=doc["task_id"],
        status=doc["status"],
        result=doc.get("result"),
        error=doc.get("error"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


# 5a. GET /api/v1/extension/tasks - Bulk task list (for extension polling)
@router.get("/api/v1/extension/tasks", response_model=List[TaskStatusOut])
async def list_extension_tasks(
    request: Request,
    to_user_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
):
    """List tasks for extension polling"""
    demo = get_demo_user(request)
    tasks_col = _get_collection("tasks")

    query = {"to_user_id": to_user_id or demo["user_id"]}
    if status:
        query["status"] = status

    docs = list(
        tasks_col.find(query)
        .sort("created_at", DESCENDING)
        .limit(limit)
    )

    return [
        TaskStatusOut(
            task_id=doc["task_id"],
            status=doc["status"],
            result=doc.get("result"),
            error=doc.get("error"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )
        for doc in docs
    ]


# 5b. GET /api/v1/workspaces/{workspace_id}/vscode/context - Context bundle
@router.get("/api/v1/workspaces/{workspace_id}/vscode/context", response_model=ContextResponse)
async def vscode_context(
    workspace_id: str,
    request: Request,
    tasks_limit: int = Query(20, ge=0, le=500),
    conversations_limit: int = Query(5, ge=0, le=200),
    include_messages: Optional[bool] = False,
):
    demo = get_demo_user(request)
    tasks_col = _get_collection("tasks")
    chats_col = _get_collection("chats")

    # Only show tasks for this workspace
    task_docs = list(
        tasks_col.find({"workspace_id": demo["workspace_id"]})
        .sort("updated_at", DESCENDING)
        .limit(tasks_limit)
    )
    tasks = [
        ContextTask(
            id=doc["task_id"],
            title=(doc.get("payload") or {}).get("content") or doc.get("task_type"),
            status=doc.get("status"),
        )
        for doc in task_docs
    ]

    chat_docs = list(
        chats_col.find({"workspace_id": demo["workspace_id"]})
        .sort("updated_at", DESCENDING)
        .limit(conversations_limit)
    )
    conversations = [
        ContextConversation(
            id=doc["chat_id"],
            title=doc.get("name"),
            summary=None,
            lastMessages=None,
        )
        for doc in chat_docs
    ]

    return ContextResponse(tasks=tasks, conversations=conversations)


# 6. GET /api/v1/workspaces/{workspace_id}/sync - Sync poll
@router.get("/api/v1/workspaces/{workspace_id}/sync", response_model=SyncResponse)
async def sync_workspace(
    workspace_id: str,
    cursor: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    """Sync tasks and messages (polling fallback)"""

    # For demo, just return recent tasks
    tasks_col = _get_collection("tasks")

    query = {"workspace_id": workspace_id}
    if cursor:
        query["created_at"] = {"$gt": cursor}

    docs = list(
        tasks_col.find(query)
        .sort("created_at", DESCENDING)
        .limit(limit)
    )

    items = [
        SyncItem(
            entity_type="task",
            id=doc["task_id"],
            payload=doc,
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            deleted=False,
        )
        for doc in docs
    ]

    return SyncResponse(items=items, done=True)


# 7. GET /api/v1/events - SSE stream
@router.get("/api/v1/events")
async def events_stream(
    request: Request,
    workspace_id: str = Query(DEMO_WORKSPACE_ID),
    since_event_id: Optional[str] = None,
    demo_user: Optional[str] = None,
):
    """Server-Sent Events stream for realtime updates (filtered by demo user)."""

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events"""
        try:
            # Resolve demo user from query param (for browser EventSource) or header
            if demo_user and demo_user.strip().lower() in ("alice", "bob"):
                user_key = demo_user.strip().lower()
                from hack_main import DEMO_USER_MAP
                current_user = DEMO_USER_MAP[user_key]["user_id"]
            else:
                demo = get_demo_user(request)
                current_user = demo["user_id"]
            log_event("SSE_CONNECT", workspace_id=workspace_id, last_event_id=since_event_id, demo_user=current_user)
            events_col = _get_collection("events")
            last_id = since_event_id
            heartbeat_count = 0

            # Send initial heartbeat
            yield "data: heartbeat\n\n"

            while True:
                try:
                    # Poll for new events
                    query = {"workspace_id": workspace_id}
                    if last_id:
                        # Find events after last_id (simplified - use timestamp in production)
                        query["event_id"] = {"$gt": last_id}

                    docs = list(
                        events_col.find(query)
                        .sort("created_at", DESCENDING)
                        .limit(20)
                    )

                    for doc in reversed(docs):
                        event_id = doc["event_id"]
                        last_id = event_id

                        payload = doc.get("payload") or {}
                        # Filtering: allow events relevant to the current demo user
                        allowed = False
                        # payload may include from_user_id, to_user_id, user_id
                        if isinstance(payload, dict):
                            if payload.get("to_user_id") == current_user:
                                allowed = True
                            if payload.get("from_user_id") == current_user:
                                allowed = True
                            if payload.get("user_id") == current_user:
                                allowed = True
                        # Also allow non-user-targeted events (edits, messages) in same workspace
                        if not allowed and doc.get("entity_type") in ("message", "edit"):
                            allowed = True

                        if not allowed:
                            continue

                        # Format SSE event
                        data = {
                            "entity_type": doc["entity_type"],
                            "id": doc["entity_id"],
                            "payload": payload,
                            "created_at": doc["created_at"].isoformat(),
                        }

                        log_event("SSE_EVENT", workspace_id=workspace_id, event_id=event_id, entity_type=doc["entity_type"], demo_user=current_user)
                        yield f"id: {event_id}\n"
                        yield f"data: {json.dumps(data)}\n\n"

                    # Heartbeat every 15s if no events
                    if not docs:
                        heartbeat_count += 1
                        # Only log every 10 heartbeats (~50 seconds)
                        if heartbeat_count % 10 == 0:
                            log_event("SSE_HEARTBEAT", workspace_id=workspace_id, count=heartbeat_count, demo_user=current_user)
                        yield ":heartbeat\n\n"

                    await asyncio.sleep(5)  # Poll every 5s

                except Exception as exc:
                    log_error("SSE_STREAM", exc, workspace_id=workspace_id, last_event_id=last_id)
                    # Close gracefully on error
                    break

        except Exception as exc:
            log_error("SSE_CONNECT", exc, workspace_id=workspace_id)
            raise
        finally:
            log_event("SSE_DISCONNECT", workspace_id=workspace_id, last_event_id=last_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# 8. POST /api/v1/workspaces/{workspace_id}/vscode/agent/edits/record - Record edit
@router.post("/api/v1/workspaces/{workspace_id}/vscode/agent/edits/record")
async def record_edit(workspace_id: str, req: RecordEditRequest, request: Request):
    """Record edit completion from VS Code extension"""
    edits_col = _get_collection("edits")
    tasks_col = _get_collection("tasks")

    demo = get_demo_user(request)
    current_user = demo["user_id"]

    now = _now_iso()

    doc = {
        "edit_id": req.edit_id,
        "workspace_id": workspace_id,
        "description": req.description,
        "source": req.source,
        "files_modified": req.files_modified,
        "original_content": req.original_content,
        "new_content": req.new_content,
        "created_at": now,
    }

    edits_col.insert_one(doc)

    # Find matching task: by task_id == edit_id OR pending task assigned to current user
    task_doc = tasks_col.find_one({"task_id": req.edit_id})
    if not task_doc:
        task_doc = tasks_col.find_one(
            {"workspace_id": workspace_id, "to_user_id": current_user, "status": {"$in": ["pending", "running"]}},
            sort=[("created_at", DESCENDING)],
        )
    if task_doc:
        update_payload = {
            "status": "done",
            "result": {
                "edit_id": req.edit_id,
                "description": req.description,
                "files_modified": req.files_modified,
                "source": req.source,
            },
            "error": None,
            "updated_at": now,
        }
        tasks_col.update_one({"_id": task_doc["_id"]}, {"$set": update_payload})
        task_event = {**task_doc, **update_payload}
        task_event.pop("_id", None)
        _emit_event("task", task_doc["task_id"], task_event)

    # Emit event
    _emit_event("edit", req.edit_id, doc)

    return {"ok": True, "edit_id": req.edit_id}


# 9. POST /api/v1/vscode/chat - Extension chat
@router.post("/api/v1/vscode/chat", response_model=VSCodeChatResponse)
async def vscode_chat(req: VSCodeChatRequest, request: Request):
    """Send chat message from VS Code extension (with Fireworks AI)"""

    start_time = time.time()

    demo = get_demo_user(request)
    current_user_id = demo["user_id"]
    current_user_name = demo["name"]

    # Save user message
    messages_col = _get_collection("messages")
    user_msg_id = _generate_id()
    now = _now_iso()

    messages_col.insert_one({
        "message_id": user_msg_id,
        "chat_id": req.chat_id,
        "role": "user",
        "content": req.message,
        "sender_id": current_user_id,
        "sender_name": current_user_name,
        "workspace_id": req.workspace_id,
        "created_at": now,
        "metadata": {"source": "vscode", "repo": req.repo},
    })

    # Get chat history for context
    history_docs = list(
        messages_col.find({"chat_id": req.chat_id, "workspace_id": req.workspace_id})
        .sort("created_at", DESCENDING)
        .limit(10)
    )
    history_docs.reverse()

    # Build prompt
    messages = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in history_docs
    ]

    # Call Fireworks AI
    try:
        log_event("FIREWORKS_CHAT", model=CONFIG.fireworks_model, purpose="vscode_chat", chat_id=req.chat_id)
        response = _fireworks_client.chat.completions.create(
            model=CONFIG.fireworks_model,
            messages=messages,
            temperature=0.2,
            max_tokens=1000,
        )

        reply = response.choices[0].message.content.strip()
        log_event("FIREWORKS_CHAT_SUCCESS", model=CONFIG.fireworks_model, reply_length=len(reply))
    except Exception as e:
        log_error("FIREWORKS_CHAT", e, model=CONFIG.fireworks_model, purpose="vscode_chat", chat_id=req.chat_id)
        reply = f"Error calling Fireworks AI: {str(e)}"

    # Save assistant message
    assistant_msg_id = _generate_id()
    assistant_now = _now_iso()

    messages_col.insert_one({
        "message_id": assistant_msg_id,
        "chat_id": req.chat_id,
        "role": "assistant",
        "content": reply,
        "sender_id": None,
        "sender_name": "AI Assistant",
        "workspace_id": req.workspace_id,
        "created_at": assistant_now,
        "metadata": {"model": CONFIG.fireworks_model, "source": "vscode"},
    })

    # Update chat timestamp
    chats_col = _get_collection("chats")
    chats_col.update_one(
        {"chat_id": req.chat_id},
        {"$set": {"updated_at": assistant_now, "last_message_at": assistant_now}}
    )

    # Emit event
    _emit_event("message", assistant_msg_id, {
        "chat_id": req.chat_id,
        "message_id": assistant_msg_id,
        "role": "assistant",
        "content": reply,
        "workspace_id": req.workspace_id,
    })

    duration_ms = int((time.time() - start_time) * 1000)

    return VSCodeChatResponse(
        request_id=_generate_id(),
        workspace_id=req.workspace_id,
        chat_id=req.chat_id,
        user_message_id=user_msg_id,
        assistant_message_id=assistant_msg_id,
        reply=reply,
        model=CONFIG.fireworks_model,
        created_at=assistant_now,
        duration_ms=duration_ms,
    )


# 10. GET /api/me - Get current user
@router.get("/api/me", response_model=UserOut)
async def get_current_user(request: Request):
    """Get current demo user (no auth for hackathon)"""
    demo = get_demo_user(request)
    return UserOut(
        id=demo["user_id"],
        name=demo["name"],
        email=f"{demo['key']}@demo.local",
        workspace_id=demo["workspace_id"],
    )


# Ensure simple indexes for demo collections (best-effort)
def _ensure_demo_indexes():
    try:
        db = _get_demo_db()
        db["tasks"].create_index([("workspace_id", 1), ("to_user_id", 1)])
        db["events"].create_index([("workspace_id", 1), ("event_id", 1)])
        db["chats"].create_index([("workspace_id", 1)])
        db["messages"].create_index([("chat_id", 1), ("created_at", -1)])
    except Exception as exc:
        # Log but don't block startup
        log_error("INDEX_SETUP", exc)

# Run index creation in background (best-effort)
_ensure_demo_indexes()
