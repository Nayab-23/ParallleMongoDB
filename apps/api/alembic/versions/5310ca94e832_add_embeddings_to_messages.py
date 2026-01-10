"""add_embeddings_to_messages

Revision ID: 5310ca94e832
Revises: 20250307_add_user_id_to_messages
Create Date: 2025-12-07 01:06:22.600423

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '5310ca94e832'
down_revision: Union[str, Sequence[str], None] = '20250307_add_user_id_to_messages'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Add embedding column (1536 dimensions for OpenAI text-embedding-3-small)
    op.add_column('messages', 
        sa.Column('embedding', Vector(1536), nullable=True)
    )
    
    # Add index for vector similarity search (CRITICAL for performance)
    op.execute(
        'CREATE INDEX IF NOT EXISTS messages_embedding_idx ON messages '
        'USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);'
    )

def downgrade():
    op.drop_column('messages', 'embedding')
