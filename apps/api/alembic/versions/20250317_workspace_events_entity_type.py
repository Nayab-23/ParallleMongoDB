"""Add entity_type to workspace_events

Revision ID: 20250317_workspace_events_entity_type
Revises: 20250316_room_summary_column_fix
Create Date: 2025-12-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20250317_workspace_events_entity_type"
down_revision: Union[str, Sequence[str], None] = "20250316_room_summary_column_fix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("workspace_events")} if insp.has_table("workspace_events") else set()
    if "entity_type" not in cols:
        op.add_column("workspace_events", sa.Column("entity_type", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("workspace_events")} if insp.has_table("workspace_events") else set()
    if "entity_type" in cols:
        op.drop_column("workspace_events", "entity_type")

