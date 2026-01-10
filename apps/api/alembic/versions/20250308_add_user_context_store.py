"""add user_context_store"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20250308_add_user_context_store"
down_revision = "f4d3b1d3fc88"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_context_store",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),  # Changed from UUID to String
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),  # Changed from UUID to String
        sa.Column("last_email_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_calendar_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_team_activity_sync", sa.DateTime(timezone=True), nullable=True),
        sa.Column("emails_recent", postgresql.JSONB(), nullable=True),
        sa.Column("emails_medium", postgresql.JSONB(), nullable=True),
        sa.Column("emails_old", postgresql.JSONB(), nullable=True),
        sa.Column("calendar_recent", postgresql.JSONB(), nullable=True),
        sa.Column("calendar_future", postgresql.JSONB(), nullable=True),
        sa.Column("team_activity_recent", postgresql.JSONB(), nullable=True),
        sa.Column("weekly_summary", postgresql.JSONB(), nullable=True),
        sa.Column("monthly_summary", postgresql.JSONB(), nullable=True),
        sa.Column("total_items_cached", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_pruned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_user_context_store_user_id", "user_context_store", ["user_id"])


def downgrade():
    op.drop_index("ix_user_context_store_user_id", table_name="user_context_store")
    op.drop_table("user_context_store")