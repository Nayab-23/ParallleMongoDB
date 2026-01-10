"""VSCode extension API baseline: PATs, events, soft-deletes

Revision ID: 20250315_vscode_api_baseline
Revises: 20250312_rag_pgvector_upgrade
Create Date: 2025-03-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20250315_vscode_api_baseline"
down_revision: Union[str, Sequence[str], None] = "20250312_rag_pgvector_upgrade"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_pg(bind) -> bool:
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = _is_pg(bind)
    json_type = postgresql.JSONB() if is_pg else sa.JSON()

    # Personal access tokens
    op.create_table(
        "personal_access_tokens",
        sa.Column("id", sa.String(), primary_key=True, index=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("scopes", json_type, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()") if is_pg else None,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Chat/message soft-delete + metadata
    op.add_column(
        "chat_instances",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()") if is_pg else None,
            nullable=True,
        ),
    )
    op.add_column("chat_instances", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column(
        "messages",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()") if is_pg else None,
            nullable=True,
        ),
    )
    op.add_column("messages", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("metadata_json", json_type, nullable=True))

    # Task enhancements
    op.add_column("tasks", sa.Column("workspace_id", sa.String(), sa.ForeignKey("rooms.id"), nullable=True))
    op.add_column("tasks", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("priority", sa.String(), nullable=True))
    op.add_column("tasks", sa.Column("tags", json_type, nullable=True))
    op.add_column("tasks", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tasks_workspace", "tasks", ["workspace_id"])

    # Workspace events table for SSE/WS
    op.create_table(
        "workspace_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("rooms.id"), nullable=False, index=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("resource_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("payload", json_type, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()") if is_pg else None,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("workspace_events")
    op.drop_index("ix_tasks_workspace", table_name="tasks")
    op.drop_column("tasks", "deleted_at")
    op.drop_column("tasks", "tags")
    op.drop_column("tasks", "priority")
    op.drop_column("tasks", "due_at")
    op.drop_column("tasks", "workspace_id")

    op.drop_column("messages", "metadata_json")
    op.drop_column("messages", "deleted_at")
    op.drop_column("messages", "updated_at")

    op.drop_column("chat_instances", "deleted_at")
    op.drop_column("chat_instances", "updated_at")

    op.drop_table("personal_access_tokens")
