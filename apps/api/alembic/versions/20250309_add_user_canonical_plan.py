"""add user canonical plan table

Revision ID: 20250309_add_user_canonical_plan
Revises: 20250308_add_completed_brief_items
Create Date: 2025-03-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20250309_add_user_canonical_plan"
down_revision = "20250308_add_completed_brief_items"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_canonical_plan",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_timeline", postgresql.JSONB(), nullable=True),
        sa.Column("active_priorities", postgresql.JSONB(), nullable=True),
        sa.Column("pending_recommendations", postgresql.JSONB(), nullable=True),
        sa.Column("dismissed_items", postgresql.JSONB(), nullable=True),
        sa.Column("last_user_modification", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ai_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_user_canonical_plan_user_id", "user_canonical_plan", ["user_id"])


def downgrade():
    op.drop_index("ix_user_canonical_plan_user_id", table_name="user_canonical_plan")
    op.drop_table("user_canonical_plan")

