import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Load .env before reading environment variables (if it exists)
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    try:
        load_dotenv(dotenv_path=env_path)
    except Exception:
        pass  # Ignore if .env can't be read
else:
    load_dotenv()  # Try loading from default locations


def _resolve_database_url() -> str:
    """
    Postgres-first: require DATABASE_URL unless explicitly opting into SQLite for tests/dev.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    if "PYTEST_CURRENT_TEST" in os.environ:
        return "sqlite:///./test.db"

    if os.getenv("ALLOW_SQLITE_FALLBACK", "").lower() in {"1", "true", "yes", "on"}:
        return "sqlite:///./parallel.db"

    raise RuntimeError("DATABASE_URL is required (set ALLOW_SQLITE_FALLBACK=true to use local SQLite).")


DATABASE_URL = _resolve_database_url()

# Connection pool settings - critical for production performance
# Render free tier PostgreSQL max connections: ~20-25
# We use conservative settings to avoid exhausting the pool
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    pool_args = {}
else:
    # PostgreSQL connection pool configuration
    connect_args = {
        "connect_timeout": 10,  # 10 second connection timeout
        "options": "-c statement_timeout=30000"  # 30 second query timeout
    }
    pool_args = {
        "pool_size": 10,  # Maintain 10 persistent connections
        "max_overflow": 10,  # Allow 10 additional connections (20 total)
        "pool_timeout": 30,  # Wait up to 30s for available connection
        "pool_recycle": 3600,  # Recycle connections after 1 hour
        "pool_pre_ping": True,  # Verify connections before using (catches dead connections)
    }

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args=connect_args,
    **pool_args
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def get_db():
    """
    FastAPI dependency that yields a database session and ensures it is closed.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
