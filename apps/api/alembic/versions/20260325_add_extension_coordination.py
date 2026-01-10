"""add agent extension coordination tables

Revision ID: 20260325_add_extension_coordination
Revises: 20260320_add_visible_room_ids_to_messages
Create Date: 2026-03-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260325_add_extension_coordination"
down_revision = "20260320_add_visible_room_ids_to_messages"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_clients",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device_id", sa.String(), nullable=False),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=True),
        sa.Column("head_sha", sa.String(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "device_id", "repo_id", name="uq_agent_clients_user_device_repo"),
    )
    op.create_index(
        "ix_agent_clients_org_repo_last_seen",
        "agent_clients",
        ["org_id", "repo_id", "last_seen_at"],
    )

    op.create_table(
        "agent_inbox",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("to_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("from_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("task_type", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_agent_inbox_to_status_created",
        "agent_inbox",
        ["to_user_id", "status", "created_at"],
    )
    op.create_index(
        "ix_agent_inbox_org_repo_created",
        "agent_inbox",
        ["org_id", "repo_id", "created_at"],
    )


def downgrade():
    op.drop_index("ix_agent_inbox_org_repo_created", table_name="agent_inbox")
    op.drop_index("ix_agent_inbox_to_status_created", table_name="agent_inbox")
    op.drop_table("agent_inbox")

    op.drop_index("ix_agent_clients_org_repo_last_seen", table_name="agent_clients")
    op.drop_table("agent_clients")
