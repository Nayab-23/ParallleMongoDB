"""Add severity and source_type to notifications

Revision ID: 20260102_add_notifications_severity
Revises: 95d25bc9dcb6
Create Date: 2026-01-02 00:00:00
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260102_add_notifications_severity"
down_revision = "95d25bc9dcb6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add severity column (defaults to 'normal' for existing rows)
    op.add_column(
        "notifications",
        sa.Column("severity", sa.String(), server_default="normal", nullable=True),
    )
    op.add_column(
        "notifications",
        sa.Column("source_type", sa.String(), nullable=True),
    )
    op.create_index(
        op.f("ix_notifications_severity"),
        "notifications",
        ["severity"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notifications_severity"), table_name="notifications")
    op.drop_column("notifications", "source_type")
    op.drop_column("notifications", "severity")
