"""Add activity manager tables and columns

Revision ID: 20251222_add_activity_manager
Revises: 20250323_add_joined_at_room_members
Create Date: 2025-12-22
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = '20251222_add_activity_manager'
down_revision = '20250323_add_joined_at_room_members'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # Create user_status table
    op.create_table(
        'user_status',
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('current_status', sa.Text(), nullable=False),
        sa.Column('status_embedding', Vector(1536), nullable=True),
        sa.Column('raw_activity_text', sa.Text(), nullable=True),
        sa.Column('room_id', sa.String(), nullable=True),
        sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id']),
        sa.PrimaryKeyConstraint('user_id')
    )

    op.create_index('idx_user_status_updated', 'user_status', ['last_updated'], postgresql_ops={'last_updated': 'DESC'})
    op.create_index('idx_user_status_embedding', 'user_status', ['status_embedding'],
                    postgresql_using='ivfflat',
                    postgresql_with={'lists': 100},
                    postgresql_ops={'status_embedding': 'vector_cosine_ops'})

    if not insp.has_table("user_actions"):
        op.create_table(
            'user_actions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('tool', sa.String(), nullable=False),
            sa.Column('action_type', sa.String(), nullable=False),
            sa.Column('action_data', sa.JSON(), nullable=False),
            sa.Column('task_id', sa.String(), nullable=True),
            sa.Column('session_id', sa.String(), nullable=True),
            sa.Column('activity_summary', sa.Text(), nullable=True),
            sa.Column('activity_embedding', Vector(1536), nullable=True),
            sa.Column('similarity_to_status', sa.Float(), nullable=True),
            sa.Column('similarity_to_previous', sa.Float(), nullable=True),
            sa.Column('is_status_change', sa.Boolean(), server_default='false'),
            sa.Column('room_id', sa.String(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.ForeignKeyConstraint(['task_id'], ['tasks.id']),
            sa.ForeignKeyConstraint(['room_id'], ['rooms.id']),
        )
        op.create_index('ix_user_actions_user_id', 'user_actions', ['user_id'])
        op.create_index('ix_user_actions_timestamp', 'user_actions', ['timestamp'])
        op.create_index('ix_user_actions_task_id', 'user_actions', ['task_id'])
        op.create_index('ix_user_actions_session_id', 'user_actions', ['session_id'])
    else:
        op.add_column('user_actions', sa.Column('activity_summary', sa.Text(), nullable=True))
        op.add_column('user_actions', sa.Column('activity_embedding', Vector(1536), nullable=True))
        op.add_column('user_actions', sa.Column('similarity_to_status', sa.Float(), nullable=True))
        op.add_column('user_actions', sa.Column('similarity_to_previous', sa.Float(), nullable=True))
        op.add_column('user_actions', sa.Column('is_status_change', sa.Boolean(), server_default='false'))
        op.add_column('user_actions', sa.Column('room_id', sa.String(), nullable=True))

        op.create_foreign_key('user_actions_room_id_fkey', 'user_actions', 'rooms', ['room_id'], ['id'])

        op.create_index('idx_user_actions_embedding', 'user_actions', ['activity_embedding'],
                        postgresql_using='ivfflat',
                        postgresql_with={'lists': 100},
                        postgresql_ops={'activity_embedding': 'vector_cosine_ops'})
        op.create_index('idx_user_actions_room_id', 'user_actions', ['room_id'])
        op.create_index('idx_user_actions_status_change', 'user_actions', ['is_status_change'],
                        postgresql_where=sa.text('is_status_change = true'))

        return

    op.create_index('idx_user_actions_embedding', 'user_actions', ['activity_embedding'],
                    postgresql_using='ivfflat',
                    postgresql_with={'lists': 100},
                    postgresql_ops={'activity_embedding': 'vector_cosine_ops'})
    op.create_index('idx_user_actions_room_id', 'user_actions', ['room_id'])
    op.create_index('idx_user_actions_status_change', 'user_actions', ['is_status_change'],
                    postgresql_where=sa.text('is_status_change = true'))

def downgrade():
    # Drop indexes
    op.drop_index('idx_user_actions_status_change', 'user_actions')
    op.drop_index('idx_user_actions_room_id', 'user_actions')
    op.drop_index('idx_user_actions_embedding', 'user_actions')

    # Drop foreign key
    op.drop_constraint('user_actions_room_id_fkey', 'user_actions', type_='foreignkey')

    # Drop columns from user_actions
    op.drop_column('user_actions', 'room_id')
    op.drop_column('user_actions', 'is_status_change')
    op.drop_column('user_actions', 'similarity_to_previous')
    op.drop_column('user_actions', 'similarity_to_status')
    op.drop_column('user_actions', 'activity_embedding')
    op.drop_column('user_actions', 'activity_summary')

    # Drop user_status table
    op.drop_index('idx_user_status_embedding', 'user_status')
    op.drop_index('idx_user_status_updated', 'user_status')
    op.drop_table('user_status')
