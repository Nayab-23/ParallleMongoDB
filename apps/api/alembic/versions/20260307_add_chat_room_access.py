"""Add chat_room_access table for cross-room chat visibility

Revision ID: 20260307_add_chat_room_access
Revises: 20260306_add_graph_system
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260307_add_chat_room_access"
down_revision = "20260306_add_graph_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_room_access",
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("room_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["chat_id"], ["chat_instances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chat_id", "room_id"),
    )
    op.create_index("idx_chat_room_access_chat", "chat_room_access", ["chat_id"])
    op.create_index("idx_chat_room_access_room", "chat_room_access", ["room_id"])

    # Backfill existing chat → room links
    op.execute(
        """
        INSERT INTO chat_room_access (chat_id, room_id)
        SELECT id, room_id
        FROM chat_instances
        WHERE room_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("idx_chat_room_access_chat", table_name="chat_room_access")
    op.drop_index("idx_chat_room_access_room", table_name="chat_room_access")
    op.drop_table("chat_room_access")
