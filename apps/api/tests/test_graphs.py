import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import graphs
from app.api.v1.deps import get_current_user, get_db
from app.models.graph_agent import GraphAgent, GraphExecution, GraphHistory
from models import Base, User


DATABASE_URL = "sqlite:///./test_graphs.db"

engine = create_engine(
    DATABASE_URL,
    future=True,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def setup_module():
    # Create only the tables we need to keep SQLite simple
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            GraphAgent.__table__,
            GraphExecution.__table__,
            GraphHistory.__table__,
        ],
    )


def teardown_module():
    Base.metadata.drop_all(
        bind=engine,
        tables=[
            GraphExecution.__table__,
            GraphHistory.__table__,
            GraphAgent.__table__,
            User.__table__,
        ],
    )


def get_app():
    app = FastAPI()
    app.include_router(graphs.router, prefix="/api/v1")

    async def override_get_current_user():
        db = TestingSessionLocal()
        user = db.query(User).first()
        if not user:
            user = User(id="user-1", email="user@example.com", name="User One", org_id=None)
            db.add(user)
            db.commit()
        db.close()
        return user

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db
    return app


def _basic_pipeline():
    return {
        "nodes": [
            {"id": "email_ingest", "type": "email_ingest"},
            {"id": "vector_search", "type": "vector_search"},
            {"id": "task_extract", "type": "task_extract"},
        ],
        "edges": [
            {"source": "email_ingest", "target": "vector_search"},
            {"source": "vector_search", "target": "task_extract"},
        ],
    }


def test_create_and_get_agent():
    app = get_app()
    client = TestClient(app)
    resp = client.post("/api/v1/graphs", json={"name": "Test Agent", "pipeline": _basic_pipeline()})
    assert resp.status_code == 201, resp.text
    agent_id = resp.json()["id"]

    get_resp = client.get(f"/api/v1/graphs/{agent_id}")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["name"] == "Test Agent"
    assert body["version"] == 1


def test_execute_pipeline():
    app = get_app()
    client = TestClient(app)
    resp = client.post("/api/v1/graphs", json={"name": "Exec Agent", "pipeline": _basic_pipeline()})
    agent_id = resp.json()["id"]

    exec_resp = client.post(f"/api/v1/graphs/{agent_id}/execute", json={"input_data": {"foo": "bar"}})
    assert exec_resp.status_code == 200, exec_resp.text
    data = exec_resp.json()
    assert data["status"] in {"running", "completed", "failed"}
    assert "execution_id" in data


def test_modify_and_history_and_rollback():
    app = get_app()
    client = TestClient(app)
    resp = client.post("/api/v1/graphs", json={"name": "Mod Agent", "pipeline": _basic_pipeline()})
    agent_id = resp.json()["id"]

    modify_resp = client.post(f"/api/v1/graphs/{agent_id}/modify", json={"request": "prioritize urgent emails"})
    assert modify_resp.status_code == 200, modify_resp.text
    new_version = modify_resp.json()["version"]
    assert new_version == 2

    history_resp = client.get(f"/api/v1/graphs/{agent_id}/history")
    assert history_resp.status_code == 200
    history = history_resp.json()
    assert any(h["version"] == 2 for h in history)

    rollback_resp = client.post(f"/api/v1/graphs/{agent_id}/rollback", json={"version": 1})
    assert rollback_resp.status_code == 200
    assert rollback_resp.json()["version"] == 3  # rollback recorded as new version
