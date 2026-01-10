import logging
import uuid
from datetime import datetime, timezone
from database import Base
from app.core.settings import get_settings
from pydantic import BaseModel, EmailStr
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    func,
    String,
    Text,
    UniqueConstraint,
    Date,
    text,
    event,
    BigInteger,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func as sa_func

logger = logging.getLogger(__name__)
_settings = get_settings()
json_field_type = JSONB if _settings.is_postgres else JSON

# Vector type for embeddings - only available with PostgreSQL + pgvector
if _settings.is_postgres:
    try:
        from pgvector.sqlalchemy import Vector
        vector_field_type = Vector
    except ImportError:
        vector_field_type = LargeBinary  # Fallback if pgvector not installed
else:
    vector_field_type = LargeBinary  # SQLite uses binary for embeddings

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=True)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=True)
    is_platform_admin = Column(Boolean, nullable=False, server_default='false')

    preferences = Column(JSON, default=dict)
    permissions = Column(JSON, default=dict)  # ✅ DB field

    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    # relationships
    agents = relationship("AgentProfile", back_populates="owner")
    inbox_tasks = relationship("InboxTask", back_populates="user")
    credentials = relationship("UserCredential", back_populates="user", uselist=False)
    sentiments = relationship("UserSentiment", back_populates="user")
    room_memberships = relationship("RoomMember", back_populates="user")
    external_accounts = relationship("ExternalAccount", back_populates="user", cascade="all, delete-orphan")
    actions = relationship("UserAction", back_populates="user")
    status = relationship("UserStatus", back_populates="user", uselist=False)
    personal_access_tokens = relationship(
        "PersonalAccessToken", back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------
# PERSONAL ACCESS TOKENS
# ---------------------------

class PersonalAccessToken(Base):
    __tablename__ = "personal_access_tokens"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    token_hash = Column(String, nullable=False)
    scopes = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="personal_access_tokens")

# ---------------------------
# USER CREDENTIALS
# ---------------------------

class UserCredential(Base):
    __tablename__ = "user_credentials"

    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    user = relationship("User", back_populates="credentials")


# ---------------------------
# SENTIMENT
# ---------------------------

class UserSentiment(Base):
    __tablename__ = "user_sentiments"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    score = Column(Float, default=0.0)
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    user = relationship("User", back_populates="sentiments")


# ---------------------------
# ORGANIZATIONS
# ---------------------------

class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    owner_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    invite_code = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    # relationships
    rooms = relationship("Room", back_populates="org")
    invites = relationship("OrgInvite", back_populates="org")


# ---------------------------
# AGENT PROFILE
# ---------------------------

class AgentProfile(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    persona_json = Column(JSON, default=dict)
    persona_embedding = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    owner = relationship("User", back_populates="agents")
    memories = relationship("MemoryRecord", back_populates="agent")

class Permissions(BaseModel):
    frontend: bool = True
    backend: bool = True

# ---------------------------
# ROOMS
# ---------------------------

class Room(Base):
    __tablename__ = "rooms"

    id = Column(String, primary_key=True, index=True)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)

    project_summary = Column(Text, default="")
    memory_summary = Column(Text, default="")
    summary_version = Column(Integer, default=1)
    summary_updated_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))

    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    org = relationship("Organization", back_populates="rooms")
    chat_instances = relationship(
        "ChatInstance",
        back_populates="room",
        cascade="all, delete-orphan",
    )
    messages = relationship("Message", back_populates="room")
    memories = relationship("MemoryRecord", back_populates="room")
    members = relationship("RoomMember", back_populates="room", cascade="all, delete-orphan")


class ChatInstance(Base):
    __tablename__ = "chat_instances"

    id = Column(String, primary_key=True, index=True)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    created_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    last_message_at = Column(DateTime, nullable=True)

    room = relationship("Room", back_populates="chat_instances")
    messages = relationship("Message", back_populates="chat_instance", cascade="all, delete-orphan")
    room_access = relationship("ChatRoomAccess", back_populates="chat", cascade="all, delete-orphan")


class ChatRoomAccess(Base):
    __tablename__ = "chat_room_access"

    chat_id = Column(String, ForeignKey("chat_instances.id", ondelete="CASCADE"), primary_key=True)
    room_id = Column(String, ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    chat = relationship("ChatInstance", back_populates="room_access")
    room = relationship("Room")


class ExternalAccount(Base):
    __tablename__ = "external_accounts"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String, nullable=False, index=True)  # e.g., google_gmail, google_calendar
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    scopes = Column(JSON, default=list)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    user = relationship("User", back_populates="external_accounts")

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_external_account_user_provider"),
    )


