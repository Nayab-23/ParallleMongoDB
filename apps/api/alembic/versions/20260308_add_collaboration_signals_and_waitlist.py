"""add collaboration signals and waitlist tables

Revision ID: 20260308_add_collab_waitlist
Revises: 20260307_add_chat_room_access
Create Date: 2026-03-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = "20260308_add_collab_waitlist"
down_revision = "20260307_add_chat_room_access"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "collaboration_signals",
        sa.Column("id", sa.String(), primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("signal_type", sa.String(), nullable=False),
        sa.Column("user_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("chat_id", sa.String(), nullable=True),
        sa.Column("message_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("computed_hash", sa.String(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("notification_id", sa.String(), nullable=True),
        sa.Column("sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_collaboration_signals_hash", "collaboration_signals", ["computed_hash"], unique=True)
    op.create_index("ix_collaboration_signals_chat_created", "collaboration_signals", ["chat_id", "created_at"])
    op.create_index("ix_collaboration_signals_window", "collaboration_signals", ["window_start", "window_end"])

    op.create_table(
        "waitlist_submissions",
        sa.Column("id", sa.String(), primary_key=True, default=lambda: str(uuid.uuid4())),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=False, index=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_waitlist_email", "waitlist_submissions", ["email"])


def downgrade():
    op.drop_index("ix_waitlist_email", table_name="waitlist_submissions")
    op.drop_table("waitlist_submissions")
    op.drop_index("ix_collaboration_signals_window", table_name="collaboration_signals")
    op.drop_index("ix_collaboration_signals_chat_created", table_name="collaboration_signals")
    op.drop_index("ix_collaboration_signals_hash", table_name="collaboration_signals")
    op.drop_table("collaboration_signals")
