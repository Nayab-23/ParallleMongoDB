import os
import pathlib
import sys
from datetime import datetime, timezone, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite:///./test_api_v1.db"
os.environ["RAG_ENABLED"] = "false"
os.environ.setdefault("SECRET_KEY", "testsecret")

from tests.test_v1_api import (  # noqa: E402
    SessionLocal,
    auth_header_for,
    make_app,
    seed_data,
)
from models import ChatInstance, Message, Task  # noqa: E402


def _seed_workspace_data():
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        # Tasks
        mine = Task(
            id="task-me-1",
            workspace_id="ws1",
            title="My assigned task",
            status="open",
            assignee_id="u1",
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(minutes=5),
        )
        other = Task(
            id="task-other-1",
            workspace_id="ws1",
            title="Other user task",
            status="open",
            assignee_id="u2",
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(minutes=10),
        )

        # Assistant conversation
        pa_chat = ChatInstance(
            id="chat-pa",
            room_id="ws1",
            name="Parallel Assistant",
            created_by_user_id="u1",
            created_at=now - timedelta(hours=1),
            last_message_at=now - timedelta(minutes=1),
        )
        msg_user = Message(
            id="msg-1",
            room_id="ws1",
            chat_instance_id=pa_chat.id,
            sender_id="u1",
            sender_name="User One",
            role="user",
            content="Can you help with tests?",
            created_at=now - timedelta(minutes=2),
        )
        msg_assistant = Message(
            id="msg-2",
            room_id="ws1",
            chat_instance_id=pa_chat.id,
            sender_id="u1",
            sender_name="Parallel Assistant",
            role="assistant",
            content="Sure, here are steps.",
            created_at=now - timedelta(minutes=1),
        )

        db.add_all([mine, other, pa_chat, msg_user, msg_assistant])
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def client():
    seed_data()
    _seed_workspace_data()
    app = make_app()
    with TestClient(app) as c:
        yield c


def _make_pat(client: TestClient, scopes: list[str]) -> str:
    # Reset in-memory rate limiter to avoid cross-test coupling
    import app.api.v1.deps as deps

    deps._rate_limit_state.clear()
    resp = client.post(
        "/api/v1/auth/pat",
        json={"name": "vscode", "scopes": scopes},
        headers=auth_header_for("u1"),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["token"]


def test_vscode_context_returns_assistant_data(client: TestClient):
    token = _make_pat(client, ["tasks:read", "chats:read"])
    resp = client.get(
        "/api/v1/workspaces/ws1/vscode/context",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["workspace_id"] == "ws1"
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["assignee_id"] == "u1"
    assert len(body["conversations"]) == 1
    convo = body["conversations"][0]
    assert convo["title"] == "Parallel Assistant"
    assert "messages" not in convo


def test_vscode_context_include_messages_requires_scope(client: TestClient):
    token = _make_pat(client, ["tasks:read", "chats:read"])
    resp = client.get(
        "/api/v1/workspaces/ws1/vscode/context",
        params={"include_messages": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403

    token_with_msgs = _make_pat(client, ["tasks:read", "chats:read", "messages:read"])
    resp_ok = client.get(
        "/api/v1/workspaces/ws1/vscode/context",
        params={"include_messages": True, "messages_limit": 1},
        headers={"Authorization": f"Bearer {token_with_msgs}"},
    )
    assert resp_ok.status_code == 200, resp_ok.text
    convo = resp_ok.json()["conversations"][0]
    assert "messages" in convo
    assert len(convo["messages"]) == 1
    assert convo["messages"][0]["role"] in {"assistant", "user"}


def test_agent_propose_returns_relative_paths(client: TestClient):
    token = _make_pat(client, ["tasks:read", "chats:read", "edits:propose"])
    payload = {
        "request": "Add logging and fix tests",
        "mode": "dry-run",
        "repo": {
            "name": "parallel-backend",
            "open_files": ["/abs/path/main.py", "src/app.py"],
            "selected_files": [],
            "diff": "diff --git a b",
            "diagnostics": [],
        },
        "context": {},
        "output": {"format": "fullText", "max_files": 3},
    }
    resp = client.post(
        "/api/v1/workspaces/ws1/vscode/agent/propose",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body["plan"], list) and body["plan"]
    assert "contextUsed" in body
    for edit in body["edits"]:
        assert not edit["filePath"].startswith("/")
        assert ".." not in pathlib.PurePosixPath(edit["filePath"]).parts
    # Ensure at least one edit derived from relative input
    assert any(edit["filePath"] == "src/app.py" for edit in body["edits"])


def test_agent_propose_requires_files_read_for_file_context(client: TestClient):
    payload = {
        "request": "Tweak logging",
        "mode": "dry-run",
        "repo": {
            "name": "parallel-backend",
            "files": [
                {"relative": "main.py", "content": "print('hi')\n"},
            ],
        },
        "context": {},
        "output": {"format": "fullText", "max_files": 1},
    }

    token = _make_pat(client, ["tasks:read", "chats:read", "edits:propose"])
    resp = client.post(
        "/api/v1/workspaces/ws1/vscode/agent/propose",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403

    token_ok = _make_pat(client, ["tasks:read", "chats:read", "edits:propose", "files:read"])
    resp_ok = client.post(
        "/api/v1/workspaces/ws1/vscode/agent/propose",
        json=payload,
        headers={"Authorization": f"Bearer {token_ok}"},
    )
    assert resp_ok.status_code == 200, resp_ok.text


def test_agent_propose_apply_requires_scope(client: TestClient):
    payload = {
        "request": "Apply small change",
        "mode": "apply",
        "repo": {
            "name": "parallel-backend",
            "open_files": ["main.py"],
        },
        "context": {},
        "output": {"format": "fullText", "max_files": 1},
    }

    token = _make_pat(client, ["tasks:read", "chats:read", "edits:propose"])
    resp = client.post(
        "/api/v1/workspaces/ws1/vscode/agent/propose",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403

    token_ok = _make_pat(client, ["tasks:read", "chats:read", "edits:propose", "edits:apply"])
    resp_ok = client.post(
        "/api/v1/workspaces/ws1/vscode/agent/propose",
        json=payload,
        headers={"Authorization": f"Bearer {token_ok}"},
    )
    assert resp_ok.status_code == 200, resp_ok.text


def test_inline_completion_requires_scope(client: TestClient):
    payload = {
        "filePath": "main.py",
        "languageId": "python",
        "prefix": "def add(a, b):\n    return a +",
        "suffix": "\n",
        "cursor": {"line": 1, "character": 15},
        "maxCompletions": 1,
    }
    token = _make_pat(client, ["files:read"])
    resp = client.post(
        "/api/v1/workspaces/ws1/vscode/agent/complete",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_plan_requires_scope(client: TestClient):
    payload = {
        "request": "Refactor the task service for clarity",
        "repo": {"name": "parallel-backend", "open_files": ["main.py"]},
    }
    token = _make_pat(client, ["tasks:read", "chats:read"])
    resp = client.post(
        "/api/v1/workspaces/ws1/vscode/agent/plan",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
