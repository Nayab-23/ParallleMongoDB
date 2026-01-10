"""add permissions to user

Revision ID: dd59285901e0
Revises: c8a5ec79adb7
Create Date: 2025-11-28 15:13:19.955282

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "dd59285901e0"
down_revision: Union[str, Sequence[str], None] = "c8a5ec79adb7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column("permissions", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "permissions")
