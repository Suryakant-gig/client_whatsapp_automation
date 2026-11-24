"""Unit and integration tests for database models, constraints, and relationships."""

from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Campaign,
    CampaignBatch,
    CampaignRecipient,
    FollowUpSchedule,
    IncomingMessage,
    Lead,
    MessageLog,
    SyncLog,
    Template,
)


def test_database_connection(migrated_test_engine: Engine) -> None:
    """Verify that connection to the database succeeds."""
    with migrated_test_engine.connect() as connection:
        result = connection.execute(text("SELECT 1")).scalar()
        assert result == 1


def test_alembic_migration_tables_created(migrated_test_engine: Engine) -> None:
    """Verify that Alembic migration created all expected tables and indexes."""
    inspector = inspect(migrated_test_engine)
    tables = inspector.get_table_names()

    expected_tables = {
        "alembic_version",
        "leads",
        "follow_up_schedules",
        "campaigns",
        "campaign_batches",
        "campaign_recipients",
        "message_logs",
        "incoming_messages",
        "templates",
        "sync_logs",
    }
    assert expected_tables.issubset(set(tables)), f"Missing tables: {expected_tables - set(tables)}"


def test_lead_crud(db_session: Session) -> None:
    """Test full CRUD lifecycle for leads."""
    # Create
    lead = Lead(
        serial_number="LEAD-001",
        customer_name="Ramesh Sharma",
        phone_number="+919876543210",
        status="Pending",
    )
    db_session.add(lead)
    db_session.flush()

    assert lead.id is not None
    lead_id = lead.id

    # Retrieve
    retrieved = db_session.get(Lead, lead_id)
    assert retrieved is not None
    assert retrieved.customer_name == "Ramesh Sharma"
    assert retrieved.phone_number == "+919876543210"
    assert retrieved.status == "Pending"

    # Update
    retrieved.status = "Replied"
    retrieved.follow_up_paused = True
    db_session.flush()

    updated = db_session.get(Lead, lead_id)
    assert updated is not None
    assert updated.status == "Replied"
    assert updated.follow_up_paused is True

    # Delete
    db_session.delete(updated)
    db_session.flush()

    deleted = db_session.get(Lead, lead_id)
    assert deleted is None


def test_lead_status_validation(db_session: Session) -> None:
    """Verify valid statuses are accepted and invalid statuses (e.g., 'Interested') are rejected."""
    # Valid statuses: Pending, Replied, Not Interested, Interested
    for valid_status in ["Pending", "Replied", "Not Interested", "Interested"]:
        lead = Lead(
            customer_name=f"Customer {valid_status}",
            phone_number="+919999999999",
            status=valid_status,
        )
        db_session.add(lead)
        db_session.flush()
        assert lead.status == valid_status
        db_session.delete(lead)
        db_session.flush()

    # Disallowed status must be rejected
    with pytest.raises(ValueError, match="Invalid lead status 'InvalidStatus'"):
        Lead(
            customer_name="Invalid Lead",
            phone_number="+919999999999",
            status="InvalidStatus",
        )


def test_follow_up_pause_field_defaults(db_session: Session) -> None:
    """Verify follow_up_paused defaults to False."""
    lead = Lead(
        customer_name="Ananya Verma",
        phone_number="+919812345678",
    )
    db_session.add(lead)
    db_session.flush()

    assert lead.follow_up_paused is False


def test_multiple_follow_up_schedules_for_one_lead(db_session: Session) -> None:
    """Verify each customer can have multiple individual follow-up schedules."""
    lead = Lead(
        customer_name="Vikram Patel",
        phone_number="+919123456789",
    )
    db_session.add(lead)
    db_session.flush()

    now = datetime.now(timezone.utc)
    schedules = [
        FollowUpSchedule(
            lead_id=lead.id,
            sequence_number=1,
            scheduled_at=now + timedelta(days=1),
            status="Scheduled",
        ),
        FollowUpSchedule(
            lead_id=lead.id,
            sequence_number=2,
            scheduled_at=now + timedelta(days=3),
            status="Scheduled",
        ),
        FollowUpSchedule(
            lead_id=lead.id,
            sequence_number=3,
            scheduled_at=now + timedelta(days=7),
            status="Scheduled",
        ),
    ]
    db_session.add_all(schedules)
    db_session.flush()

    # Re-query lead and inspect relationship
    retrieved_lead = db_session.get(Lead, lead.id)
    assert retrieved_lead is not None
    assert len(retrieved_lead.follow_up_schedules) == 3
    seq_numbers = [s.sequence_number for s in retrieved_lead.follow_up_schedules]
    assert seq_numbers == [1, 2, 3]


