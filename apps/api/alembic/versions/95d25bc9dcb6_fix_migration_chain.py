"""fix migration chain

Revision ID: 95d25bc9dcb6
Revises: 20260101_add_notification_fields  # keep chain linear to avoid multiple heads
Create Date: 2025-12-30
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '95d25bc9dcb6'
down_revision = '20260101_add_notification_fields'
branch_labels = None
depends_on = None

def upgrade():
    # Empty migration - just fixes the chain
    pass

def downgrade():
    pass
