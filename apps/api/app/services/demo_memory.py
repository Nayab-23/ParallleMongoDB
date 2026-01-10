import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo.collection import Collection

from app.services.demo_embeddings import embed_texts
from app.services.demo_mongo import get_demo_db

VECTOR_INDEX_NAME = "memory_docs_embedding"


def _get_memory_collection() -> Collection:
    return get_demo_db()["memory_docs"]


def _get_trace_collection() -> Collection:
    return get_demo_db()["demo_traces"]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def chunk_text(text: str, *, max_chars: int = 800, overlap: int = 120) -> List[str]:
    cleaned = _normalize_text(text)
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    words = cleaned.split()
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for word in words:
        word_len = len(word) + (1 if current else 0)
        if current and current_len + word_len > max_chars:
            chunk = " ".join(current)
            chunks.append(chunk)

            if overlap > 0:
                overlap_words: List[str] = []
                overlap_len = 0
                for w in reversed(current):
                    overlap_len += len(w) + 1
                    overlap_words.append(w)
                    if overlap_len >= overlap:
                        break
                current = list(reversed(overlap_words))
                current_len = sum(len(w) + 1 for w in current) if current else 0
            else:
                current = []
                current_len = 0

        current.append(word)
        current_len += len(word) + 1

    if current:
        chunks.append(" ".join(current))
    return chunks


def inject_memory(
    agent_id: str,
    title: str,
    text: str,
    metadata: Optional[Dict[str, Any]] = None,
    *,
    max_chars: int = 800,
    overlap: int = 120,
) -> Tuple[List[str], int]:
    chunks = chunk_text(text, max_chars=max_chars, overlap=overlap)
    if not chunks:
        return [], 0

    embeddings, embed_model = embed_texts(chunks)
    if len(embeddings) != len(chunks):
        raise RuntimeError("Embedding count mismatch during memory injection.")

    now = datetime.now(timezone.utc)
    docs: List[Dict[str, Any]] = []
    for idx, (chunk, vector) in enumerate(zip(chunks, embeddings)):
        docs.append(
            {
                "_id": str(uuid.uuid4()),
                "agent_id": agent_id,
                "title": title,
                "text": chunk,
                "metadata": metadata or {},
                "embedding": vector,
                "chunk_index": idx,
                "chunk_count": len(chunks),
                "created_at": now,
                "embedding_provider": "voyage",
                "embedding_model": embed_model,
            }
        )

    collection = _get_memory_collection()
    collection.insert_many(docs)
    return [doc["_id"] for doc in docs], len(chunks)


def vector_search(
    target_agent_id: str,
    query_embedding: List[float],
    *,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    index_name = VECTOR_INDEX_NAME
    collection = _get_memory_collection()
    num_candidates = max(top_k * 10, 50)
    pipeline = [
        {
            "$vectorSearch": {
                "index": index_name,
                "path": "embedding",
                "queryVector": query_embedding,
                "numCandidates": num_candidates,
                "limit": top_k,
                "filter": {"agent_id": target_agent_id},
            }
        },
        {
            "$project": {
                "_id": 1,
                "agent_id": 1,
                "title": 1,
                "text": 1,
                "metadata": 1,
                "chunk_index": 1,
                "chunk_count": 1,
                "embedding_provider": 1,
                "embedding_model": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]
    return list(collection.aggregate(pipeline))


def store_trace(payload: Dict[str, Any]) -> str:
    trace_id = payload.get("trace_id") or str(uuid.uuid4())
    payload["trace_id"] = trace_id
    payload.setdefault("created_at", datetime.now(timezone.utc))
    _get_trace_collection().insert_one(payload)
    return trace_id


def get_trace(trace_id: str) -> Optional[Dict[str, Any]]:
    doc = _get_trace_collection().find_one({"trace_id": trace_id})
    if not doc:
        return None
    if isinstance(doc.get("created_at"), datetime):
        doc["created_at"] = doc["created_at"].isoformat()
    doc["_id"] = str(doc.get("_id")) if "_id" in doc else doc.get("_id")
    return doc


def embed_question(question: str) -> Tuple[List[float], str]:
    vectors, model = embed_texts([question])
    if not vectors:
        raise RuntimeError("Failed to generate embedding for question.")
    return vectors[0], model


def build_demo_answer_prompt(question: str, sources: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    lines = []
    for idx, src in enumerate(sources, start=1):
        text = src.get("text") or ""
        title = src.get("title") or "Untitled"
        lines.append(f"[{idx}] {title}: {text}")

    context_block = "\n".join(lines) if lines else "No sources available."

    system = (
        "You are an offline teammate proxy. Answer using ONLY the provided sources. "
        "Cite sources with [n] after each sentence. If the answer is not in the sources, say you do not know."
    )
    user = f"Question: {question}\n\nSources:\n{context_block}\n\nAnswer with citations."
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_trace_payload(
    *,
    trace_id: str,
    request: Dict[str, Any],
    answer: str,
    sources: List[Dict[str, Any]],
    embedding_model: str,
    llm_model: str,
    latency_ms: int,
) -> Dict[str, Any]:
    return {
        "trace_id": trace_id,
        "request": request,
        "answer": answer,
        "sources": sources,
        "embedding_provider": "voyage",
        "embedding_model": embedding_model,
        "llm_provider": "fireworks",
        "llm_model": llm_model,
        "latency_ms": latency_ms,
        "created_at": datetime.now(timezone.utc),
    }
