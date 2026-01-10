"""baseline

Revision ID: c8a5ec79adb7
Revises: 
Create Date: 2025-11-28 14:58:12.604832
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c8a5ec79adb7"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Baseline schema for subsequent migrations.

    IMPORTANT: This must create the initial tables expected by later migrations
    (which add/alter columns and constraints).
    """
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    json_type = sa.JSON()

    insp = sa.inspect(bind)
    if insp.has_table("alembic_version"):
        with op.batch_alter_table("alembic_version") as batch:
            batch.alter_column(
                "version_num",
                existing_type=sa.String(length=32),
                type_=sa.Text(),
                existing_nullable=False,
            )

    op.create_table(
        "organizations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=True),
        sa.Column("invite_code", sa.String(), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("preferences", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_org_id", "users", ["org_id"])

    op.create_table(
        "user_credentials",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
    )

    op.create_table(
        "agents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("persona_json", json_type, nullable=True),
        sa.Column("persona_embedding", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
    )
    op.create_index("ix_agents_user_id", "agents", ["user_id"])

    op.create_table(
        "rooms",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("project_summary", sa.Text(), nullable=True),
        sa.Column("memory_summary", sa.Text(), nullable=True),
        sa.Column("summary_version", sa.Integer(), nullable=True),
        sa.Column("summary_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
    )
    op.create_index("ix_rooms_org_id", "rooms", ["org_id"])

    op.create_table(
        "room_members",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("room_id", sa.String(), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role_in_room", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
    )
    op.create_index("ix_room_members_room_id", "room_members", ["room_id"])
    op.create_index("ix_room_members_user_id", "room_members", ["user_id"])

    op.create_table(
        "daily_briefs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("summary_json", json_type, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
    )
    op.create_index("ix_daily_briefs_user_id", "daily_briefs", ["user_id"])
    op.create_index("ix_daily_briefs_org_id", "daily_briefs", ["org_id"])
    op.create_index("ix_daily_briefs_date", "daily_briefs", ["date"])

    op.create_table(
        "messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("room_id", sa.String(), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("sender_id", sa.String(), nullable=False),
        sa.Column("sender_name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
    )
    op.create_index("ix_messages_room_id", "messages", ["room_id"])

    op.create_table(
        "memories",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("room_id", sa.String(), sa.ForeignKey("rooms.id"), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance_score", sa.Float(), nullable=True),
        sa.Column("embedding", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
    )
    op.create_index("ix_memories_agent_id", "memories", ["agent_id"])
    op.create_index("ix_memories_room_id", "memories", ["room_id"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("assignee_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
    )
    op.create_index("ix_tasks_assignee_id", "tasks", ["assignee_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    op.create_table(
        "inbox_tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("room_id", sa.String(), sa.ForeignKey("rooms.id"), nullable=True),
        sa.Column("source_message_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("priority", sa.String(), nullable=True),
        sa.Column("tags", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
    )
    op.create_index("ix_inbox_tasks_user_id", "inbox_tasks", ["user_id"])
    op.create_index("ix_inbox_tasks_room_id", "inbox_tasks", ["room_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_inbox_tasks_room_id", table_name="inbox_tasks")
    op.drop_index("ix_inbox_tasks_user_id", table_name="inbox_tasks")
    op.drop_table("inbox_tasks")

    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_assignee_id", table_name="tasks")
    op.drop_table("tasks")

    op.drop_index("ix_memories_room_id", table_name="memories")
    op.drop_index("ix_memories_agent_id", table_name="memories")
    op.drop_table("memories")

    op.drop_index("ix_messages_room_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_daily_briefs_date", table_name="daily_briefs")
    op.drop_index("ix_daily_briefs_org_id", table_name="daily_briefs")
    op.drop_index("ix_daily_briefs_user_id", table_name="daily_briefs")
    op.drop_table("daily_briefs")

    op.drop_index("ix_room_members_user_id", table_name="room_members")
    op.drop_index("ix_room_members_room_id", table_name="room_members")
    op.drop_table("room_members")

    op.drop_index("ix_rooms_org_id", table_name="rooms")
    op.drop_table("rooms")

    op.drop_index("ix_agents_user_id", table_name="agents")
    op.drop_table("agents")

    op.drop_table("user_credentials")

    op.drop_index("ix_users_org_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    op.drop_table("organizations")
