"""add graph system tables

Revision ID: 20260306_add_graph_system
Revises: 20260305_add_event_data_to_app_events
Create Date: 2026-03-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260306_add_graph_system"
down_revision = "20260305_add_event_data_to_app_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = postgresql.JSONB(astext_type=sa.Text())
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if "graph_agents" not in existing_tables:
        op.create_table(
            "graph_agents",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("pipeline_config", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_graph_agents_user_id ON graph_agents (user_id)"))

    if "graph_executions" not in existing_tables:
        op.create_table(
            "graph_executions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("agent_id", sa.String(), sa.ForeignKey("graph_agents.id"), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("input_data", json_type, nullable=True),
            sa.Column("output_data", json_type, nullable=True),
            sa.Column("metrics", json_type, nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_graph_executions_agent_id ON graph_executions (agent_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_graph_executions_status ON graph_executions (status)"))

    if "graph_history" not in existing_tables:
        op.create_table(
            "graph_history",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("agent_id", sa.String(), sa.ForeignKey("graph_agents.id"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("pipeline_config", json_type, nullable=False),
            sa.Column("change_summary", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        )
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_graph_history_agent_id ON graph_history (agent_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_graph_history_version ON graph_history (version)"))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_graph_history_version"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_graph_history_agent_id"))
    if op.get_bind().dialect.has_table(op.get_bind(), "graph_history"):
        op.drop_table("graph_history")

    op.execute(sa.text("DROP INDEX IF EXISTS ix_graph_executions_status"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_graph_executions_agent_id"))
    if op.get_bind().dialect.has_table(op.get_bind(), "graph_executions"):
        op.drop_table("graph_executions")

    op.execute(sa.text("DROP INDEX IF EXISTS ix_graph_agents_user_id"))
    if op.get_bind().dialect.has_table(op.get_bind(), "graph_agents"):
        op.drop_table("graph_agents")
