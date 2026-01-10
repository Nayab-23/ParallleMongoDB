import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from openai import OpenAI
from pydantic import BaseModel, Field
from pymongo import MongoClient
from pymongo.collection import Collection
from dotenv import load_dotenv
from starlette.middleware.base import BaseHTTPMiddleware

from logutil import log_event, log_error, create_error_response, get_client_ip

# Load .env from the same directory as this file (if it exists)
env_path = Path(__file__).with_name(".env")
if env_path.exists():
    try:
        load_dotenv(dotenv_path=env_path)
    except Exception:
        pass  # Ignore if .env can't be read
else:
    load_dotenv()  # Try loading from default locations


@dataclass(frozen=True)
class HackConfig:
    fireworks_api_key: str
    fireworks_base_url: str
    fireworks_model: str
    voyage_api_key: str
    voyage_model: str
    mongodb_uri: str
    mongodb_db: Optional[str]
    mongodb_vector_index: str


def _load_config() -> HackConfig:
    required = [
        "FIREWORKS_API_KEY",
        "FIREWORKS_BASE_URL",
        "FIREWORKS_MODEL",
        "VOYAGE_API_KEY",
        "VOYAGE_MODEL",
        "MONGODB_URI",
    ]
    missing = [key for key in required if not os.getenv(key, "").strip()]
    if missing:
        raise RuntimeError(
            "Missing required env vars for hackathon runtime: "
            + ", ".join(missing)
        )

    return HackConfig(
        fireworks_api_key=os.getenv("FIREWORKS_API_KEY", "").strip(),
        fireworks_base_url=os.getenv("FIREWORKS_BASE_URL", "").strip(),
        fireworks_model=os.getenv("FIREWORKS_MODEL", "").strip(),
        voyage_api_key=os.getenv("VOYAGE_API_KEY", "").strip(),
        voyage_model=os.getenv("VOYAGE_MODEL", "").strip(),
        mongodb_uri=os.getenv("MONGODB_URI", "").strip(),
        mongodb_db=os.getenv("MONGODB_DB", "").strip() or None,
        mongodb_vector_index=os.getenv("MONGODB_VECTOR_INDEX", "memory_docs_embedding").strip(),
    )


CONFIG = _load_config()

_fireworks_client = OpenAI(
    api_key=CONFIG.fireworks_api_key,
    base_url=CONFIG.fireworks_base_url,
)

_mongo_client: Optional[MongoClient] = None
_mongo_lock = threading.Lock()


def _get_mongo_client() -> MongoClient:
    global _mongo_client
    if _mongo_client is None:
        with _mongo_lock:
            if _mongo_client is None:
                try:
                    log_event("MONGO_CONNECT", method="connect", uri_host=CONFIG.mongodb_uri.split("@")[-1].split("/")[0] if "@" in CONFIG.mongodb_uri else "localhost")
                    _mongo_client = MongoClient(CONFIG.mongodb_uri, serverSelectionTimeoutMS=5000)
                    # Test connection
                    _mongo_client.admin.command("ping")
                    log_event("MONGO_CONNECT_SUCCESS", method="ping")
                except Exception as exc:
                    log_error("MONGO_CONNECT", exc, method="connect")
                    raise
    return _mongo_client


def _get_demo_db():
    client = _get_mongo_client()
    if CONFIG.mongodb_db:
        return client[CONFIG.mongodb_db]
    try:
        default_db = client.get_default_database()
        if default_db is not None:
            return default_db
    except Exception:
        pass
    return client["parallel_demo"]


def _memory_collection() -> Collection:
    return _get_demo_db()["memory_docs"]


def _trace_collection() -> Collection:
    return _get_demo_db()["demo_traces"]


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


def _truncate_text(text: str, limit: int = 8000) -> str:
    return text if len(text) <= limit else text[:limit]


def _embed_voyage(texts: List[str]) -> List[List[float]]:
    payload = {
        "model": CONFIG.voyage_model,
        "input": [_truncate_text(text) for text in texts],
    }
    headers = {
        "Authorization": f"Bearer {CONFIG.voyage_api_key}",
        "Content-Type": "application/json",
    }

    try:
        log_event("VOYAGE_EMBED", method="embed", model=CONFIG.voyage_model, num_texts=len(texts))
        response = httpx.post(
            "https://api.voyageai.com/v1/embeddings",
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        embeddings = [item["embedding"] for item in data.get("data", [])]
        if len(embeddings) != len(texts):
            raise RuntimeError("Voyage embeddings response length mismatch.")
        log_event("VOYAGE_EMBED_SUCCESS", model=CONFIG.voyage_model, num_embeddings=len(embeddings))
        return embeddings
    except Exception as exc:
        log_error("VOYAGE_EMBED", exc, model=CONFIG.voyage_model, num_texts=len(texts))
        raise


def embed_texts(texts: List[str]) -> Tuple[List[List[float]], str, str]:
    if not texts:
        return [], CONFIG.voyage_model, "voyage"
    vectors = _embed_voyage(texts)
    return vectors, CONFIG.voyage_model, "voyage"


def embed_question(question: str) -> Tuple[List[float], str, str]:
    vectors, model, provider = embed_texts([question])
    if not vectors:
        raise RuntimeError("Failed to generate embedding for question.")
    return vectors[0], model, provider


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

    embeddings, embed_model, embed_provider = embed_texts(chunks)
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
                "embedding_provider": embed_provider,
                "embedding_model": embed_model,
            }
        )

    collection = _memory_collection()
    collection.insert_many(docs)
    return [doc["_id"] for doc in docs], len(chunks)


