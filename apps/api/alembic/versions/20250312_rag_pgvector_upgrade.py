"""RAG infrastructure upgrade: pgvector, memory embeddings, search indexes

Revision ID: 20250312_rag_pgvector_upgrade
Revises: 20250310_add_action_to_completed_brief_items
Create Date: 2025-03-12
"""

import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "20250312_rag_pgvector_upgrade"
down_revision: Union[str, Sequence[str], None] = "20250310_add_action_to_completed_brief_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


def _migrate_memory_embeddings(bind) -> None:
    """Copy existing JSON embeddings into the new vector column when possible."""
    result = bind.execute(sa.text("SELECT id, embedding FROM memories WHERE embedding IS NOT NULL"))
    rows = result.fetchall()

    for row in rows:
        emb = row.embedding
        if not isinstance(emb, (list, tuple)):
            continue
        if len(emb) != 1536:
            continue
        try:
            vector_literal = "[" + ",".join(str(float(x)) for x in emb) + "]"
            bind.execute(
                sa.text(
                    "UPDATE memories SET embedding_vec = CAST(:vec AS vector) WHERE id = :id"
                ),
                {"vec": vector_literal, "id": row.id},
            )
        except Exception:
            # Best effort; continue on failures
            continue


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = _is_postgres(bind)

    # Core tables/columns that should exist on all backends
    op.create_table(
        "embedding_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True) if is_pg else sa.String(), primary_key=True),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()") if is_pg else None),
        sa.UniqueConstraint("entity_type", "entity_id", name="uq_embedding_job_entity"),
    )

    op.add_column(
        "rooms",
        sa.Column(
            "summaries_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()") if is_pg else None,
            nullable=True,
        ),
    )
    op.add_column("daily_briefs", sa.Column("room_id", sa.String(), nullable=True))
    op.add_column("daily_briefs", sa.Column("summary_text", sa.Text(), nullable=True))

    op.add_column("memories", sa.Column("user_id", sa.String(), nullable=True))
    op.add_column(
        "memories",
        sa.Column(
            "metadata_json",
            postgresql.JSONB() if is_pg else sa.JSON(),
            nullable=True,
        ),
    )

    if not is_pg:
        # SQLite/dev path: keep legacy JSON embeddings; indexes still help recency filtering
        op.create_index("ix_memories_room_created", "memories", ["room_id", "created_at"], unique=False)
        op.create_index("ix_memories_user_created", "memories", ["user_id", "created_at"], unique=False)
        return

    # Postgres-specific: extensions and vector conversion
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.add_column("memories", sa.Column("embedding_vec", Vector(1536), nullable=True))

    _migrate_memory_embeddings(bind)

    op.drop_column("memories", "embedding")
    op.alter_column("memories", "embedding_vec", new_column_name="embedding")

    op.create_index("ix_memories_room_created", "memories", ["room_id", "created_at"], unique=False)
    op.create_index("ix_memories_user_created", "memories", ["user_id", "created_at"], unique=False)

    index_type = os.getenv("VECTOR_INDEX_TYPE", "ivfflat").lower()
    if index_type not in {"ivfflat", "hnsw"}:
        index_type = "ivfflat"

    if index_type == "hnsw":
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS memories_embedding_idx
            ON memories
            USING hnsw (embedding vector_cosine_ops)
            """
        )
    else:
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS memories_embedding_idx
            ON memories
            USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
            """
        )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS memories_metadata_json_idx
        ON memories
        USING gin (metadata_json)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS messages_content_trgm_idx
        ON messages
        USING gin (content gin_trgm_ops)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = _is_postgres(bind)

    if is_pg:
        op.execute("DROP INDEX IF EXISTS messages_content_trgm_idx")
        op.execute("DROP INDEX IF EXISTS memories_embedding_idx")
        op.execute("DROP INDEX IF EXISTS memories_metadata_json_idx")

        # Revert vector column to a simple JSON column (data is dropped in downgrade)
        op.alter_column("memories", "embedding", new_column_name="embedding_vec")
        op.add_column("memories", sa.Column("embedding", postgresql.JSONB(), nullable=True))
        op.drop_column("memories", "embedding_vec")

    op.drop_index("ix_memories_user_created", table_name="memories")
    op.drop_index("ix_memories_room_created", table_name="memories")

    op.drop_column("memories", "metadata_json")
    op.drop_column("memories", "user_id")

    op.drop_column("daily_briefs", "summary_text")
    op.drop_column("daily_briefs", "room_id")
    op.drop_column("rooms", "summaries_updated_at")

    op.drop_table("embedding_jobs")

