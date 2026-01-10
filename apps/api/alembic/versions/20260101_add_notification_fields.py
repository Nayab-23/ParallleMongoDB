"""Add severity and source_type to notifications

Revision ID: 20260101_add_notification_fields
Revises: 20251229_add_vscode_auth_codes
Create Date: 2026-01-01
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260101_add_notification_fields'
down_revision = '20251229_add_vscode_auth_codes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("notifications"):
        op.create_table(
            'notifications',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('type', sa.String(), server_default='task', nullable=True),
            sa.Column('severity', sa.String(), server_default='normal', nullable=True),
            sa.Column('source_type', sa.String(), nullable=True),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('message', sa.Text(), server_default='', nullable=True),
            sa.Column('task_id', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column('is_read', sa.Boolean(), server_default='false', nullable=True),
            sa.Column('data', sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['task_id'], ['tasks.id']),
        )
        op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)
    else:
        # Add severity column (default 'normal')
        op.add_column('notifications', sa.Column('severity', sa.String(), server_default='normal', nullable=True))
        # Add source_type column (nullable)
        op.add_column('notifications', sa.Column('source_type', sa.String(), nullable=True))

    # Create indexes for better query performance
    op.create_index(op.f('ix_notifications_severity'), 'notifications', ['severity'], unique=False)
    op.create_index(op.f('ix_notifications_source_type'), 'notifications', ['source_type'], unique=False)


def downgrade() -> None:
    # Remove indexes
    op.drop_index(op.f('ix_notifications_source_type'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_severity'), table_name='notifications')

    # Remove columns
    op.drop_column('notifications', 'source_type')
    op.drop_column('notifications', 'severity')
