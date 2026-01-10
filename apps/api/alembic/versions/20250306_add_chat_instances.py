"""Add chat instances and link messages"""

from alembic import op
import sqlalchemy as sa
import uuid
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision = "20250306_add_chat_instances"
down_revision = "20250222_pin_inbox_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_instances",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("room_id", sa.String(), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_chat_instances_room_id", "chat_instances", ["room_id"])

    op.add_column("messages", sa.Column("chat_instance_id", sa.String(), nullable=True))
    op.create_index("ix_messages_chat_instance_id", "messages", ["chat_instance_id"])
    op.create_foreign_key(
        "fk_messages_chat_instance",
        source_table="messages",
        referent_table="chat_instances",
        local_cols=["chat_instance_id"],
        remote_cols=["id"],
    )

    conn = op.get_bind()
    rooms = conn.execute(sa.text("SELECT id, created_at FROM rooms")).fetchall()
    for room_id, room_created_at in rooms:
        chat_id = str(uuid.uuid4())
        created_at = room_created_at or datetime.now(timezone.utc)
        last_message_at = conn.execute(
            sa.text("SELECT MAX(created_at) FROM messages WHERE room_id = :room_id"),
            {"room_id": room_id},
        ).scalar()

        conn.execute(
            sa.text(
                """
                INSERT INTO chat_instances (id, room_id, name, created_by_user_id, created_at, last_message_at)
                VALUES (:id, :room_id, :name, NULL, :created_at, :last_message_at)
                """
            ),
            {
                "id": chat_id,
                "room_id": room_id,
                "name": "General",
                "created_at": created_at,
                "last_message_at": last_message_at,
            },
        )

        conn.execute(
            sa.text(
                """
                UPDATE messages
                SET chat_instance_id = :chat_id
                WHERE room_id = :room_id
                """
            ),
            {"chat_id": chat_id, "room_id": room_id},
        )

    op.alter_column("messages", "chat_instance_id", nullable=False)


def downgrade():
    op.drop_constraint("fk_messages_chat_instance", "messages", type_="foreignkey")
    op.drop_index("ix_messages_chat_instance_id", table_name="messages")
    op.drop_column("messages", "chat_instance_id")

    op.drop_index("ix_chat_instances_room_id", table_name="chat_instances")
    op.drop_table("chat_instances")