class DailyBrief(Base):
    __tablename__ = "daily_briefs"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=True, index=True)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=True, index=True)
    date = Column(Date, nullable=False, index=True)
    summary_json = Column(JSON, nullable=False)
    summary_text = Column(Text, nullable=True)
    generated_at = Column(DateTime, default=datetime.now(timezone.utc), index=True)


class UserCanonicalPlan(Base):
    __tablename__ = "user_canonical_plan"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    approved_timeline = Column(json_field_type)
    active_priorities = Column(json_field_type)

    pending_recommendations = Column(json_field_type)
    dismissed_items = Column(json_field_type)

    last_user_modification = Column(DateTime(timezone=True))
    last_ai_sync = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

class UserContextStore(Base):
    __tablename__ = "user_context_store"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    last_email_sync = Column(DateTime(timezone=True))
    last_calendar_sync = Column(DateTime(timezone=True))
    last_team_activity_sync = Column(DateTime(timezone=True))

    emails_recent = Column(json_field_type)
    emails_medium = Column(json_field_type)
    emails_old = Column(json_field_type)
    calendar_recent = Column(json_field_type)
    calendar_future = Column(json_field_type)
    team_activity_recent = Column(json_field_type)

    weekly_summary = Column(json_field_type)
    monthly_summary = Column(json_field_type)

    total_items_cached = Column(Integer, nullable=False, server_default="0")
    last_pruned_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class CompletedBriefItem(Base):
    __tablename__ = "completed_brief_items"

    id = Column(String, primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    item_signature = Column(Text, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    source_type = Column(Text, nullable=True)
    source_id = Column(Text, nullable=True)
    action = Column(Text, nullable=False, server_default="completed")  # completed | deleted
    item_title = Column(Text, nullable=True)
    item_description = Column(Text, nullable=True)
    timeframe = Column(Text, nullable=True)
    section = Column(Text, nullable=True)
    raw_item = Column(json_field_type, nullable=True)

class RoomOut(BaseModel):
    id: str
    name: str
    created_at: str
    message_count: int
    project_summary: str
    is_personal: bool = False
    
    class Config:
        from_attributes = True

class RoomMember(Base):
    __tablename__ = "room_members"

    id = Column(String, primary_key=True, index=True)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    role_in_room = Column(String, nullable=True)
    joined_at = Column(DateTime, default=datetime.now(timezone.utc))

    room = relationship("Room", back_populates="members")
    user = relationship("User", back_populates="room_memberships")

    __table_args__ = (
        UniqueConstraint("room_id", "user_id", name="unique_room_user"),
    )

class RoomMemberOut(BaseModel):
    id: str
    room_id: str
    user_id: str
    role_in_room: Optional[str] = None
    joined_at: datetime

    class Config:
        from_attributes = True

class RoomMemberCreate(BaseModel):
    room_id: str
    user_id: str
    role_in_room: Optional[str] = None

class RoomWithMembers(BaseModel):
    id: str
    name: str
    created_at: str
    member_count: int
    members: List[RoomMemberOut] = []

    class Config:
        from_attributes = True

class UserWithRooms(BaseModel):
    id: str
    name: str
    email: str
    role: Optional[str] = None
    permissions: Optional["Permissions"] = None
    rooms: List[str] = []

# ---------------------------
# MESSAGES
# ---------------------------

class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, index=True)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False, index=True)
    chat_instance_id = Column(String, ForeignKey("chat_instances.id"), nullable=False, index=True)
    sender_id = Column(String, nullable=False)
    sender_name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    user_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), index=True)
    embedding = Column(vector_field_type, nullable=True)
    cached_summary = Column(String(100), nullable=True)  # Cached AI-generated summary for activity feed
    visible_room_ids = Column(ARRAY(UUID), nullable=True)

    room = relationship("Room", back_populates="messages")
    chat_instance = relationship("ChatInstance", back_populates="messages")


# ---------------------------
# INBOX TASKS
# ---------------------------

class InboxTask(Base):
    __tablename__ = "inbox_tasks"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=True)
    source_message_id = Column(String, nullable=True)
    status = Column(String, default="open")
    priority = Column(String, nullable=True)
    tags = Column(JSON, default=list)
    pinned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    user = relationship("User", back_populates="inbox_tasks")


