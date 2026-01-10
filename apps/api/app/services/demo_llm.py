import os
from typing import List, Dict

from openai import OpenAI

_fireworks_client: OpenAI | None = None


def get_fireworks_model() -> str:
    model = os.getenv("FIREWORKS_MODEL", "").strip()
    if not model:
        raise RuntimeError("FIREWORKS_MODEL is required for demo chat.")
    return model


def get_fireworks_client() -> OpenAI:
    api_key = os.getenv("FIREWORKS_API_KEY", "").strip()
    base_url = os.getenv("FIREWORKS_BASE_URL", "").strip()
    if not api_key:
        raise RuntimeError("FIREWORKS_API_KEY is required for demo chat.")
    if not base_url:
        raise RuntimeError("FIREWORKS_BASE_URL is required for demo chat.")

    global _fireworks_client
    if _fireworks_client is None:
        _fireworks_client = OpenAI(api_key=api_key, base_url=base_url)
    return _fireworks_client


def chat_completion(
    messages: List[Dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 700,
) -> str:
    client = get_fireworks_client()
    model_name = model or get_fireworks_model()
    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content or ""
