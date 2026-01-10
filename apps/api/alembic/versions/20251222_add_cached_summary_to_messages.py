"""Add cached_summary to messages

Revision ID: 20251222_add_cached_summary_to_messages
Revises: 20251222_add_activity_manager
Create Date: 2025-12-22
"""
from alembic import op
import sqlalchemy as sa

revision = '20251222_add_cached_summary_to_messages'
down_revision = '20251222_add_activity_manager'
branch_labels = None
depends_on = None

def upgrade():
    # Add cached_summary column to messages table
    op.add_column('messages', sa.Column('cached_summary', sa.String(100), nullable=True))

    # Add index for messages with cached summaries (WHERE clause for partial index)
    op.create_index(
        'idx_messages_cached_summary',
        'messages',
        ['cached_summary'],
        postgresql_where=sa.text('cached_summary IS NOT NULL')
    )

def downgrade():
    # Drop index
    op.drop_index('idx_messages_cached_summary', 'messages')

    # Drop column
    op.drop_column('messages', 'cached_summary')