# ---------------------------
# MEMORY / RECALL
# ---------------------------

class MemoryRecord(Base):
    __tablename__ = "memories"

    id = Column(String, primary_key=True, index=True)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    content = Column(Text, nullable=False)
    importance_score = Column(Float, default=0.0)
    embedding = Column(vector_field_type, nullable=True)
    metadata_json = Column(json_field_type, default=dict)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_memories_room_created", "room_id", "created_at"),
        Index("ix_memories_user_created", "user_id", "created_at"),
    )

    agent = relationship("AgentProfile", back_populates="memories")
    room = relationship("Room", back_populates="memories")
    user = relationship("User", foreign_keys=[user_id])


# ---------------------------
# TASKS
# ---------------------------

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    assignee_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String, default="new", index=True)
    workspace_id = Column(String, ForeignKey("rooms.id"), nullable=True, index=True)
    due_at = Column(DateTime, nullable=True)
    priority = Column(String, nullable=True)
    tags = Column(JSON, default=list)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    assignee = relationship("User")
    workspace = relationship("Room")
    actions = relationship("UserAction", back_populates="task")


# ---------------------------
# NOTIFICATIONS
# ---------------------------

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String, default="task")
    severity = Column(String, default="normal")  # 'urgent' or 'normal'
    source_type = Column(String, nullable=True)  # 'conflict_file', 'conflict_semantic', 'task', 'mention', etc.
    title = Column(String, nullable=False)
    message = Column(Text, default="")
    task_id = Column(String, ForeignKey("tasks.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    is_read = Column(Boolean, default=False)
    data = Column(json_field_type, nullable=True, default=dict)
    signal_hash = Column(String, nullable=True, index=True)

    user = relationship("User")
    task = relationship("Task")


# ---------------------------
# EXTENSION COORDINATION
# ---------------------------


class AgentClient(Base):
    __tablename__ = "agent_clients"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(String, nullable=False)
    repo_id = Column(String, nullable=False)
    branch = Column(String, nullable=True)
    head_sha = Column(String, nullable=True)
    capabilities = Column(json_field_type, nullable=False, default=dict)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "device_id", "repo_id", name="uq_agent_clients_user_device_repo"),
        Index("ix_agent_clients_org_repo_last_seen", "org_id", "repo_id", "last_seen_at"),
    )


class AgentInbox(Base):
    __tablename__ = "agent_inbox"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    to_user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    from_user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    repo_id = Column(String, nullable=False, index=True)
    task_type = Column(String, nullable=False)
    payload = Column(json_field_type, nullable=False, default=dict)
    status = Column(String, nullable=False, server_default="pending")
    result = Column(json_field_type, nullable=True)
    error_code = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    handled_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_inbox_to_status_created", "to_user_id", "status", "created_at"),
        Index("ix_agent_inbox_org_repo_created", "org_id", "repo_id", "created_at"),
    )


# ---------------------------
# CODE EVENTS
# ---------------------------

class CodeEvent(Base):
    __tablename__ = "code_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    device_id = Column(Text, nullable=False)
    repo_id = Column(Text, nullable=False, index=True)
    branch = Column(Text, nullable=True)
    head_sha_before = Column(Text, nullable=True)
    head_sha_after = Column(Text, nullable=True)
    event_type = Column(Text, nullable=False)
    files_touched = Column(ARRAY(Text), nullable=True)
    systems_touched = Column(ARRAY(Text), nullable=True)
    tags = Column(ARRAY(Text), nullable=True)
    summary = Column(Text, nullable=True)
    details = Column(Text, nullable=True)  # Longer explanation of the change
    impact_tags = Column(ARRAY(Text), nullable=True)  # Infrastructure/contract impact flags
    created_at = Column(DateTime(timezone=True), server_default=sa_func.now(), nullable=False)

    __table_args__ = (
        Index("ix_code_events_org_repo_created", "org_id", "repo_id", text("created_at DESC")),
    )


class AgentCursor(Base):
    __tablename__ = "agent_cursors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    repo_id = Column(String, nullable=False, index=True)
    cursor_name = Column(String, nullable=False, default="code_events")
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_event_id = Column(UUID(as_uuid=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=sa_func.now(), onupdate=sa_func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", "repo_id", "cursor_name", name="uq_agent_cursor_scope"),
    )


# ---------------------------
# EVENT LOGS
# ---------------------------

class EventLog(Base):
    __tablename__ = "event_logs"

    id = Column(String, primary_key=True, index=True)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False, index=True)
    user_id = Column(String, nullable=True)
    event_type = Column(String, nullable=False)
    detail = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc), index=True)


