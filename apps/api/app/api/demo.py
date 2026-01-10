import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.demo_memory import (
    build_demo_answer_prompt,
    build_trace_payload,
    embed_question,
    get_trace,
    inject_memory,
    store_trace,
    vector_search,
    VECTOR_INDEX_NAME,
)
from app.services.demo_embeddings import embed_texts, get_expected_dimension
from app.services.demo_llm import chat_completion, get_fireworks_model
from app.services.demo_mongo import get_memory_collection, list_search_indexes, ping_demo_db

router = APIRouter(prefix="/demo", tags=["demo"])


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


class DemoHealthResponse(BaseModel):
    ok: bool
    mongo: Dict[str, Any]
    vector_index: Dict[str, Any]
    voyage: Dict[str, Any]
    fireworks: Dict[str, Any]


@router.post("/inject_memory", response_model=DemoInjectResponse)
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


@router.post("/ask", response_model=DemoAskResponse)
def demo_ask(payload: DemoAskRequest) -> DemoAskResponse:
    top_k = payload.top_k or 5
    start = time.time()

    try:
        query_vector, embed_model = embed_question(payload.question)
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
        answer = chat_completion(messages, temperature=0.2, max_tokens=700)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
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
            embedding_model=embed_model,
            llm_model=get_fireworks_model(),
            latency_ms=latency_ms,
        )
    )

    return DemoAskResponse(answer=answer, sources=response_sources, trace_id=trace_id)


@router.get("/trace/{trace_id}")
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


@router.get("/health", response_model=DemoHealthResponse)
def demo_health() -> DemoHealthResponse:
    overall_ok = True
    mongo_status: Dict[str, Any] = {"ok": False}
    vector_status: Dict[str, Any] = {"ok": False}
    voyage_status: Dict[str, Any] = {"ok": False}
    fireworks_status: Dict[str, Any] = {"ok": False}

    # MongoDB Atlas connectivity
    try:
        ping_demo_db()
        mongo_status.update({"ok": True})
    except Exception as exc:
        overall_ok = False
        mongo_status.update({"ok": False, "error": str(exc)})

    # Voyage embeddings
    voyage_embedding: List[float] = []
    expected_dim: int | None = None
    try:
        embeddings, model = embed_texts(["health check"])
        voyage_embedding = embeddings[0] if embeddings else []
        dim = len(voyage_embedding)
        expected_dim = get_expected_dimension(model) or dim
        dim_ok = dim == expected_dim and dim > 0
        voyage_status.update(
            {
                "ok": dim_ok,
                "model": model,
                "dimensions": dim,
                "expected_dimensions": expected_dim,
            }
        )
        if not dim_ok:
            overall_ok = False
    except Exception as exc:
        overall_ok = False
        voyage_status.update({"ok": False, "error": str(exc)})

    # Vector search index
    index_name = VECTOR_INDEX_NAME
    vector_status.update({"index": index_name})
    try:
        indexes = list_search_indexes()
        index_info = next((idx for idx in indexes if idx.get("name") == index_name), None)
        if not index_info:
            overall_ok = False
            vector_status.update(
                {
                    "ok": False,
                    "error": "Vector search index not found.",
                    "instructions": (
                        "Create Atlas Vector Search index named 'memory_docs_embedding' on collection "
                        f"'memory_docs' with path 'embedding', numDimensions={expected_dim or 'UNKNOWN'}, "
                        "and cosine similarity."
                    ),
                }
            )
        else:
            status = index_info.get("status")
            if status and status.upper() != "READY":
                overall_ok = False
                vector_status.update({"ok": False, "status": status})
            else:
                if voyage_embedding:
                    collection = get_memory_collection()
                    try:
                        list(
                            collection.aggregate(
                                [
                                    {
                                        "$vectorSearch": {
                                            "index": index_name,
                                            "path": "embedding",
                                            "queryVector": voyage_embedding,
                                            "numCandidates": 10,
                                            "limit": 1,
                                            "filter": {"agent_id": "__healthcheck__"},
                                        }
                                    },
                                    {"$limit": 1},
                                ]
                            )
                        )
                        vector_status.update({"ok": True})
                    except Exception as exc:
                        overall_ok = False
                        vector_status.update({"ok": False, "error": str(exc)})
                else:
                    overall_ok = False
                    vector_status.update({"ok": False, "error": "Voyage embeddings unavailable for vector test."})
    except Exception as exc:
        overall_ok = False
        vector_status.update({"ok": False, "error": str(exc)})

    # Fireworks chat
    try:
        model = get_fireworks_model()
        response = chat_completion(
            [{"role": "user", "content": "health check"}],
            model=model,
            temperature=0.0,
            max_tokens=5,
        )
        fireworks_status.update({"ok": bool(response.strip()), "model": model})
        if not response.strip():
            overall_ok = False
            fireworks_status.update({"ok": False, "error": "Empty response from Fireworks."})
    except Exception as exc:
        overall_ok = False
        fireworks_status.update({"ok": False, "error": str(exc)})

    return DemoHealthResponse(
        ok=overall_ok,
        mongo=mongo_status,
        vector_index=vector_status,
        voyage=voyage_status,
        fireworks=fireworks_status,
    )
