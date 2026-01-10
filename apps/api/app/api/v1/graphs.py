from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db
from app.models.graph_agent import GraphAgent, GraphExecution, GraphHistory
from app.services.graph_executor import GraphExecutor
from app.services.graph_modifier import PipelineModifier
from app.services.system_agent import ensure_system_agent_exists
from app.api.dependencies.auth import parse_admin_emails, is_platform_admin_user
from models import User

router = APIRouter(prefix="/graphs", tags=["graphs-experimental"])


class CreateGraphPayload(BaseModel):
    name: str
    pipeline: Dict[str, Any]


class ExecutePayload(BaseModel):
    input_data: Dict[str, Any] = {}


class ModifyPayload(BaseModel):
    request: str


class RollbackPayload(BaseModel):
    version: int


def _ensure_owner(agent: GraphAgent, current_user: User) -> None:
    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")


def _load_agent(db: Session, agent_id: str, current_user: User) -> GraphAgent:
    agent = db.query(GraphAgent).filter(GraphAgent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    _ensure_owner(agent, current_user)
    return agent


def _is_admin(user: User) -> bool:
    admin_emails = parse_admin_emails()
    return is_platform_admin_user(user, admin_emails)


@router.get("/me")
async def get_my_system_agent(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access only")

    agent = (
        db.query(GraphAgent)
        .filter(GraphAgent.user_id == current_user.id, GraphAgent.name == "System Agent")
        .first()
    )
    if not agent:
        agent = ensure_system_agent_exists(current_user.id, db)

    return {
        "success": True,
        "data": {
            "id": agent.id,
            "name": agent.name,
            "pipeline": agent.pipeline_config,
            "version": agent.version,
            "created_at": agent.created_at.isoformat() if getattr(agent, "created_at", None) else None,
            "updated_at": agent.updated_at.isoformat() if getattr(agent, "updated_at", None) else None,
        },
    }


@router.post("", status_code=201)
async def create_graph_agent(
    payload: CreateGraphPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = GraphAgent(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        name=payload.name,
        pipeline_config=payload.pipeline,
        version=1,
        created_at=datetime.now(timezone.utc),
    )
    history = GraphHistory(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        version=1,
        pipeline_config=payload.pipeline,
        change_summary="initial",
        created_at=datetime.now(timezone.utc),
        created_by=current_user.id,
    )
    db.add(agent)
    db.add(history)
    db.commit()
    return {
        "id": agent.id,
        "name": agent.name,
        "pipeline": agent.pipeline_config,
        "version": agent.version,
    }


@router.get("/{agent_id}")
async def get_graph_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = _load_agent(db, agent_id, current_user)
    return {
        "id": agent.id,
        "name": agent.name,
        "pipeline": agent.pipeline_config,
        "version": agent.version,
    }


@router.get("/{agent_id}/history")
async def get_graph_history(
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = _load_agent(db, agent_id, current_user)
    rows = (
        db.query(GraphHistory)
        .filter(GraphHistory.agent_id == agent.id)
        .order_by(GraphHistory.version.desc())
        .all()
    )
    return [
        {
            "version": r.version,
            "change_summary": r.change_summary,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "created_by": r.created_by,
            "pipeline": r.pipeline_config,
        }
        for r in rows
    ]


@router.post("/{agent_id}/execute")
async def execute_graph(
    agent_id: str,
    payload: ExecutePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = _load_agent(db, agent_id, current_user)
    execution = GraphExecution(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        status="running",
        input_data=payload.input_data,
        started_at=datetime.now(timezone.utc),
    )
    db.add(execution)
    db.commit()

    workspace_id = getattr(current_user, "org_id", None) or f"graph-{current_user.id}"
    executor = GraphExecutor(db, workspace_id=workspace_id, user_id=current_user.id)
    try:
        result = await executor.execute(agent.id, agent.pipeline_config or {}, payload.input_data)
        execution.status = "completed"
        execution.output_data = result
        execution.metrics = result.get("metrics")
        execution.completed_at = datetime.now(timezone.utc)
        db.commit()
        return {"execution_id": execution.id, "status": execution.status, "result": result}
    except Exception as exc:
        execution.status = "failed"
        execution.completed_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=500, detail=f"Execution failed: {exc}") from exc


@router.get("/{agent_id}/executions")
async def list_executions(
    agent_id: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = _load_agent(db, agent_id, current_user)
    rows = (
        db.query(GraphExecution)
        .filter(GraphExecution.agent_id == agent.id)
        .order_by(GraphExecution.started_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "metrics": r.metrics,
        }
        for r in rows
    ]


@router.post("/{agent_id}/modify")
async def modify_pipeline(
    agent_id: str,
    payload: ModifyPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = _load_agent(db, agent_id, current_user)
    modifier = PipelineModifier(db, current_user)
    try:
        result = await modifier.modify_from_request(agent, payload.request)
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Pipeline modification failed: {exc}") from exc


@router.post("/{agent_id}/rollback")
async def rollback_pipeline(
    agent_id: str,
    payload: RollbackPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = _load_agent(db, agent_id, current_user)
    target = (
        db.query(GraphHistory)
        .filter(GraphHistory.agent_id == agent.id, GraphHistory.version == payload.version)
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Version not found")

    new_version = agent.version + 1
    agent.pipeline_config = target.pipeline_config
    agent.version = new_version
    agent.updated_at = datetime.now(timezone.utc)

    rollback_history = GraphHistory(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        version=new_version,
        pipeline_config=target.pipeline_config,
        change_summary=f"rollback to version {payload.version}",
        created_at=datetime.now(timezone.utc),
        created_by=current_user.id,
    )
    db.add(rollback_history)
    db.commit()

    return {
        "id": agent.id,
        "name": agent.name,
        "pipeline": agent.pipeline_config,
        "version": agent.version,
    }
