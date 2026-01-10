"""Add joined_at to room_members (safe if already exists)"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250323_add_joined_at_room_members"
down_revision = "20250317_workspace_events_entity_type"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(
            "ALTER TABLE room_members ADD COLUMN IF NOT EXISTS joined_at TIMESTAMPTZ DEFAULT now()"
        )
    else:
        with op.batch_alter_table("room_members") as batch_op:
            if not _has_column(bind, "room_members", "joined_at"):
                batch_op.add_column(
                    sa.Column(
                        "joined_at",
                        sa.DateTime(timezone=True),
                        server_default=sa.text("CURRENT_TIMESTAMP"),
                    )
                )


def downgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute("ALTER TABLE room_members DROP COLUMN IF EXISTS joined_at")
    else:
        with op.batch_alter_table("room_members") as batch_op:
            if _has_column(bind, "room_members", "joined_at"):
                batch_op.drop_column("joined_at")


def _has_column(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    cols = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in cols
