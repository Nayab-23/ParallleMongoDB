"""
Debug endpoints for System Agent diagnostics.

These endpoints help diagnose why the System Agent feature may not be
appearing in the frontend chat list.
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, get_db, require_workspace_member
from app.api.dependencies.auth import (
    parse_admin_emails,
    is_platform_admin_user,
    require_platform_admin,
)
from app.models.graph_agent import GraphAgent
from app.services.system_agent import ensure_system_agent_exists
from models import User, ChatInstance

router = APIRouter()
logger = logging.getLogger(__name__)


class WhoAmIResponse(BaseModel):
    user_id: str
    email: str
    is_platform_admin_db: bool
    is_platform_admin_computed: bool
    admin_emails_configured: List[str]
    email_in_admin_list: bool


class SystemAgentResponse(BaseModel):
    exists: bool
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    user_id: Optional[str] = None
    version: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    pipeline_config: Optional[dict] = None


class AllSystemAgentsResponse(BaseModel):
    total_count: int
    agents: List[SystemAgentResponse]


class ChatListTestResponse(BaseModel):
    user_id: str
    workspace_id: str
    is_admin: bool
    system_agent_exists: bool
    system_agent_id: Optional[str] = None
    would_show_in_list: bool
    reason: str
    regular_chat_count: int


@router.get("/whoami", response_model=WhoAmIResponse)
def debug_whoami(
    current_user: User = Depends(get_current_user),
):
    """
    Debug endpoint to check current user's admin status.

    Returns detailed information about:
    - User ID and email
    - Database platform_admin flag
    - Computed admin status (via ADMIN_EMAILS)
    - Configured admin emails
    - Whether user's email is in the admin list
    """
    admin_emails = parse_admin_emails()
    is_admin = is_platform_admin_user(current_user, admin_emails)
    email_normalized = current_user.email.strip().lower() if current_user.email else None

    logger.info(
        f"[Debug /whoami] User: {current_user.id} ({current_user.email}), "
        f"is_platform_admin={getattr(current_user, 'is_platform_admin', False)}, "
        f"computed_admin={is_admin}, admin_emails={admin_emails}"
    )

    return WhoAmIResponse(
        user_id=current_user.id,
        email=current_user.email,
        is_platform_admin_db=getattr(current_user, "is_platform_admin", False),
        is_platform_admin_computed=is_admin,
        admin_emails_configured=sorted(list(admin_emails)),
        email_in_admin_list=email_normalized in admin_emails if email_normalized else False,
    )


@router.get("/system-agent", response_model=SystemAgentResponse)
def debug_system_agent(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Debug endpoint to check if System Agent exists for current user.

    Returns:
    - Whether the agent exists
    - Agent details if it exists
    - None values if it doesn't exist
    """
    agent = (
        db.query(GraphAgent)
        .filter(GraphAgent.user_id == current_user.id, GraphAgent.name == "System Agent")
        .first()
    )

    if agent:
        logger.info(
            f"[Debug /system-agent] Found System Agent for user {current_user.id}: "
            f"id={agent.id}, version={agent.version}"
        )
        return SystemAgentResponse(
            exists=True,
            agent_id=agent.id,
            agent_name=agent.name,
            user_id=agent.user_id,
            version=agent.version,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
            pipeline_config=agent.pipeline_config,
        )
    else:
        logger.info(f"[Debug /system-agent] No System Agent found for user {current_user.id}")
        return SystemAgentResponse(exists=False)


@router.post("/system-agent/create", response_model=SystemAgentResponse)
def debug_create_system_agent(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Debug endpoint to force create a System Agent for the current user.

    This will:
    1. Check if one already exists
    2. Create one if it doesn't exist
    3. Return the agent details

    Useful for testing the creation logic.
    """
    logger.info(f"[Debug /system-agent/create] Creating System Agent for user {current_user.id}")

    agent = ensure_system_agent_exists(current_user.id, db)

    logger.info(
        f"[Debug /system-agent/create] System Agent ensured for user {current_user.id}: "
        f"id={agent.id}, version={agent.version}"
    )

    return SystemAgentResponse(
        exists=True,
        agent_id=agent.id,
        agent_name=agent.name,
        user_id=agent.user_id,
        version=agent.version,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        pipeline_config=agent.pipeline_config,
    )


@router.get("/all-system-agents", response_model=AllSystemAgentsResponse)
def debug_all_system_agents(
    _: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    """
    Debug endpoint to list ALL System Agents in the database.

    Admin-only endpoint that shows:
    - Total count of System Agents
    - Details for each System Agent

    Useful for understanding system-wide state.
    """
    agents = db.query(GraphAgent).filter(GraphAgent.name == "System Agent").all()

    logger.info(f"[Debug /all-system-agents] Found {len(agents)} System Agent(s)")

    agent_responses = [
        SystemAgentResponse(
            exists=True,
            agent_id=agent.id,
            agent_name=agent.name,
            user_id=agent.user_id,
            version=agent.version,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
            pipeline_config=agent.pipeline_config,
        )
        for agent in agents
    ]

    return AllSystemAgentsResponse(
        total_count=len(agents),
        agents=agent_responses,
    )


@router.get("/test-chat-list/{workspace_id}", response_model=ChatListTestResponse)
def debug_test_chat_list(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Debug endpoint to simulate the chat list logic for System Agent.

    This replicates the exact logic from GET /workspaces/{workspace_id}/chats
    but returns diagnostic information instead of the actual chat list.

    Returns:
    - Whether user is admin
    - Whether System Agent exists
    - Whether it would show in the chat list
    - Reason for the outcome
    - Count of regular chats
    """
    # Verify workspace membership
    require_workspace_member(workspace_id, current_user, db)

    # Check admin status
    admin_emails = parse_admin_emails()
    is_admin = is_platform_admin_user(current_user, admin_emails)

    # Count regular chats
    regular_chat_count = (
        db.query(func.count(ChatInstance.id))
        .filter(ChatInstance.room_id == workspace_id)
        .scalar()
    )

    # Check for System Agent
    agent = (
        db.query(GraphAgent)
        .filter(GraphAgent.user_id == current_user.id, GraphAgent.name == "System Agent")
        .first()
    )

    # Determine outcome
    if not is_admin:
        reason = "User is not a platform admin"
        would_show = False
        system_agent_id = None
    elif agent:
        reason = "System Agent exists and would be prepended to chat list"
        would_show = True
        system_agent_id = agent.id
    else:
        reason = "System Agent does not exist but would be created and shown"
        would_show = True
        system_agent_id = None

    logger.info(
        f"[Debug /test-chat-list] workspace={workspace_id}, user={current_user.id}, "
        f"is_admin={is_admin}, agent_exists={agent is not None}, "
        f"would_show={would_show}, reason={reason}"
    )

    return ChatListTestResponse(
        user_id=current_user.id,
        workspace_id=workspace_id,
        is_admin=is_admin,
        system_agent_exists=agent is not None,
        system_agent_id=system_agent_id,
        would_show_in_list=would_show,
        reason=reason,
        regular_chat_count=regular_chat_count,
    )
