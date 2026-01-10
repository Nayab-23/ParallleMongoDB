"""Normalize room summary timestamp column

Revision ID: 20250316_room_summary_column_fix
Revises: 20250315_vscode_api_baseline, f4d3b1d3fc88
Create Date: 2025-03-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20250316_room_summary_column_fix"
down_revision: Union[str, Sequence[str], None] = ("20250315_vscode_api_baseline", "f4d3b1d3fc88")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_columns(bind) -> set[str]:
    insp = sa.inspect(bind)
    return {col["name"] for col in insp.get_columns("rooms")}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _get_columns(bind)
    is_pg = bind.dialect.name == "postgresql"
    default = sa.text("now()") if is_pg else None

    if "summaries_updated_at" in cols and "summary_updated_at" not in cols:
        with op.batch_alter_table("rooms") as batch:
            batch.alter_column(
                "summaries_updated_at",
                new_column_name="summary_updated_at",
                existing_type=sa.DateTime(timezone=True),
            )
    elif "summary_updated_at" not in cols:
        op.add_column(
            "rooms",
            sa.Column("summary_updated_at", sa.DateTime(timezone=True), server_default=default, nullable=True),
        )

    # Drop the stray column if both exist
    cols = _get_columns(bind)
    if "summaries_updated_at" in cols and "summary_updated_at" in cols:
        with op.batch_alter_table("rooms") as batch:
            batch.drop_column("summaries_updated_at")


def downgrade() -> None:
    bind = op.get_bind()
    cols = _get_columns(bind)
    is_pg = bind.dialect.name == "postgresql"
    default = sa.text("now()") if is_pg else None

    if "summary_updated_at" in cols and "summaries_updated_at" not in cols:
        with op.batch_alter_table("rooms") as batch:
            batch.alter_column(
                "summary_updated_at",
                new_column_name="summaries_updated_at",
                existing_type=sa.DateTime(timezone=True),
            )
    elif "summaries_updated_at" not in cols:
        op.add_column(
            "rooms",
            sa.Column("summaries_updated_at", sa.DateTime(timezone=True), server_default=default, nullable=True),
        )

    cols = _get_columns(bind)
    if "summary_updated_at" in cols and "summaries_updated_at" in cols:
        with op.batch_alter_table("rooms") as batch:
            batch.drop_column("summary_updated_at")