def test_campaign_to_batch_relationships(db_session: Session) -> None:
    """Verify a campaign can contain multiple batches with back-reference."""
    campaign = Campaign(
        campaign_name="Diwali Goa Packages 2026",
        status="Scheduled",
    )
    db_session.add(campaign)
    db_session.flush()

    batch_1 = CampaignBatch(
        campaign_id=campaign.id,
        batch_number=1,
        batch_size=50,
        approval_status="Approved",
    )
    batch_2 = CampaignBatch(
        campaign_id=campaign.id,
        batch_number=2,
        batch_size=45,
        approval_status="Pending",
    )
    db_session.add_all([batch_1, batch_2])
    db_session.flush()

    retrieved_campaign = db_session.get(Campaign, campaign.id)
    assert retrieved_campaign is not None
    assert len(retrieved_campaign.batches) == 2
    assert retrieved_campaign.batches[0].batch_number == 1
    assert retrieved_campaign.batches[0].campaign.campaign_name == "Diwali Goa Packages 2026"


def test_maximum_batch_size_validation(db_session: Session) -> None:
    """Verify batch size validation enforces maximum of 50 recipients."""
    campaign = Campaign(campaign_name="Summer Dubai Promotion")
    db_session.add(campaign)
    db_session.flush()

    # Valid batch size (50)
    batch_valid = CampaignBatch(
        campaign_id=campaign.id,
        batch_number=1,
        batch_size=50,
    )
    db_session.add(batch_valid)
    db_session.flush()
    assert batch_valid.batch_size == 50

    # Invalid batch size (> 50) rejected by validator
    with pytest.raises(ValueError, match="Batch size must be between 1 and 50 recipients"):
        CampaignBatch(
            campaign_id=campaign.id,
            batch_number=2,
            batch_size=51,
        )

    # Invalid batch size (<= 0) rejected by validator
    with pytest.raises(ValueError, match="Batch size must be between 1 and 50 recipients"):
        CampaignBatch(
            campaign_id=campaign.id,
            batch_number=3,
            batch_size=0,
        )


def test_duplicate_recipient_prevention_within_batch(db_session: Session) -> None:
    """Verify duplicate recipients within the same batch are prevented."""
    campaign = Campaign(campaign_name="Kerala Monsoon Special")
    db_session.add(campaign)
    db_session.flush()

    batch = CampaignBatch(
        campaign_id=campaign.id,
        batch_number=1,
        batch_size=20,
    )
    lead = Lead(
        customer_name="Pooja Nair",
        phone_number="+919870001122",
    )
    db_session.add_all([batch, lead])
    db_session.flush()

    recipient_1 = CampaignRecipient(
        batch_id=batch.id,
        lead_id=lead.id,
        send_status="Pending",
    )
    db_session.add(recipient_1)
    db_session.flush()

    # Attempt to add the exact same lead to the same batch
    recipient_2 = CampaignRecipient(
        batch_id=batch.id,
        lead_id=lead.id,
        send_status="Pending",
    )
    db_session.add(recipient_2)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_duplicate_whatsapp_message_id_prevention(db_session: Session) -> None:
    """Verify duplicate incoming WhatsApp message IDs are rejected."""
    now = datetime.now(timezone.utc)
    msg1 = IncomingMessage(
        whatsapp_message_id="wamid.HBgLMzkxOTg3NjU0MzIx",
        sender_phone="+919876543210",
        message_text="Hello, I want details about Ladakh tour",
        received_at=now,
    )
    db_session.add(msg1)
    db_session.flush()

    # Duplicate incoming message with identical whatsapp_message_id
    msg2 = IncomingMessage(
        whatsapp_message_id="wamid.HBgLMzkxOTg3NjU0MzIx",
        sender_phone="+919876543210",
        message_text="Duplicate webhook delivery",
        received_at=now,
    )
    db_session.add(msg2)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_duplicate_message_log_whatsapp_id_prevention(db_session: Session) -> None:
    """Verify duplicate whatsapp_message_id in outbound message_logs is rejected."""
    lead = Lead(customer_name="Aditi Rao", phone_number="+919876543299")
    db_session.add(lead)
    db_session.flush()

    log1 = MessageLog(
        lead_id=lead.id,
        message_type="follow_up",
        whatsapp_message_id="wamid.OUTBOUND.12345",
        delivery_status="Sent",
    )
    db_session.add(log1)
    db_session.flush()

    # Attempt to insert second message log with the identical whatsapp_message_id
    log2 = MessageLog(
        lead_id=lead.id,
        message_type="follow_up",
        whatsapp_message_id="wamid.OUTBOUND.12345",
        delivery_status="Sent",
    )
    db_session.add(log2)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_foreign_key_enforcement(db_session: Session) -> None:
    """Verify SQLite foreign key enforcement rejects orphaned child records."""
    now = datetime.now(timezone.utc)
    non_existent_lead_id = 999999

    # Attempt to insert follow-up schedule referencing a non-existent lead
    orphan_schedule = FollowUpSchedule(
        lead_id=non_existent_lead_id,
        sequence_number=1,
        scheduled_at=now,
        status="Scheduled",
    )
    db_session.add(orphan_schedule)

    with pytest.raises(IntegrityError):
        db_session.flush()
