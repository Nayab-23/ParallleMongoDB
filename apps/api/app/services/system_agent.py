import uuid
from typing import Dict

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.graph_agent import GraphAgent


DEFAULT_SYSTEM_PIPELINE: Dict = {
    "nodes": [
        {"id": "1", "type": "email_ingest", "label": "Email Ingestion", "config": {}},
        {"id": "2", "type": "vector_search", "label": "Vector Search", "config": {"k": 50}},
        {"id": "3", "type": "reranker", "label": "Reranker", "config": {}},
        {"id": "4", "type": "task_extract", "label": "Task Extraction", "config": {}},
        {"id": "5", "type": "brief_gen", "label": "Brief Generation", "config": {}},
    ],
    "edges": [
        {"source": "1", "target": "2"},
        {"source": "2", "target": "3"},
        {"source": "3", "target": "4"},
        {"source": "4", "target": "5"},
    ],
}


def ensure_system_agent_exists(user_id: str, db: Session) -> GraphAgent:
    """
    Ensure a user has a persistent System Agent. Creates one if missing.
    """
    result = db.execute(
        select(GraphAgent).where(
            GraphAgent.user_id == user_id,
            GraphAgent.name == "System Agent",
        )
    )
    existing = result.scalars().first()
    if existing:
        return existing

    system_agent = GraphAgent(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name="System Agent",
        pipeline_config=DEFAULT_SYSTEM_PIPELINE,
        version=1,
    )
    db.add(system_agent)
    db.commit()
    db.refresh(system_agent)
    return system_agent