# ---------------------------
# WORKSPACE EVENTS (SSE/WS)
# ---------------------------

class WorkspaceEvent(Base):
    __tablename__ = "workspace_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id = Column(String, ForeignKey("rooms.id"), nullable=False, index=True)
    type = Column(String, nullable=False)
    resource_id = Column(String, nullable=False)
    user_id = Column(String, nullable=True)
    entity_type = Column(String, nullable=True)
    payload = Column(json_field_type, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=sa_func.now(), index=True)


class EmbeddingJob(Base):
    __tablename__ = "embedding_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String, nullable=False)  # message | memory | summary
    entity_id = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", name="uq_embedding_job_entity"),
    )


# ---------------------------
# USER STATUS
# ---------------------------

class UserStatus(Base):
    __tablename__ = "user_status"

    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    current_status = Column(Text, nullable=False)
    status_embedding = Column(vector_field_type, nullable=True)
    raw_activity_text = Column(Text, nullable=True)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=True)
    last_updated = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="status")
    room = relationship("Room")


# ---------------------------
# USER ACTIONS
# ---------------------------

class UserAction(Base):
    __tablename__ = "user_actions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    tool = Column(String, nullable=False)  # e.g., gmail, calendar, vscode, slack, parallel_web
    action_type = Column(String, nullable=False)  # e.g., email_sent, email_read, task_created, code_edited
    action_data = Column(json_field_type, nullable=False)

    task_id = Column(String, ForeignKey("tasks.id"), nullable=True, index=True)
    session_id = Column(String, nullable=True, index=True)

    # Activity manager columns
    activity_summary = Column(Text, nullable=True)
    activity_embedding = Column(vector_field_type, nullable=True)
    similarity_to_status = Column(Float, nullable=True)
    similarity_to_previous = Column(Float, nullable=True)
    is_status_change = Column(Boolean, server_default='false')
    room_id = Column(String, ForeignKey("rooms.id"), nullable=True)

    # Relationships
    user = relationship("User", back_populates="actions")
    task = relationship("Task", back_populates="actions")
    room = relationship("Room")

class OrgMemberOut(BaseModel):
    id: str
    name: str
    role: Optional[str] = None

class OrgOut(BaseModel):
    id: str
    name: str

class UserOut(BaseModel):
    id: str
    email: str
    name: str
    created_at: datetime
    # optional but nice so frontend can show it:
    role: Optional[str] = None  

    permissions: Optional[Permissions] = None
    org_id: Optional[str] = None
    is_platform_admin: bool = False
    needs_invite: bool = False

    class Config:
        from_attributes = True


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(json_field_type, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
    )


class AppEvent(Base):
    __tablename__ = "app_events"

    id = Column(String, primary_key=True)
    event_type = Column(String, nullable=False)
    user_email = Column(String, nullable=True)
    target_email = Column(String, nullable=True)
    event_data = Column(json_field_type, nullable=True)
    request_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), index=True)

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None
    role: Optional[str] = None
    invite_code: Optional[str] = None

class CreateRoomRequest(BaseModel):
    room_name: str

    class Config:
        validate_by_name = True
        fields = {
            "room_name": "roomName",  # accept both room_name and roomName
        }


class CreateChatInstanceRequest(BaseModel):
    name: str

    class Config:
        validate_by_name = True
class MemoryQueryRequest(BaseModel):
    question: str

class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None
    role: Optional[str] = None
    invite_code: Optional[str] = None

class AuthLoginRequest(BaseModel):
    email: str
    password: str

class CreateRoomResponse(BaseModel):
    room_id: str
    room_name: str
    id: Optional[str] = None
    name: Optional[str] = None
    default_chat_id: Optional[str] = None

class MessageOut(BaseModel):
    id: str
    chat_instance_id: Optional[str] = None
    sender_id: str
    sender_name: str
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ChatInstanceOut(BaseModel):
    id: str
    room_id: str
    name: str
    created_by_user_id: Optional[str] = None
    created_at: datetime
    last_message_at: Optional[datetime] = None
    message_count: Optional[int] = None

    class Config:
        from_attributes = True

class InboxCreateRequest(BaseModel):
    content: str
    room_id: Optional[str] = None
    source_message_id: Optional[str] = None
    priority: Optional[str] = None
    tags: List[str] = []
    pinned: bool = False

