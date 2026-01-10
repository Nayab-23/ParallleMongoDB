"""add completed_brief_items"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250308_add_completed_brief_items"
down_revision = "20250308_add_user_context_store"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "completed_brief_items",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),  # Fixed
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_signature", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("source_type", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Text(), nullable=True),
    )
    op.create_index("ix_completed_brief_items_user_id", "completed_brief_items", ["user_id"])
    op.create_index("ix_completed_brief_items_signature", "completed_brief_items", ["item_signature"])


def downgrade():
    op.drop_index("ix_completed_brief_items_signature", table_name="completed_brief_items")
    op.drop_index("ix_completed_brief_items_user_id", table_name="completed_brief_items")
    op.drop_table("completed_brief_items")