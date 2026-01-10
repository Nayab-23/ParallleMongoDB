"""Add user_id to messages"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250307_add_user_id_to_messages"
down_revision = "20250306_add_chat_instances"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("user_id", sa.String(), nullable=True))
    op.create_index("ix_messages_user_id", "messages", ["user_id"])

    conn = op.get_bind()
    # Backfill user messages: sender_id like 'user:<id>'
    conn.execute(
        sa.text(
            """
            UPDATE messages
            SET user_id = SUBSTRING(sender_id FROM 6)
            WHERE sender_id LIKE 'user:%' AND user_id IS NULL
            """
        )
    )
    # Backfill assistant messages: join agents to find owner
    conn.execute(
        sa.text(
            """
            UPDATE messages m
            SET user_id = a.user_id
            FROM agents a
            WHERE m.user_id IS NULL
              AND m.sender_id LIKE 'agent:%'
              AND REPLACE(m.sender_id, 'agent:', '') = a.id
            """
        )
    )


def downgrade():
    op.drop_index("ix_messages_user_id", table_name="messages")
    op.drop_column("messages", "user_id")