class RoleUpdate(BaseModel):
    role: str

class TaskIn(BaseModel):
    title: str
    description: Optional[str] = ""
    assignee_id: str

class TaskUpdate(BaseModel):
    status: str

class TaskOut(BaseModel):
    id: str
    title: str
    description: str
    assignee_id: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class InboxTaskOut(BaseModel):
    id: str
    user_id: str
    content: str
    status: str
    priority: Optional[str] = None
    tags: List[str] = []
    pinned: bool = False
    room_id: Optional[str] = None
    source_message_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class InboxUpdateRequest(BaseModel):
    status: str
    priority: Optional[str] = None
    pinned: Optional[bool] = None

class NotificationOut(BaseModel):
    id: str
    user_id: str
    type: str
    title: str
    message: str
    task_id: Optional[str] = None
    created_at: datetime
    is_read: bool

    class Config:
        from_attributes = True

class ActivateRequest(BaseModel):
    invite_code: str
    role: Optional[str] = None  # optional – lets them pick Product/Eng/etc.

# in models.py

class OrgInvite(Base):
    __tablename__ = "org_invites"

    id = Column(String, primary_key=True, index=True)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    email = Column(String, nullable=False, index=True)

    # Keep token for now so the schema matches the existing table
    token = Column(String, unique=True, nullable=True)  # make nullable for future flexibility

    # New fields
    role = Column(String, nullable=True)
    invited_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    org = relationship("Organization", back_populates="invites")

class CreateOrgInviteRequest(BaseModel):
    email: str
    role: Optional[str] = None


# ---------------------------
# COLLABORATION SIGNALS
# ---------------------------


