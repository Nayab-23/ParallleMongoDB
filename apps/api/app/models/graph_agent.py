"""
Isolated models for experimental graph agents.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from models import Base, json_field_type


def _uuid() -> str:
    return str(uuid.uuid4())


class GraphAgent(Base):
    __tablename__ = "graph_agents"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    pipeline_config = Column(json_field_type, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))


class GraphExecution(Base):
    __tablename__ = "graph_executions"

    id = Column(String, primary_key=True, default=_uuid)
    agent_id = Column(String, ForeignKey("graph_agents.id"), nullable=False, index=True)
    status = Column(String, nullable=False, index=True, default="pending")  # pending/running/completed/failed
    input_data = Column(json_field_type, nullable=True)
    output_data = Column(json_field_type, nullable=True)
    metrics = Column(json_field_type, nullable=True)
    started_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)


class GraphHistory(Base):
    __tablename__ = "graph_history"

    id = Column(String, primary_key=True, default=_uuid)
    agent_id = Column(String, ForeignKey("graph_agents.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    pipeline_config = Column(json_field_type, nullable=False, default=dict)
    change_summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=True, index=True)
