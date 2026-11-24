"""Database engine, session factory, and dependency injection."""

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    """Enable foreign key constraints for SQLite connections.

    SQLite ignores foreign key constraints by default unless explicitly
    activated via 'PRAGMA foreign_keys=ON' for each connection.
    """
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_db_engine(database_url: str | None = None, echo: bool | None = None) -> Engine:
    """Create a configured SQLAlchemy engine supporting PostgreSQL (psycopg 3) and SQLite."""
    settings = get_settings()
    raw_url = database_url or settings.sync_database_url
    url = settings.normalize_db_url(raw_url)

    # Transparently route through local WebSocket bridge if outbound port 5432 is blocked locally
    from app.core.neon_bridge import resolve_database_url
    url = resolve_database_url(url)

    is_echo = echo if echo is not None else settings.DEBUG

    engine_kwargs: dict[str, Any] = {
        "echo": is_echo,
    }

    if url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # PostgreSQL / Neon configuration
        engine_kwargs["pool_pre_ping"] = settings.DB_POOL_PRE_PING
        engine_kwargs["pool_recycle"] = settings.DB_POOL_RECYCLE_SECONDS
        engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
        engine_kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
        engine_kwargs["pool_timeout"] = settings.DB_POOL_TIMEOUT_SECONDS

    return create_engine(url, **engine_kwargs)


# Central application engine and session factory
engine = create_db_engine()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding an isolated database session with auto-rollback on error."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
