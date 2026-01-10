import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.api.v1.deps import (
    get_current_user,
    get_db,
    get_task_for_user,
    require_scope,
    require_workspace_member,
)
from app.services.events import record_workspace_event
from models import Task, User

router = APIRouter()

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    status: Optional[str] = "new"
    due_at: Optional[datetime] = None
    priority: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class TaskPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    due_at: Optional[datetime] = None
    priority: Optional[str] = None
    tags: Optional[List[str]] = None


class TaskOut(BaseModel):
    id: str
    workspace_id: str
    title: str
    description: str
    assignee_id: str
    status: str
    due_at: Optional[datetime] = None
    priority: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TaskList(BaseModel):
    items: List[TaskOut]
    next_cursor: Optional[str] = None


def _parse_cursor(cursor: Optional[str]):
    if not cursor or "|" not in cursor:
        return None
    ts_str, tid = cursor.split("|", 1)
    try:
        ts_val = datetime.fromisoformat(ts_str)
    except Exception:
        return None
    return ts_val, tid


def _make_cursor(ts: datetime, tid: str) -> str:
    return f"{ts.isoformat()}|{tid}"


@router.get("/workspaces/{workspace_id}/tasks", response_model=TaskList)
def list_tasks(
    workspace_id: str,
    updated_after: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_scope("tasks:read")),
):
    require_workspace_member(workspace_id, current_user, db)

    query = db.query(Task).filter(Task.workspace_id == workspace_id)

    if updated_after:
        try:
            dt = datetime.fromisoformat(updated_after)
        except Exception:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid updated_after")
        query = query.filter(
            or_(
                Task.updated_at >= dt,
                and_(Task.deleted_at.isnot(None), Task.deleted_at >= dt),
            )
        )

    parsed = _parse_cursor(cursor)
    if parsed:
        ts, tid = parsed
        query = query.filter(
            or_(
                Task.updated_at < ts,
                and_(Task.updated_at == ts, Task.id > tid),
            )
        )

    ordered_pairs = (
        query.with_entities(Task.id, Task.updated_at)
        .order_by(Task.updated_at.desc(), Task.id.asc())
        .limit(limit + 1)
        .all()
    )
    seen_ids = set()
    ordered_ids: List[str] = []
    ordered_timestamps: List[datetime] = []
    for tid, ts in ordered_pairs:
        if tid in seen_ids:
            continue
        seen_ids.add(tid)
        ordered_ids.append(tid)
        ordered_timestamps.append(ts or datetime.now(timezone.utc))

    rows_by_id = {
        row.id: row
        for row in db.query(Task).filter(Task.id.in_(ordered_ids)).all()
    }
    rows = [rows_by_id[tid] for tid in ordered_ids if tid in rows_by_id]

    next_cursor = None
    if len(rows) > limit:
        last_ts = ordered_timestamps[limit - 1]
        last_id = ordered_ids[limit - 1]
        next_cursor = _make_cursor(last_ts, last_id)
        rows = rows[:limit]

    return TaskList(
        items=[
            TaskOut(
                id=row.id,
                workspace_id=row.workspace_id or workspace_id,
                title=row.title,
                description=row.description or "",
                assignee_id=row.assignee_id,
                status=row.status,
                due_at=row.due_at,
                priority=row.priority,
                tags=row.tags or [],
                created_at=row.created_at,
                updated_at=row.updated_at,
                deleted_at=row.deleted_at,
            )
            for row in rows
        ],
        next_cursor=next_cursor,
    )


@router.post("/workspaces/{workspace_id}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(
    workspace_id: str,
    payload: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_scope("tasks:write")),
):
    require_workspace_member(workspace_id, current_user, db)
    now = datetime.now(timezone.utc)
    task = Task(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        title=payload.title,
        description=payload.description or "",
        assignee_id=current_user.id,
        status=payload.status or "new",
        due_at=payload.due_at,
        priority=payload.priority,
        tags=payload.tags or [],
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    record_workspace_event(
        db,
        workspace_id=workspace_id,
        event_type="task.created",
        resource_id=task.id,
        entity_type="task",
        user_id=current_user.id,
        payload={"title": task.title},
    )
    db.commit()
    db.refresh(task)
    return TaskOut.from_orm(task)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task: Task = Depends(get_task_for_user),
    payload: TaskPatch = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_scope("tasks:write")),
):
    now = datetime.now(timezone.utc)
    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.status is not None:
        task.status = payload.status
    if payload.due_at is not None:
        task.due_at = payload.due_at
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.tags is not None:
        task.tags = payload.tags
    task.updated_at = now

    db.add(task)
    record_workspace_event(
        db,
        workspace_id=task.workspace_id or "",
        event_type="task.updated",
        resource_id=task.id,
        entity_type="task",
        user_id=current_user.id,
        payload={"status": task.status},
    )
    db.commit()
    db.refresh(task)
    return TaskOut.from_orm(task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task: Task = Depends(get_task_for_user),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _: None = Depends(require_scope("tasks:write")),
):
    now = datetime.now(timezone.utc)
    task.deleted_at = now
    task.updated_at = now
    db.add(task)
    record_workspace_event(
        db,
        workspace_id=task.workspace_id or "",
        event_type="task.deleted",
        resource_id=task.id,
        entity_type="task",
        user_id=current_user.id,
        payload={},
    )
    db.commit()
    return None
