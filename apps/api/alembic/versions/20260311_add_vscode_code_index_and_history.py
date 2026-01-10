"""add_vscode_code_index_and_history

Revision ID: 20260311_add_vscode_code_index_and_history
Revises: 20260310_add_bootstrap_indexes
Create Date: 2026-03-11 10:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

try:
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover - optional dependency
    Vector = None

# revision identifiers, used by Alembic.
revision: str = "20260311_add_vscode_code_index_and_history"
down_revision: Union[str, Sequence[str], None] = "20260310_add_bootstrap_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    is_postgres = dialect == "postgresql"

    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    embedding_type = Vector(1536) if is_postgres and Vector is not None else sa.LargeBinary()

    op.create_table(
        "code_index_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("embedding", embedding_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_code_index_entries_workspace_id",
        "code_index_entries",
        ["workspace_id"],
    )
    op.create_index(
        "ix_code_index_entries_file_path",
        "code_index_entries",
        ["file_path"],
    )
    op.create_index(
        "ix_code_index_entries_workspace_file",
        "code_index_entries",
        ["workspace_id", "file_path"],
    )
    if is_postgres:
        op.execute(
            "CREATE INDEX IF NOT EXISTS code_index_entries_embedding_idx "
            "ON code_index_entries USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);"
        )

    op.create_table(
        "agent_edit_history",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("rooms.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("files_modified", sa.JSON(), nullable=False),
        sa.Column("original_content", sa.JSON(), nullable=False),
        sa.Column("new_content", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_agent_edit_history_workspace_id",
        "agent_edit_history",
        ["workspace_id"],
    )
    op.create_index(
        "ix_agent_edit_history_user_id",
        "agent_edit_history",
        ["user_id"],
    )


def downgrade():
    op.drop_index("ix_agent_edit_history_user_id", table_name="agent_edit_history")
    op.drop_index("ix_agent_edit_history_workspace_id", table_name="agent_edit_history")
    op.drop_table("agent_edit_history")

    bind = op.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS code_index_entries_embedding_idx")
    op.drop_index("ix_code_index_entries_workspace_file", table_name="code_index_entries")
    op.drop_index("ix_code_index_entries_file_path", table_name="code_index_entries")
    op.drop_index("ix_code_index_entries_workspace_id", table_name="code_index_entries")
    op.drop_table("code_index_entries")
