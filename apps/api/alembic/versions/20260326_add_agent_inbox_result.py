"""add result fields to agent_inbox

Revision ID: 20260326_add_agent_inbox_result
Revises: 20260325_add_extension_coordination
Create Date: 2026-03-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260326_add_agent_inbox_result"
down_revision = "20260325_add_extension_coordination"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns("agent_inbox")}

    if "result" not in existing_cols:
        op.add_column("agent_inbox", sa.Column("result", sa.JSON(), nullable=True))
    if "error_code" not in existing_cols:
        op.add_column("agent_inbox", sa.Column("error_code", sa.String(), nullable=True))


def downgrade():
    # Downgrade remains destructive; assumes columns exist
    op.drop_column("agent_inbox", "error_code")
    op.drop_column("agent_inbox", "result")
