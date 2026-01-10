import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from config import openai_client
from models import CodeIndexEntry

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_CHARS = 1400
DEFAULT_MAX_CHUNKS = 120


def _chunk_lines(
    content: str,
    *,
    max_chars: int = DEFAULT_CHUNK_CHARS,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    overlap_lines: int = 3,
) -> List[Tuple[str, Dict[str, Any]]]:
    lines = content.splitlines()
    chunks: List[Tuple[str, Dict[str, Any]]] = []
    idx = 0
    total = len(lines)
    while idx < total and len(chunks) < max_chunks:
        char_count = 0
        start = idx
        end = idx
        while end < total:
            line = lines[end]
            next_count = char_count + len(line) + 1
            if char_count and next_count > max_chars:
                break
            char_count = next_count
            end += 1
        if end == start:
            end = min(total, start + 1)
        chunk_lines = lines[start:end]
        text_block = "\n".join(chunk_lines)
        chunks.append(
            (
                text_block,
                {
                    "start_line": start + 1,
                    "end_line": end,
                    "total_lines": total,
                },
            )
        )
        if end >= total:
            break
        idx = max(end - overlap_lines, end)
    return chunks


def _generate_embedding(content: str) -> List[float]:
    if openai_client is None:
        raise RuntimeError("OpenAI client not configured; cannot generate embeddings")
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=content[:8000],
    )
    return response.data[0].embedding


def index_codebase(
    db: Session,
    *,
    workspace_id: str,
    files: Iterable[Dict[str, Any]],
    max_chars: int = DEFAULT_CHUNK_CHARS,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
) -> int:
    settings = get_settings()
    if not (settings.rag_enabled and settings.is_postgres and openai_client):
        logger.info("[CodeIndex] Skipped indexing; embeddings not available")
        return 0

    file_list = list(files)
    if not file_list:
        return 0
    paths = [f.get("path") for f in file_list if f.get("path")]
    if paths:
        db.query(CodeIndexEntry).filter(
            CodeIndexEntry.workspace_id == workspace_id,
            CodeIndexEntry.file_path.in_(paths),
        ).delete(synchronize_session=False)
        db.commit()

    total_added = 0
    now = datetime.now(timezone.utc)
    for file_entry in file_list:
        content = file_entry.get("content") or ""
        file_path = file_entry.get("path") or ""
        if not content.strip() or not file_path:
            continue
        language = file_entry.get("language")
        symbol = file_entry.get("symbol")
        for chunk_index, (chunk_text, metadata) in enumerate(
            _chunk_lines(content, max_chars=max_chars, max_chunks=max_chunks)
        ):
            try:
                embedding = _generate_embedding(chunk_text)
            except Exception:
                logger.exception("[CodeIndex] Embedding failed for %s", file_path)
                continue
            entry = CodeIndexEntry(
                id=str(uuid4()),
                workspace_id=workspace_id,
                file_path=file_path,
                language=language,
                symbol=symbol,
                chunk_index=chunk_index,
                content=chunk_text,
                metadata_json=metadata,
                embedding=embedding,
                created_at=now,
                updated_at=now,
            )
            db.add(entry)
            total_added += 1
        db.commit()
    return total_added


def search_code_index(
    db: Session,
    *,
    workspace_id: str,
    query: str,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    settings = get_settings()
    if not (settings.rag_enabled and settings.is_postgres and openai_client):
        return []
    if not query:
        return []
    try:
        embedding = _generate_embedding(query)
    except Exception:
        logger.exception("[CodeIndex] Embedding failed for query")
        return []

    embedding_str = "[" + ",".join(map(str, embedding)) + "]"
    sql = text(
        """
        SELECT id,
               file_path,
               content,
               metadata,
               1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity
        FROM code_index_entries
        WHERE workspace_id = :workspace_id
          AND embedding IS NOT NULL
        ORDER BY similarity DESC
        LIMIT :limit
        """
    )
    rows = db.execute(
        sql,
        {
            "query_embedding": embedding_str,
            "workspace_id": workspace_id,
            "limit": limit,
        },
    ).fetchall()
    results: List[Dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "id": row[0],
                "file_path": row[1],
                "content": row[2],
                "metadata": row[3],
                "score": float(row[4] or 0.0),
            }
        )
    return results


def uuid4() -> str:
    import uuid

    return str(uuid.uuid4())
