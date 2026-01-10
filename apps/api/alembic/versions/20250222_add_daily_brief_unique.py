"""Add unique constraint on daily_briefs user/date"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250222_add_daily_brief_unique"
# adjust this to match your current head revision
down_revision = "dd59285901e0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_daily_briefs_user_date",
        "daily_briefs",
        ["user_id", "date"],
    )


def downgrade():
    op.drop_constraint(
        "uq_daily_briefs_user_date",
        "daily_briefs",
        type_="unique",
    )
