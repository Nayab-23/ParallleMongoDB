import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Ensure .env is loaded (if it exists)
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    try:
        load_dotenv(dotenv_path=env_path)
    except Exception:
        pass  # Ignore if .env can't be read
else:
    load_dotenv()  # Try loading from default locations


def _as_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    database_url: str
    rag_enabled: bool
    openai_api_key: str
    env: str

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgres")

    @property
    def vector_supported(self) -> bool:
        return self.is_postgres and _as_bool(os.getenv("RAG_ENABLED"), False)


@lru_cache()
def _load_settings() -> Settings:
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        # Check for SQLite fallback mode (for local development)
        if _as_bool(os.getenv("ALLOW_SQLITE_FALLBACK"), False):
            db_url = "sqlite:///./parallel.db"
        else:
            raise RuntimeError("DATABASE_URL is required; set it to your Postgres connection string.")

    return Settings(
        database_url=db_url,
        rag_enabled=_as_bool(os.getenv("RAG_ENABLED"), False),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        env=os.getenv("PARALLEL_ENV", os.getenv("DEPLOYMENT_MODE", "development")),
    )


def get_settings(*, refresh: bool = False) -> Settings:
    """
    Cached settings loader. Use refresh=True in tests when you mutate env vars.
    """
    if refresh:
        _load_settings.cache_clear()
    return _load_settings()

