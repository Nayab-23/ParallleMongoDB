"""Add app_settings table and is_platform_admin flag

Revision ID: 20260301_add_app_settings_and_platform_admin
Revises: 20260102_add_notifications_severity
Create Date: 2026-03-01
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260301_add_app_settings_and_platform_admin"
down_revision = "20260102_add_notifications_severity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_column("users", "is_platform_admin")
