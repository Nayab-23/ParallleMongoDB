"""add indexes to speed bootstrap/rooms

Revision ID: 20260310_add_bootstrap_indexes
Revises: 20260309_add_collab_audit_and_notification_link
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260310_add_bootstrap_indexes"
down_revision = "20260309_add_collab_audit_and_notification_link"
branch_labels = None
depends_on = None


def upgrade():
    # Safe indexes; if they already exist, PostgreSQL will error, so use IF NOT EXISTS where supported
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_instances_room_id ON chat_instances (room_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_room_member_user_id ON room_members (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_room_member_room_id ON room_members (room_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_room_access_room_id ON chat_room_access (room_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_room_access_chat_id ON chat_room_access (chat_id)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_chat_room_access_chat_id")
    op.execute("DROP INDEX IF EXISTS idx_chat_room_access_room_id")
    op.execute("DROP INDEX IF EXISTS idx_room_member_room_id")
    op.execute("DROP INDEX IF EXISTS idx_room_member_user_id")
    op.execute("DROP INDEX IF EXISTS idx_chat_instances_room_id")
