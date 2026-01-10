"""Add event_data to app_events

Revision ID: 20260305_add_event_data_to_app_events
Revises: 20260104_add_performance_indexes
Create Date: 2026-03-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260305_add_event_data_to_app_events"
down_revision = "20260104_add_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns("app_events")}
    if "event_data" in existing_cols:
        return

    try:
        op.add_column(
            "app_events",
            sa.Column(
                "event_data",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )
    except Exception:
        # Fallback for non-Postgres (or if JSONB import fails)
        op.add_column("app_events", sa.Column("event_data", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns("app_events")}
    if "event_data" in existing_cols:
        op.drop_column("app_events", "event_data")