def vector_search(
    target_agent_id: str,
    query_embedding: List[float],
    *,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    try:
        log_event("VECTOR_SEARCH", agent_id=target_agent_id, top_k=top_k, index=CONFIG.mongodb_vector_index)
        collection = _memory_collection()
        num_candidates = max(top_k * 10, 50)
        pipeline = [
            {
                "$vectorSearch": {
                    "index": CONFIG.mongodb_vector_index,
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
        results = list(collection.aggregate(pipeline))
        log_event("VECTOR_SEARCH_SUCCESS", agent_id=target_agent_id, num_results=len(results))
        return results
    except Exception as exc:
        log_error("VECTOR_SEARCH", exc, agent_id=target_agent_id, top_k=top_k)
        raise


def store_trace(payload: Dict[str, Any]) -> str:
    trace_id = payload.get("trace_id") or str(uuid.uuid4())
    payload["trace_id"] = trace_id
    payload.setdefault("created_at", datetime.now(timezone.utc))
    _trace_collection().insert_one(payload)
    return trace_id


def get_trace(trace_id: str) -> Optional[Dict[str, Any]]:
    doc = _trace_collection().find_one({"trace_id": trace_id})
    if not doc:
        return None
    if isinstance(doc.get("created_at"), datetime):
        doc["created_at"] = doc["created_at"].isoformat()
    doc["_id"] = str(doc.get("_id")) if "_id" in doc else doc.get("_id")
    return doc


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
    embedding_provider: str,
    embedding_model: str,
    llm_provider: str,
    llm_model: str,
    latency_ms: int,
) -> Dict[str, Any]:
    return {
        "trace_id": trace_id,
        "request": request,
        "answer": answer,
        "sources": sources,
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "latency_ms": latency_ms,
        "created_at": datetime.now(timezone.utc),
    }


class DemoInjectRequest(BaseModel):
    agent_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    metadata: Optional[Dict[str, Any]] = None


class DemoInjectResponse(BaseModel):
    inserted: int
    chunks: int
    doc_ids: List[str]


class DemoAskRequest(BaseModel):
    target_agent_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    top_k: Optional[int] = Field(5, ge=1, le=50)


class DemoSource(BaseModel):
    doc_id: str
    title: str
    snippet: str
    score: float
    metadata: Dict[str, Any]


class DemoAskResponse(BaseModel):
    answer: str
    sources: List[DemoSource]
    trace_id: str


# ============================================
# REQUEST LOGGING MIDDLEWARE
# ============================================

class RequestLoggerMiddleware(BaseHTTPMiddleware):
    """Logs all requests with request_id, timing, and error handling"""

    async def dispatch(self, request: Request, call_next):
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Extract client info
        client_ip = get_client_ip(request)
        method = request.method
        path = request.url.path

        # Log request start
        start_time = time.time()
        log_event(
            "REQUEST_START",
            request_id=request_id,
            method=method,
            path=path,
            client_ip=client_ip,
        )

        try:
            # Process request
            response = await call_next(request)

            # Log request end
            duration_ms = int((time.time() - start_time) * 1000)
            log_event(
                "REQUEST_END",
                request_id=request_id,
                method=method,
                path=path,
                status=response.status_code,
                duration_ms=duration_ms,
                client_ip=client_ip,
            )

            # Add request ID to response headers
            response.headers["X-Request-Id"] = request_id
            return response

        except Exception as exc:
            # Log uncaught exception with full stacktrace
            duration_ms = int((time.time() - start_time) * 1000)
            log_error(
                "INTERNAL_ERROR",
                exc,
                request_id=request_id,
                method=method,
                path=path,
                duration_ms=duration_ms,
                client_ip=client_ip,
            )

            # Return standardized error response
            return create_error_response(
                status_code=500,
                error_code="INTERNAL_ERROR",
                message=f"An unexpected error occurred: {str(exc)}",
                request_id=request_id,
            )


app = FastAPI()

# Register request logging middleware
app.add_middleware(RequestLoggerMiddleware)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/llm_health")
def llm_health():
    try:
        log_event("FIREWORKS_CHAT", model=CONFIG.fireworks_model, purpose="health_check")
        response = _fireworks_client.chat.completions.create(
            model=CONFIG.fireworks_model,
            messages=[
                {"role": "system", "content": "You are a health check responder."},
                {"role": "user", "content": "Reply with a single word: ok"},
            ],
            max_tokens=5,
            temperature=0,
        )
        sample = response.choices[0].message.content.strip() if response.choices else ""
        log_event("FIREWORKS_CHAT_SUCCESS", model=CONFIG.fireworks_model, sample_length=len(sample))
        return {
            "provider": "fireworks",
            "model": CONFIG.fireworks_model,
            "ok": True,
            "sample": sample,
        }
    except Exception as exc:
        log_error("FIREWORKS_CHAT", exc, model=CONFIG.fireworks_model, purpose="health_check")
        raise HTTPException(status_code=500, detail=f"LLM health check failed: {exc}")


@app.get("/api/demo/health")
def demo_health():
    try:
        _get_mongo_client().admin.command("ping")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"MongoDB unavailable: {exc}")
    return {"ok": True, "mongodb": "ok"}


@app.post("/api/demo/inject_memory", response_model=DemoInjectResponse)
def demo_inject_memory(payload: DemoInjectRequest) -> DemoInjectResponse:
    try:
        doc_ids, chunk_count = inject_memory(
            agent_id=payload.agent_id,
            title=payload.title,
            text=payload.text,
            metadata=payload.metadata,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to inject memory: {exc}")

    return DemoInjectResponse(
        inserted=len(doc_ids),
        chunks=chunk_count,
        doc_ids=doc_ids,
    )


@app.post("/api/demo/ask", response_model=DemoAskResponse)
def demo_ask(payload: DemoAskRequest) -> DemoAskResponse:
    top_k = payload.top_k or 5
    start = time.time()

    try:
        query_vector, embed_model, embed_provider = embed_question(payload.question)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to embed question: {exc}")

    try:
        results = vector_search(payload.target_agent_id, query_vector, top_k=top_k)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Vector search failed: {exc}")

    response_sources: List[DemoSource] = []
    trace_sources: List[Dict[str, Any]] = []
    for doc in results:
        text = doc.get("text") or ""
        snippet = text[:240] + ("..." if len(text) > 240 else "")
        source_payload = {
            "doc_id": str(doc.get("_id")),
            "title": doc.get("title") or "Untitled",
            "snippet": snippet,
            "score": float(doc.get("score") or 0.0),
            "metadata": doc.get("metadata") or {},
        }
        response_sources.append(DemoSource(**source_payload))
        trace_sources.append(
            {
                **source_payload,
                "text": text,
                "chunk_index": doc.get("chunk_index"),
                "chunk_count": doc.get("chunk_count"),
            }
        )

    messages = build_demo_answer_prompt(
        question=payload.question,
        sources=trace_sources,
    )

    try:
        log_event("FIREWORKS_CHAT", model=CONFIG.fireworks_model, purpose="demo_ask", num_sources=len(trace_sources))
        response = _fireworks_client.chat.completions.create(
            model=CONFIG.fireworks_model,
            messages=messages,
            temperature=0.2,
            max_tokens=700,
        )
        answer = response.choices[0].message.content.strip() if response.choices else ""
        log_event("FIREWORKS_CHAT_SUCCESS", model=CONFIG.fireworks_model, answer_length=len(answer))
    except RuntimeError as exc:
        log_error("FIREWORKS_CHAT", exc, model=CONFIG.fireworks_model, purpose="demo_ask")
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        log_error("FIREWORKS_CHAT", exc, model=CONFIG.fireworks_model, purpose="demo_ask")
        raise HTTPException(status_code=500, detail=f"LLM synthesis failed: {exc}")

    latency_ms = int((time.time() - start) * 1000)
    trace_id = str(uuid.uuid4())
    trace_id = store_trace(
        build_trace_payload(
            trace_id=trace_id,
            request={
                "target_agent_id": payload.target_agent_id,
                "question": payload.question,
                "top_k": top_k,
            },
            answer=answer,
            sources=trace_sources,
            embedding_provider=embed_provider,
            embedding_model=embed_model,
            llm_provider="fireworks",
            llm_model=CONFIG.fireworks_model,
            latency_ms=latency_ms,
        )
    )

    return DemoAskResponse(answer=answer, sources=response_sources, trace_id=trace_id)


@app.get("/api/demo/trace/{trace_id}")
def demo_get_trace(trace_id: str):
    try:
        trace = get_trace(trace_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Trace lookup failed: {exc}")
    if not trace:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


# ============================================
# INCLUDE WEB ↔ EXTENSION API
# ============================================

from hack_api import router as hack_api_router
app.include_router(hack_api_router)
