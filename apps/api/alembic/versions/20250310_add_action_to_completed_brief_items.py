"""add action and raw data to completed brief items

Revision ID: 20250310_add_action_to_completed_brief_items
Revises: 20250308_add_completed_brief_items
Create Date: 2025-03-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20250310_add_action_to_completed_brief_items"
down_revision = "20250309_add_user_canonical_plan"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("completed_brief_items", sa.Column("action", sa.Text(), nullable=False, server_default="completed"))
    op.add_column("completed_brief_items", sa.Column("item_title", sa.Text(), nullable=True))
    op.add_column("completed_brief_items", sa.Column("item_description", sa.Text(), nullable=True))
    op.add_column("completed_brief_items", sa.Column("timeframe", sa.Text(), nullable=True))
    op.add_column("completed_brief_items", sa.Column("section", sa.Text(), nullable=True))
    op.add_column("completed_brief_items", sa.Column("raw_item", postgresql.JSONB(), nullable=True))
    # Backfill action for existing rows
    op.execute("UPDATE completed_brief_items SET action = 'completed' WHERE action IS NULL")


def downgrade():
    op.drop_column("completed_brief_items", "raw_item")
    op.drop_column("completed_brief_items", "section")
    op.drop_column("completed_brief_items", "timeframe")
    op.drop_column("completed_brief_items", "item_description")
    op.drop_column("completed_brief_items", "item_title")
    op.drop_column("completed_brief_items", "action")
