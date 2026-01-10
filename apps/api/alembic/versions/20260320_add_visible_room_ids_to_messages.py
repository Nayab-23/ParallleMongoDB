"""add visible_room_ids to messages

Revision ID: 20260320_add_visible_room_ids_to_messages
Revises: 20260310_add_bootstrap_indexes
Create Date: 2026-03-20 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260320_add_visible_room_ids_to_messages"
down_revision = "20260310_add_bootstrap_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("visible_room_ids", sa.ARRAY(sa.UUID()), nullable=True))
    op.execute(
        """
        UPDATE messages
        SET visible_room_ids = ARRAY[room_id]::uuid[]
        WHERE visible_room_ids IS NULL OR cardinality(visible_room_ids)=0
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_visible_room_ids_gin ON messages USING gin (visible_room_ids)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_messages_visible_room_ids_gin")
    op.drop_column("messages", "visible_room_ids")
