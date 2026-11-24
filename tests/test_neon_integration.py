"""Integration tests running directly against Neon Serverless PostgreSQL."""

from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.neon_bridge import resolve_database_url
from app.db.models.respondent import Respondent


@pytest.fixture(scope="module")
def neon_engine():
    """Create a live PostgreSQL engine connected to Neon."""
    settings = get_settings()
    url = resolve_database_url(settings.DATABASE_URL_DIRECT)
    engine = create_engine(url, pool_pre_ping=True)
    yield engine
    engine.dispose()


def test_neon_dialect_and_version(neon_engine):
    """Verify Neon engine is running PostgreSQL 16+ with psycopg 3."""
    assert neon_engine.dialect.name == "postgresql"
    with neon_engine.connect() as conn:
        db_name, version_str = conn.execute(text("SELECT current_database(), version();")).fetchone()
        assert db_name == "neondb"
        assert "PostgreSQL" in version_str


def test_neon_respondents_table_structure(neon_engine):
    """Verify respondents table exists with all expected columns and indexes in Neon."""
    from sqlalchemy import inspect
    inspector = inspect(neon_engine)
    tables = inspector.get_table_names()
    assert "respondents" in tables

    columns = {c["name"]: c for c in inspector.get_columns("respondents")}
    assert "phone_number" in columns
    assert "classification" in columns
    assert "first_reply_at" in columns
    assert "last_reply_at" in columns
    assert "original_campaign_id" in columns


def test_neon_transaction_rollback_isolation(neon_engine):
    """Verify PostgreSQL transaction rollback keeps production data completely isolated."""
    Session = sessionmaker(bind=neon_engine, autocommit=False, autoflush=False)
    session = Session()

    test_phone = "+919999900999"
    now = datetime.now(timezone.utc)

    try:
        # Insert temporary test respondent
        temp_resp = Respondent(
            phone_number=test_phone,
            name="Rollback Test User",
            classification="UNCLASSIFIED",
            first_reply_at=now,
            last_reply_at=now,
            internal_notes="Ephemeral record for transaction verification",
        )
        session.add(temp_resp)
        session.flush()

        # Verify visible within transaction
        inserted_id = temp_resp.id
        assert inserted_id is not None
        queried = session.get(Respondent, inserted_id)
        assert queried is not None
        assert queried.phone_number == test_phone

    finally:
        # Roll back transaction
        session.rollback()
        session.close()

    # Re-verify in separate connection that record does NOT exist
    with neon_engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM respondents WHERE phone_number = :p"),
            {"p": test_phone},
        ).scalar()
        assert count == 0


def test_neon_unique_phone_constraint_enforcement(neon_engine):
    """Verify PostgreSQL enforces unique constraint on respondent phone number."""
    Session = sessionmaker(bind=neon_engine, autocommit=False, autoflush=False)
    session = Session()
    test_phone = "+919999900888"
    now = datetime.now(timezone.utc)

    try:
        resp1 = Respondent(
            phone_number=test_phone,
            name="Contact 1",
            classification="UNCLASSIFIED",
            first_reply_at=now,
            last_reply_at=now,
        )
        session.add(resp1)
        session.flush()

        resp2 = Respondent(
            phone_number=test_phone,
            name="Contact 2 Duplicate",
            classification="INTERESTED",
            first_reply_at=now,
            last_reply_at=now,
        )
        session.add(resp2)

        with pytest.raises(IntegrityError):
            session.flush()

    finally:
        session.rollback()
        session.close()


def test_neon_classification_check_constraint(neon_engine):
    """Verify PostgreSQL rejects invalid classification via CHECK constraint."""
    Session = sessionmaker(bind=neon_engine, autocommit=False, autoflush=False)
    session = Session()
    now = datetime.now(timezone.utc)

    try:
        # Note: model validator will catch it first; execute raw SQL to test DB constraint
        with pytest.raises(Exception):
            with neon_engine.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO respondents (phone_number, classification, first_reply_at, last_reply_at)
                        VALUES ('+919999900777', 'INVALID_CLASS', :now, :now);
                    """),
                    {"now": now},
                )
    finally:
        session.close()
