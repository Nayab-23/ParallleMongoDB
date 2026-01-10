"""Add OAuth 2.1 PKCE tables

Revision ID: 20251229_add_oauth_tables
Revises: 20251222_add_cached_summary_to_messages
Create Date: 2025-12-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251229_add_oauth_tables'
down_revision = '20251222_add_cached_summary_to_messages'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # OAuth Clients table
    op.create_table(
        'oauth_clients',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('client_type', sa.String(), nullable=False, server_default='public'),
        sa.Column('client_secret_hash', sa.String(), nullable=True),
        sa.Column('redirect_uris', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('allowed_scopes', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_oauth_clients_id'), 'oauth_clients', ['id'], unique=False)

    # OAuth Authorization Codes table
    op.create_table(
        'oauth_authorization_codes',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('client_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('redirect_uri', sa.String(), nullable=False),
        sa.Column('scope', sa.String(), nullable=False),
        sa.Column('code_challenge', sa.String(), nullable=False),
        sa.Column('code_challenge_method', sa.String(), nullable=False, server_default='S256'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['oauth_clients.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_oauth_authorization_codes_id'), 'oauth_authorization_codes', ['id'], unique=False)
    op.create_index(op.f('ix_oauth_authorization_codes_client_id'), 'oauth_authorization_codes', ['client_id'], unique=False)
    op.create_index(op.f('ix_oauth_authorization_codes_user_id'), 'oauth_authorization_codes', ['user_id'], unique=False)

    # OAuth Refresh Tokens table
    op.create_table(
        'oauth_refresh_tokens',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('token_hash', sa.String(), nullable=False),
        sa.Column('client_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('scope', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('replaced_by_id', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['oauth_clients.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['replaced_by_id'], ['oauth_refresh_tokens.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_oauth_refresh_tokens_id'), 'oauth_refresh_tokens', ['id'], unique=False)
    op.create_index(op.f('ix_oauth_refresh_tokens_token_hash'), 'oauth_refresh_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_oauth_refresh_tokens_client_id'), 'oauth_refresh_tokens', ['client_id'], unique=False)
    op.create_index(op.f('ix_oauth_refresh_tokens_user_id'), 'oauth_refresh_tokens', ['user_id'], unique=False)

    # OAuth Access Tokens table
    op.create_table(
        'oauth_access_tokens',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('token_hash', sa.String(), nullable=True),
        sa.Column('client_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('refresh_token_id', sa.String(), nullable=True),
        sa.Column('scope', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['client_id'], ['oauth_clients.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['refresh_token_id'], ['oauth_refresh_tokens.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_oauth_access_tokens_id'), 'oauth_access_tokens', ['id'], unique=False)
    op.create_index(op.f('ix_oauth_access_tokens_token_hash'), 'oauth_access_tokens', ['token_hash'], unique=False)
    op.create_index(op.f('ix_oauth_access_tokens_client_id'), 'oauth_access_tokens', ['client_id'], unique=False)
    op.create_index(op.f('ix_oauth_access_tokens_user_id'), 'oauth_access_tokens', ['user_id'], unique=False)
    op.create_index(op.f('ix_oauth_access_tokens_refresh_token_id'), 'oauth_access_tokens', ['refresh_token_id'], unique=False)

    # Insert default VS Code extension client
    op.execute("""
        INSERT INTO oauth_clients (id, name, client_type, redirect_uris, allowed_scopes, is_active, created_at, updated_at)
        VALUES (
            'vscode-extension',
            'Parallel VS Code Extension',
            'public',
            '["vscode://parallel.parallel-vscode/auth-callback", "http://localhost:54321/callback"]',
            '["openid", "profile", "email", "tasks:read", "tasks:write", "chats:read", "chats:write", "workspaces:read"]',
            true,
            now(),
            now()
        )
        ON CONFLICT (id) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table('oauth_access_tokens')
    op.drop_table('oauth_refresh_tokens')
    op.drop_table('oauth_authorization_codes')
    op.drop_table('oauth_clients')


