import os
import threading
from typing import Optional

import certifi
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection

_mongo_client: Optional[MongoClient] = None
_mongo_lock = threading.Lock()


def get_mongo_client() -> MongoClient:
    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri:
        raise RuntimeError("MONGODB_URI is required for demo MongoDB features.")

    global _mongo_client
    if _mongo_client is None:
        with _mongo_lock:
            if _mongo_client is None:
                _mongo_client = MongoClient(
                    uri,
                    serverSelectionTimeoutMS=5000,
                    tlsCAFile=certifi.where(),
                )
    return _mongo_client


def get_demo_db() -> Database:
    client = get_mongo_client()
    try:
        default_db = client.get_default_database()
        if default_db is not None:
            return default_db
    except Exception:
        pass
    return client["parallel_demo"]


def ping_demo_db() -> None:
    db = get_demo_db()
    db.command("ping")


def get_memory_collection() -> Collection:
    return get_demo_db()["memory_docs"]


def list_search_indexes() -> list[dict]:
    collection = get_memory_collection()
    return list(collection.list_search_indexes())