class CollaborationSignal(Base):
    __tablename__ = "collaboration_signals"

    id = Column(String, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    signal_type = Column(String, nullable=False)
    user_ids = Column(JSON, nullable=True)
    chat_id = Column(String, nullable=True)
    message_ids = Column(JSON, nullable=True)
    computed_hash = Column(String, nullable=False, index=True)
    window_start = Column(DateTime(timezone=True), nullable=True)
    window_end = Column(DateTime(timezone=True), nullable=True)
    score = Column(Float, nullable=True)
    notification_id = Column(String, nullable=True)
    sent = Column(Boolean, nullable=False, default=False)
    details = Column(JSON, nullable=True)


class CollaborationAuditRun(Base):
    __tablename__ = "collaboration_audit_runs"

    id = Column(String, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    params = Column(JSON, nullable=True)
    stats = Column(JSON, nullable=True)
    sample_mismatches = Column(JSON, nullable=True)


# ---------------------------
# WAITLIST
# ---------------------------


class WaitlistSubmission(Base):
    __tablename__ = "waitlist_submissions"

    id = Column(String, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    name = Column(String, nullable=True)
    email = Column(String, nullable=False, index=True)
    notes = Column(Text, nullable=True)
    source = Column(String, nullable=True)
    meta = Column(JSON, nullable=True)


# ---------------------------
# VS CODE AUTH CODES
# ---------------------------

class VSCodeAuthCode(Base):
    """
    Short-lived, single-use auth codes for VS Code browser sign-in flow.
    """
    __tablename__ = "vscode_auth_codes"

    code_hash = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")


# ---------------------------
# OAUTH 2.1 MODELS (PKCE)
# ---------------------------

class OAuthClient(Base):
    """
    Pre-registered OAuth clients (e.g., VS Code extension).
    Public clients use PKCE; no client_secret required.
    """
    __tablename__ = "oauth_clients"

    id = Column(String, primary_key=True, index=True)  # e.g., "vscode-extension"
    name = Column(String, nullable=False)
    client_type = Column(String, nullable=False, default="public")  # public | confidential
    # For confidential clients only (hashed); null for public clients
    client_secret_hash = Column(String, nullable=True)
    # JSON array of allowed redirect URIs
    redirect_uris = Column(JSON, nullable=False, default=list)
    # JSON array of allowed scopes
    allowed_scopes = Column(JSON, nullable=False, default=list)
    # Is this client active?
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class OAuthAuthorizationCode(Base):
    """
    Temporary authorization codes for OAuth PKCE flow.
    Single-use, short-lived (5-10 minutes).
    """
    __tablename__ = "oauth_authorization_codes"

    id = Column(String, primary_key=True, index=True)  # The authorization code itself
    client_id = Column(String, ForeignKey("oauth_clients.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    redirect_uri = Column(String, nullable=False)
    scope = Column(String, nullable=False)  # Space-separated scopes
    # PKCE: S256 hash of code_verifier
    code_challenge = Column(String, nullable=False)
    code_challenge_method = Column(String, nullable=False, default="S256")
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    # One-time use tracking
    used_at = Column(DateTime(timezone=True), nullable=True)

    client = relationship("OAuthClient")
    user = relationship("User")


class OAuthRefreshToken(Base):
    """
    Refresh tokens for OAuth flow.
    Hashed for security; supports rotation.
    """
    __tablename__ = "oauth_refresh_tokens"

    id = Column(String, primary_key=True, index=True)
    # Hash of the actual token value
    token_hash = Column(String, nullable=False, unique=True, index=True)
    client_id = Column(String, ForeignKey("oauth_clients.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    scope = Column(String, nullable=False)
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=True)  # null = no expiry
    # Revocation
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    # For token rotation: link to the token this one replaced
    replaced_by_id = Column(String, ForeignKey("oauth_refresh_tokens.id"), nullable=True)

    client = relationship("OAuthClient")
    user = relationship("User")


class OAuthAccessToken(Base):
    """
    Access tokens issued via OAuth.
    Short-lived; can be JWT or opaque.
    """
    __tablename__ = "oauth_access_tokens"

    id = Column(String, primary_key=True, index=True)
    # For opaque tokens, store hash; for JWT, this can be the jti claim
    token_hash = Column(String, nullable=True, index=True)
    client_id = Column(String, ForeignKey("oauth_clients.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    refresh_token_id = Column(String, ForeignKey("oauth_refresh_tokens.id"), nullable=True, index=True)
    scope = Column(String, nullable=False)
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    # Revocation (usually via refresh token revocation)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    client = relationship("OAuthClient")
    user = relationship("User")
    refresh_token = relationship("OAuthRefreshToken")


# ---------------------------
# CODE INDEXING (VS CODE)
# ---------------------------

class CodeIndexEntry(Base):
    __tablename__ = "code_index_entries"

    id = Column(String, primary_key=True, index=True)
    workspace_id = Column(String, ForeignKey("rooms.id"), nullable=False, index=True)
    file_path = Column(String, nullable=False, index=True)
    language = Column(String, nullable=True)
    symbol = Column(String, nullable=True)
    chunk_index = Column(Integer, nullable=False, default=0)
    content = Column(Text, nullable=False)
    metadata_json = Column("metadata", json_field_type, nullable=True)
    embedding = Column(vector_field_type, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
    )

    room = relationship("Room")


# ---------------------------
# AGENT EDIT HISTORY
# ---------------------------

class AgentEditHistory(Base):
    __tablename__ = "agent_edit_history"

    id = Column(String, primary_key=True, index=True)
    workspace_id = Column(String, ForeignKey("rooms.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    description = Column(Text, nullable=True)
    source = Column(String, nullable=True)
    files_modified = Column(json_field_type, nullable=False)
    original_content = Column(json_field_type, nullable=False)
    new_content = Column(json_field_type, nullable=False)

    user = relationship("User")
    room = relationship("Room")


# ---------------------------
# EMBEDDING JOB ENQUEUE HOOKS
# ---------------------------

def _enqueue_embedding_job(connection, entity_type: str, entity_id: str) -> None:
    """
    Lightweight enqueue that runs on insert.
    Uses a raw INSERT to avoid session recursion.
    """
    settings = get_settings()
    if not settings.rag_enabled or settings.is_sqlite:
        return

    try:
        connection.execute(
            text(
                """
                INSERT INTO embedding_jobs (id, entity_type, entity_id, status, attempts, created_at, updated_at)
                VALUES (:id, :entity_type, :entity_id, 'pending', 0, now(), now())
                ON CONFLICT (entity_type, entity_id) DO NOTHING
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "entity_type": entity_type,
                "entity_id": entity_id,
            },
        )
    except Exception as exc:
        logger.debug(
            "Skipping embedding job enqueue for %s %s: %s",
            entity_type,
            entity_id,
            exc,
        )


@event.listens_for(Message, "after_insert")
def _after_message_insert(mapper, connection, target):  # type: ignore[override]
    _enqueue_embedding_job(connection, "message", target.id)


@event.listens_for(MemoryRecord, "after_insert")
def _after_memory_insert(mapper, connection, target):  # type: ignore[override]
    _enqueue_embedding_job(connection, "memory", target.id)
