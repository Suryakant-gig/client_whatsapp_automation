"""Pytest configuration and test database fixtures."""

import os
from typing import Generator
import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from alembic.config import Config
from alembic import command
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db
from app.db.models.user import User
from app.api.deps import get_current_user, verify_csrf
from app.core.config import get_settings

# Enforce mock mode during test runs for safety and test stability
os.environ["WHATSAPP_ENABLED"] = "false"
get_settings.cache_clear()


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable foreign key constraints for SQLite connections during tests."""
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory) -> str:
    """Create a temporary path for the isolated test database."""
    temp_dir = tmp_path_factory.mktemp("test_db")
    db_file = os.path.join(temp_dir, "test_travel_agency.db")
    return db_file


@pytest.fixture(scope="session")
def test_db_url(test_db_path: str) -> str:
    """Construct SQLite connection URL for the temporary test database."""
    return f"sqlite:///{test_db_path}"


@pytest.fixture(scope="session")
def migrated_test_engine(test_db_url: str) -> Generator[Engine, None, None]:
    """Execute Alembic migrations on a fresh temporary SQLite database and yield engine."""
    # Run Alembic migrations against the temporary test database
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", test_db_url)

    # Run upgrade head to apply all migrations
    command.upgrade(alembic_cfg, "head")

    # Create test engine with foreign key enforcement
    engine = create_engine(
        test_db_url,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    yield engine

    engine.dispose()


@pytest.fixture
def db_session(migrated_test_engine: Engine) -> Generator[Session, None, None]:
    """Yield a database session wrapped in a transaction that rolls back after each test."""
    connection = migrated_test_engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(
        bind=connection,
        autocommit=False,
        autoflush=False,
    )
    session = session_factory()

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Provide a FastAPI test client with database and authentication dependency overrides for regression testing."""
    def override_get_db():
        yield db_session

    mock_admin = User(
        id=999,
        username="regression_admin",
        password_hash="mock_hash",
        role="admin",
        is_active=True,
    )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: mock_admin
    app.dependency_overrides[verify_csrf] = lambda: True

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(db_session: Session) -> Generator[TestClient, None, None]:
    """Provide a raw FastAPI test client without authentication overrides for auth security testing."""
    def override_get_db():
        yield db_session

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

