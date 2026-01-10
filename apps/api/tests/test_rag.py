import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["RAG_ENABLED"] = "false"

from app.core.settings import get_settings  # noqa: E402
from app.services.rag import get_relevant_context  # noqa: E402
from database import Base  # noqa: E402
from models import ChatInstance, DailyBrief, Message, Organization, Room, User  # noqa: E402


def setup_sqlite_session():
    get_settings(refresh=True)  # ensure SQLite/dev mode in settings cache
    engine = create_engine("sqlite:///:memory:", future=True)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            User.__table__,
            Room.__table__,
            ChatInstance.__table__,
            Message.__table__,
            DailyBrief.__table__,
        ],
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT,
                    room_id TEXT,
                    user_id TEXT,
                    content TEXT,
                    importance_score REAL,
                    embedding TEXT,
                    metadata_json TEXT,
                    created_at TEXT
                )
                """
            )
        )
    return TestingSession


def test_rag_scopes_to_room():
    Session = setup_sqlite_session()
    db = Session()
    try:
        room1 = Room(id="r1", org_id="org1", name="Room 1")
        room2 = Room(id="r2", org_id="org1", name="Room 2")
        chat1 = ChatInstance(id="c1", room_id="r1", name="chat1")
        chat2 = ChatInstance(id="c2", room_id="r2", name="chat2")
        db.add_all([room1, room2, chat1, chat2])
        db.commit()

        m1 = Message(
            id="m1",
            room_id="r1",
            chat_instance_id="c1",
            sender_id="u1",
            sender_name="U1",
            role="user",
            content="hello from room1",
            created_at=datetime.now(timezone.utc),
        )
        m2 = Message(
            id="m2",
            room_id="r2",
            chat_instance_id="c2",
            sender_id="u2",
            sender_name="U2",
            role="user",
            content="other room text",
            created_at=datetime.now(timezone.utc),
        )
        db.add_all([m1, m2])
        db.commit()

        ctx = get_relevant_context(db, query="hello", room_id="r1", user_id=None, limit=5)
        ids = {item.id for item in ctx}
        assert "m1" in ids
        assert "m2" not in ids
    finally:
        db.close()


def test_rag_returns_recent_when_embeddings_missing():
    Session = setup_sqlite_session()
    db = Session()
    try:
        room = Room(id="r3", org_id="org1", name="Room 3")
        chat = ChatInstance(id="c3", room_id="r3", name="chat3")
        db.add_all([room, chat])
        db.commit()

        msg = Message(
            id="m3",
            room_id="r3",
            chat_instance_id="c3",
            sender_id="u3",
            sender_name="U3",
            role="user",
            content="something unrelated",
            created_at=datetime.now(timezone.utc),
        )
        db.add(msg)
        db.commit()

        ctx = get_relevant_context(db, query="random text", room_id="r3", user_id=None, limit=3)
        assert any(item.id == "m3" for item in ctx)
    finally:
        db.close()
