"""Extend code_events schema with details and impact_tags

Revision ID: 20260108_extend_code_events_schema
Revises: 20260108_add_code_events
Create Date: 2026-01-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260108_extend_code_events_schema"
down_revision = "20260108_add_code_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add details and impact_tags columns to code_events table."""
    # Add details column (longer explanation of the change)
    op.add_column(
        "code_events",
        sa.Column("details", sa.Text(), nullable=True)
    )

    # Add impact_tags column (low-level infrastructure/contract changes)
    op.add_column(
        "code_events",
        sa.Column("impact_tags", postgresql.ARRAY(sa.Text()), nullable=True)
    )

    # Create GIN index on impact_tags for efficient array containment queries
    op.execute(
        "CREATE INDEX ix_code_events_impact_tags ON code_events USING GIN (impact_tags)"
    )


def downgrade() -> None:
    """Remove details and impact_tags columns from code_events table."""
    op.drop_index("ix_code_events_impact_tags", table_name="code_events")
    op.drop_column("code_events", "impact_tags")
    op.drop_column("code_events", "details")
