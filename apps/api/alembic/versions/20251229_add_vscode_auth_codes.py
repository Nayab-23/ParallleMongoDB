"""Add VS Code auth codes

Revision ID: 20251229_add_vscode_auth_codes
Revises: 20251229_add_oauth_tables
Create Date: 2025-12-29
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251229_add_vscode_auth_codes'
down_revision = '20251229_add_oauth_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'vscode_auth_codes',
        sa.Column('code_hash', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('code_hash')
    )
    op.create_index(op.f('ix_vscode_auth_codes_code_hash'), 'vscode_auth_codes', ['code_hash'], unique=False)
    op.create_index(op.f('ix_vscode_auth_codes_user_id'), 'vscode_auth_codes', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_vscode_auth_codes_user_id'), table_name='vscode_auth_codes')
    op.drop_index(op.f('ix_vscode_auth_codes_code_hash'), table_name='vscode_auth_codes')
    op.drop_table('vscode_auth_codes')
