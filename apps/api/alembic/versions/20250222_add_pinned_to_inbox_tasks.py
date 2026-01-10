"""Add pinned column to inbox_tasks"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
# Keep revision <= 32 chars to fit alembic_version column
revision = "20250222_pin_inbox_tasks"
down_revision = "20250222_add_daily_brief_unique"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "inbox_tasks",
        sa.Column("pinned", sa.Boolean(), nullable=True),
    )
    op.execute("UPDATE inbox_tasks SET pinned = false WHERE pinned IS NULL")
    op.alter_column("inbox_tasks", "pinned", nullable=False)


def downgrade():
    op.drop_column("inbox_tasks", "pinned")
