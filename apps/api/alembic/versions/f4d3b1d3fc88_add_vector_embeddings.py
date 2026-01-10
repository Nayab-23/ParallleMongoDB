"""add_vector_embeddings

Revision ID: f4d3b1d3fc88
Revises: 5310ca94e832
Create Date: 2025-12-07 01:13:07.659241

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = 'f4d3b1d3fc88'
down_revision: Union[str, Sequence[str], None] = '5310ca94e832'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("messages")} if insp.has_table("messages") else set()

    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    
    # Add embedding column
    if "embedding" not in cols:
        op.add_column(
            "messages",
            sa.Column("embedding", Vector(1536), nullable=True),
        )
    
    # Create vector similarity index (CRITICAL for performance)
    # This uses cosine similarity - perfect for OpenAI embeddings
    op.execute(
        'CREATE INDEX IF NOT EXISTS messages_embedding_idx ON messages '
        'USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);'
    )

def downgrade():
    op.execute('DROP INDEX IF EXISTS messages_embedding_idx')
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("messages")} if insp.has_table("messages") else set()
    if "embedding" in cols:
        op.drop_column('messages', 'embedding')
    op.execute('DROP EXTENSION IF EXISTS vector')
