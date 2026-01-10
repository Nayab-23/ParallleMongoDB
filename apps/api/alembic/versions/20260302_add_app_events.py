"""Add app_events table

Revision ID: 20260302_add_app_events
Revises: 20260301_add_app_settings_and_platform_admin
Create Date: 2026-03-02
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260302_add_app_events"
down_revision = "20260301_add_app_settings_and_platform_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("user_email", sa.String(), nullable=True),
        sa.Column("target_email", sa.String(), nullable=True),
        sa.Column("event_data", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_app_events_created_at", "app_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_app_events_created_at", table_name="app_events")
    op.drop_table("app_events")
