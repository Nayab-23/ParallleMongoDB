"""add agent cursors for code events

Revision ID: 20260327_add_agent_cursors
Revises: 20260326_add_agent_inbox_result
Create Date: 2026-03-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260327_add_agent_cursors"
down_revision = "20260326_add_agent_inbox_result"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_cursors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("cursor_name", sa.String(), nullable=False, server_default="code_events"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "user_id", "repo_id", "cursor_name", name="uq_agent_cursor_scope"),
    )
    op.create_index("ix_agent_cursors_org", "agent_cursors", ["org_id"])
    op.create_index("ix_agent_cursors_user", "agent_cursors", ["user_id"])
    op.create_index("ix_agent_cursors_repo", "agent_cursors", ["repo_id"])


def downgrade():
    op.drop_index("ix_agent_cursors_repo", table_name="agent_cursors")
    op.drop_index("ix_agent_cursors_user", table_name="agent_cursors")
    op.drop_index("ix_agent_cursors_org", table_name="agent_cursors")
    op.drop_table("agent_cursors")
