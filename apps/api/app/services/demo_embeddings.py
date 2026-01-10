import os
from typing import List, Tuple

import httpx


def _truncate_text(text: str, limit: int = 8000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


_VOYAGE_DIMENSIONS = {
    "voyage-3": 1024,
    "voyage-3-lite": 512,
    "voyage-2": 1024,
    "voyage-2-lite": 512,
    "voyage-large-2": 1536,
    "voyage-code-2": 1536,
}


def get_expected_dimension(model: str) -> int | None:
    return _VOYAGE_DIMENSIONS.get(model)


def embed_texts(texts: List[str]) -> Tuple[List[List[float]], str]:
    if not texts:
        return [], ""

    api_key = os.getenv("VOYAGE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("VOYAGE_API_KEY is required for Voyage embeddings.")
    model = os.getenv("VOYAGE_MODEL", "").strip()
    if not model:
        raise RuntimeError("VOYAGE_MODEL is required for Voyage embeddings.")
    payload = {
        "model": model,
        "input": [_truncate_text(text) for text in texts],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = httpx.post(
        "https://api.voyageai.com/v1/embeddings",
        json=payload,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    embeddings = [item["embedding"] for item in data.get("data", [])]
    if len(embeddings) != len(texts):
        raise RuntimeError("Voyage embeddings response length mismatch.")
    return embeddings, model
