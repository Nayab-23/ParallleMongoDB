"""Add code_events table for tracking code changes

Revision ID: 20260108_add_code_events
Revises: 20260305_add_event_data_to_app_events
Create Date: 2026-01-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260108_add_code_events"
down_revision = "20260305_add_event_data_to_app_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create code_events table for tracking code changes."""
    # Create code_events table
    op.create_table(
        "code_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column("repo_id", sa.Text(), nullable=False),
        sa.Column("branch", sa.Text(), nullable=True),
        sa.Column("head_sha_before", sa.Text(), nullable=True),
        sa.Column("head_sha_after", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("files_touched", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("systems_touched", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name="fk_code_events_org_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_code_events_user_id"),
    )

    # Create composite index for primary queries (org + repo + time)
    op.create_index(
        "ix_code_events_org_repo_created",
        "code_events",
        ["org_id", "repo_id", sa.text("created_at DESC")],
    )

    # Create GIN indexes for array columns (efficient array containment queries)
    op.execute(
        "CREATE INDEX ix_code_events_files_touched ON code_events USING GIN (files_touched)"
    )
    op.execute(
        "CREATE INDEX ix_code_events_systems_touched ON code_events USING GIN (systems_touched)"
    )

    # Create index on user_id for user-specific queries
    op.create_index(
        "ix_code_events_user_id",
        "code_events",
        ["user_id"],
    )


def downgrade() -> None:
    """Drop code_events table and all indexes."""
    op.drop_index("ix_code_events_user_id", table_name="code_events")
    op.drop_index("ix_code_events_systems_touched", table_name="code_events")
    op.drop_index("ix_code_events_files_touched", table_name="code_events")
    op.drop_index("ix_code_events_org_repo_created", table_name="code_events")
    op.drop_table("code_events")
