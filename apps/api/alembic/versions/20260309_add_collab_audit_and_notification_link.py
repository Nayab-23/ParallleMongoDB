"""add collaboration audit runs and notification signal hash

Revision ID: 20260309_add_collab_audit_and_notification_link
Revises: 20260308_add_collab_waitlist
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260309_add_collab_audit_and_notification_link"
down_revision = "20260308_add_collab_waitlist"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notifications", sa.Column("signal_hash", sa.String(), nullable=True))
    op.create_index("ix_notifications_signal_hash", "notifications", ["signal_hash"])

    op.create_table(
        "collaboration_audit_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sample_mismatches", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade():
    op.drop_table("collaboration_audit_runs")
    op.drop_index("ix_notifications_signal_hash", table_name="notifications")
    op.drop_column("notifications", "signal_hash")
