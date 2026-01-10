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
from hack_main import _get_demo_db, _fireworks_client, CONFIG
from logutil import log_event, log_error

# ============================================
# CONSTANTS
# ============================================

DEMO_WORKSPACE_ID = "1"
DEMO_USER_ID = "demo-user-1"
DEMO_USER_NAME = "Demo User"

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


# ============================================
# ENDPOINTS
# ============================================

# 1. POST /api/chats - Create chat
@router.post("/api/chats", response_model=ChatOut)
async def create_chat(req: CreateChatRequest):
    """Create a new chat session"""
    chats_col = _get_collection("chats")

    now = _now_iso()
    chat_id = _generate_id()

    doc = {
        "chat_id": chat_id,
        "name": req.name,
        "workspace_id": DEMO_WORKSPACE_ID,
        "created_at": now,
        "updated_at": now,
        "last_message_at": None,
    }

    result = chats_col.insert_one(doc)

    return ChatOut(
        id=chat_id,
        chat_id=chat_id,
        name=req.name,
        created_at=now,
        updated_at=now,
    )


# 2. GET /api/chats - List chats
@router.get("/api/chats", response_model=Dict[str, Any])
async def list_chats(
    limit: int = Query(50, ge=1, le=100),
    cursor: Optional[str] = None,
):
    """List all chats for demo workspace"""
    chats_col = _get_collection("chats")

    query = {"workspace_id": DEMO_WORKSPACE_ID}

    # Simple cursor pagination (using updated_at)
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

    return {
        "items": items,
        "next_cursor": next_cursor,
    }


# 3. GET /api/chats/{chat_id}/messages - Get messages
@router.get("/api/chats/{chat_id}/messages", response_model=List[MessageOut])
async def get_chat_messages(
    chat_id: str,
    limit: int = Query(50, ge=1, le=200),
):
    """Get messages for a chat"""
    messages_col = _get_collection("messages")

    docs = list(
        messages_col.find({"chat_id": chat_id})
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


# 4. POST /api/chats/{chat_id}/dispatch - Send task to extension
@router.post("/api/chats/{chat_id}/dispatch", response_model=DispatchResponse)
async def dispatch_chat(chat_id: str, req: DispatchRequest):
    """Dispatch message as task to VS Code extension"""

    # Save user message
    messages_col = _get_collection("messages")
    user_msg_id = _generate_id()
    now = _now_iso()

    messages_col.insert_one({
        "message_id": user_msg_id,
        "chat_id": chat_id,
        "role": "user",
        "content": req.content,
        "sender_id": DEMO_USER_ID,
        "sender_name": DEMO_USER_NAME,
        "created_at": now,
        "metadata": {"mode": req.mode, "repo_id": req.repo_id},
    })

    # Create task
    tasks_col = _get_collection("tasks")
    task_id = _generate_id()

    task_doc = {
        "task_id": task_id,
        "workspace_id": DEMO_WORKSPACE_ID,
        "chat_id": chat_id,
        "repo_id": req.repo_id,
        "task_type": req.task_type or "EXECUTE",
        "status": "pending",
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

    # Emit event for SSE subscribers
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
async def get_task_status(task_id: str):
    """Get task status"""
    tasks_col = _get_collection("tasks")

    doc = tasks_col.find_one({"task_id": task_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskStatusOut(
        task_id=doc["task_id"],
        status=doc["status"],
        result=doc.get("result"),
        error=doc.get("error"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


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
    workspace_id: str = Query(DEMO_WORKSPACE_ID),
    since_event_id: Optional[str] = None,
):
    """Server-Sent Events stream for realtime updates"""

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events"""
        try:
            log_event("SSE_CONNECT", workspace_id=workspace_id, last_event_id=since_event_id)
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
                        .limit(10)
                    )

                    for doc in reversed(docs):
                        event_id = doc["event_id"]
                        last_id = event_id

                        # Format SSE event
                        data = {
                            "entity_type": doc["entity_type"],
                            "id": doc["entity_id"],
                            "payload": doc["payload"],
                            "created_at": doc["created_at"].isoformat(),
                        }

                        log_event("SSE_EVENT", workspace_id=workspace_id, event_id=event_id, entity_type=doc["entity_type"])
                        yield f"id: {event_id}\n"
                        yield f"data: {json.dumps(data)}\n\n"

                    # Heartbeat every 15s if no events
                    if not docs:
                        heartbeat_count += 1
                        # Only log every 10 heartbeats (~50 seconds)
                        if heartbeat_count % 10 == 0:
                            log_event("SSE_HEARTBEAT", workspace_id=workspace_id, count=heartbeat_count)
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
async def record_edit(workspace_id: str, req: RecordEditRequest):
    """Record edit completion from VS Code extension"""
    edits_col = _get_collection("edits")
    tasks_col = _get_collection("tasks")

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

    # Best-effort: mark matching task as done to close the demo loop
    task_doc = tasks_col.find_one({"task_id": req.edit_id})
    if not task_doc:
        task_doc = tasks_col.find_one(
            {"workspace_id": workspace_id, "status": {"$in": ["pending", "running"]}},
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
async def vscode_chat(req: VSCodeChatRequest):
    """Send chat message from VS Code extension (with Fireworks AI)"""

    start_time = time.time()

    # Save user message
    messages_col = _get_collection("messages")
    user_msg_id = _generate_id()
    now = _now_iso()

    messages_col.insert_one({
        "message_id": user_msg_id,
        "chat_id": req.chat_id,
        "role": "user",
        "content": req.message,
        "sender_id": DEMO_USER_ID,
        "sender_name": "VS Code User",
        "created_at": now,
        "metadata": {"source": "vscode", "repo": req.repo},
    })

    # Get chat history for context
    history_docs = list(
        messages_col.find({"chat_id": req.chat_id})
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
async def get_current_user():
    """Get current demo user (no auth for hackathon)"""
    return UserOut(
        id=DEMO_USER_ID,
        name=DEMO_USER_NAME,
        email="demo@parallel.ai",
        workspace_id=DEMO_WORKSPACE_ID,
    )

