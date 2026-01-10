"""Merge production migration heads

Revision ID: 20260328_merge_heads
Revises: 20260327_add_agent_cursors, 20260311_add_vscode_code_index_and_history, 20260108_extend_code_events_schema
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260328_merge_heads"
down_revision = (
    "20260327_add_agent_cursors",
    "20260311_add_vscode_code_index_and_history",
    "20260108_extend_code_events_schema",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge all migration branches - no schema changes needed."""
    pass


def downgrade() -> None:
    """No-op downgrade for merge migration."""
    pass
