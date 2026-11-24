"""Tests for Respondent management, automatic webhook persistence, manual classification, and immediate manual contact."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.campaign import Campaign, CampaignBatch, CampaignRecipient
from app.db.models.lead import Lead
from app.db.models.message import IncomingMessage, MessageLog
from app.db.models.respondent import Respondent
from app.db.models.template import Template
from app.services.scheduler_manager import get_scheduler_manager
from app.services.webhook_service import WebhookService


def test_app_startup_without_scheduler() -> None:
    """Verify application runs with APScheduler completely decommissioned."""
    mgr = get_scheduler_manager()
    assert mgr.is_running is False
    # Calling start should not crash or start anything
    mgr.start()
    assert mgr.is_running is False


def test_webhook_creates_unclassified_respondent(client: TestClient, db_session: Session) -> None:
    """Verify inbound WhatsApp message automatically creates a Respondent with UNCLASSIFIED classification."""
    # Create matching lead with verified opt-in
    lead = Lead(
        customer_name="Sunil Sharma",
        phone_number="+919876500001",
        opt_in_status="OPTED_IN",
        status="Pending",
        follow_up_paused=False,
    )
    db_session.add(lead)
    db_session.flush()

    message_data = {
        "id": "wamid.INBOUND.TEST.001",
        "from": "919876500001",
        "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        "type": "text",
        "text": {"body": "Hi, I want details about your Bali package."},
    }

    result = WebhookService.process_incoming_message(db_session, message_data, profile_name="Sunil Sharma")
    db_session.flush()

    assert result is not None
    assert result.whatsapp_message_id == "wamid.INBOUND.TEST.001"

    # Query respondents table
    respondent = db_session.scalar(
        select(Respondent).where(Respondent.phone_number == "+919876500001")
    )
    assert respondent is not None
    assert respondent.lead_id == lead.id
    assert respondent.name == "Sunil Sharma"
    # CRITICAL: Must be UNCLASSIFIED, NEVER automatically INTERESTED
    assert respondent.classification == "UNCLASSIFIED"
    assert respondent.first_reply_at is not None
    assert respondent.last_reply_at is not None


def test_webhook_deduplication_updates_existing_respondent(client: TestClient, db_session: Session) -> None:
    """Verify second inbound message updates existing respondent rather than creating a duplicate."""
    phone = "+919876500002"
    first_time = datetime.now(timezone.utc) - timedelta(hours=2)

    initial_resp = Respondent(
        phone_number=phone,
        name="Pooja Rao",
        classification="UNCLASSIFIED",
        first_reply_at=first_time,
        last_reply_at=first_time,
    )
    db_session.add(initial_resp)
    db_session.flush()

    resp_id = initial_resp.id

    # Second message from same contact
    second_time = datetime.now(timezone.utc)
    message_data = {
        "id": "wamid.INBOUND.TEST.002",
        "from": "919876500002",
        "timestamp": str(int(second_time.timestamp())),
        "type": "text",
        "text": {"body": "Following up on my inquiry."},
    }

    WebhookService.process_incoming_message(db_session, message_data)
    db_session.flush()

    # Verify no duplicate created
    all_resps = db_session.scalars(
        select(Respondent).where(Respondent.phone_number == phone)
    ).all()
    assert len(all_resps) == 1
    updated = all_resps[0]
    assert updated.id == resp_id
    assert updated.classification == "UNCLASSIFIED"


def test_delivery_status_does_not_create_respondent(client: TestClient, db_session: Session) -> None:
    """Verify delivery status notifications do NOT create respondents."""
    # Create an outbound message log
    msg_log = MessageLog(
        lead_id=None,
        message_type="campaign",
        whatsapp_message_id="wamid.STATUS.TEST.001",
        delivery_status="Accepted",
    )
    db_session.add(msg_log)
    db_session.flush()

    initial_count = len(db_session.scalars(select(Respondent)).all())

    # Incoming delivery status update
    status_data = {
        "id": "wamid.STATUS.TEST.001",
        "status": "delivered",
        "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        "recipient_id": "919876500099",
    }
    WebhookService.update_delivery_status(db_session, status_data)
    db_session.flush()

    # Verify message log updated
    assert msg_log.delivery_status == "Delivered"

    # Verify respondent count did NOT increase
    new_count = len(db_session.scalars(select(Respondent)).all())
    assert new_count == initial_count


def test_manual_classification_update(client: TestClient, db_session: Session) -> None:
    """Verify client can manually update respondent classification and only INTERESTED appear in interested section."""
    lead = Lead(
        customer_name="Anita Desai",
        phone_number="+919876500003",
        opt_in_status="OPTED_IN",
        status="Pending",
    )
    db_session.add(lead)
    db_session.flush()

    now = datetime.now(timezone.utc)
    resp = Respondent(
        lead_id=lead.id,
        phone_number="+919876500003",
        name="Anita Desai",
        classification="UNCLASSIFIED",
        first_reply_at=now,
        last_reply_at=now,
    )
    db_session.add(resp)
    db_session.flush()

    # 1. Update classification to INTERESTED
    patch_res = client.patch(
        f"/api/respondents/{resp.id}/classification",
        json={"classification": "INTERESTED"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["classification"] == "INTERESTED"

    # Verify lead status synced
    db_session.refresh(lead)
    assert lead.status == "Interested"

    # 2. Query Interested contacts filter
    get_res = client.get("/api/respondents?classification=INTERESTED")
    assert get_res.status_code == 200
    data = get_res.json()
    assert any(item["id"] == resp.id for item in data["items"])

    # 3. Update classification to NOT_INTERESTED
    patch_res2 = client.patch(
        f"/api/respondents/{resp.id}/classification",
        json={"classification": "NOT_INTERESTED"},
    )
    assert patch_res2.status_code == 200
    assert patch_res2.json()["classification"] == "NOT_INTERESTED"

    # Verify no longer in interested section
    get_res2 = client.get("/api/respondents?classification=INTERESTED")
    assert get_res2.status_code == 200
    data2 = get_res2.json()
    assert not any(item["id"] == resp.id for item in data2["items"])


def test_manual_contact_within_24h_window(client: TestClient, db_session: Session) -> None:
    """Verify manual freeform message permitted within 24h customer service window."""
    now = datetime.now(timezone.utc)
    lead = Lead(
        customer_name="Vikram Mehta",
        phone_number="+919876500004",
        opt_in_status="OPTED_IN",
        status="Interested",
    )
    db_session.add(lead)
    db_session.flush()

    resp = Respondent(
        lead_id=lead.id,
        phone_number="+919876500004",
        name="Vikram Mehta",
        classification="INTERESTED",
        first_reply_at=now - timedelta(hours=2),
        last_reply_at=now - timedelta(hours=2),  # Replied 2h ago -> Within 24h
    )
    db_session.add(resp)
    db_session.flush()

    res = client.post(
        f"/api/respondents/{resp.id}/contact",
        json={"message_text": "Hello Vikram, thank you for your inquiry about the Maldives package. Our agent is ready to help."},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["delivery_status"] == "Accepted"
    assert data["message_type"] == "manual_freeform"
    assert "wamid.mock" in data["whatsapp_message_id"]

    # Verify audit log was recorded in MessageLog
    log = db_session.scalar(
        select(MessageLog).where(MessageLog.whatsapp_message_id == data["whatsapp_message_id"])
    )
    assert log is not None
    assert log.lead_id == lead.id
    assert log.message_type == "manual_freeform"


def test_manual_contact_outside_24h_requires_template(client: TestClient, db_session: Session) -> None:
    """Verify manual contact outside 24h window rejects freeform text and requires approved template."""
    now = datetime.now(timezone.utc)
    lead = Lead(
        customer_name="Kiran Shah",
        phone_number="+919876500005",
        opt_in_status="OPTED_IN",
        status="Interested",
    )
    tpl = Template(
        template_name="approved_followup_tpl",
        language="en",
        category="UTILITY",
        approval_status="APPROVED",
        body_text="Hi {{1}}, following up on your trip request.",
    )
    db_session.add_all([lead, tpl])
    db_session.flush()

    # Last reply was 36 hours ago (outside 24h window)
    resp = Respondent(
        lead_id=lead.id,
        phone_number="+919876500005",
        name="Kiran Shah",
        classification="INTERESTED",
        first_reply_at=now - timedelta(hours=36),
        last_reply_at=now - timedelta(hours=36),
    )
    db_session.add(resp)
    db_session.flush()

    # 1. Attempt freeform message outside 24h -> Rejected
    res1 = client.post(
        f"/api/respondents/{resp.id}/contact",
        json={"message_text": "Hey Kiran, are you still interested?"},
    )
    assert res1.status_code == 400
    assert "24-hour" in res1.json()["detail"]

    # 2. Send approved template outside 24h -> Succeeded
    res2 = client.post(
        f"/api/respondents/{resp.id}/contact",
        json={"template_name": "approved_followup_tpl", "template_language": "en"},
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["success"] is True
    assert data2["message_type"] == "manual_template"


def test_manual_contact_blocked_on_opt_out(client: TestClient, db_session: Session) -> None:
    """Verify manual contact cannot override customer opt-out restrictions."""
    now = datetime.now(timezone.utc)
    lead = Lead(
        customer_name="Opted Out Contact",
        phone_number="+919876500006",
        opt_in_status="OPTED_OUT",
        status="Not Interested",
    )
    db_session.add(lead)
    db_session.flush()

    resp = Respondent(
        lead_id=lead.id,
        phone_number="+919876500006",
        name="Opted Out Contact",
        classification="NOT_INTERESTED",
        first_reply_at=now,
        last_reply_at=now,
    )
    db_session.add(resp)
    db_session.flush()

    res = client.post(
        f"/api/respondents/{resp.id}/contact",
        json={"message_text": "Trying to contact anyway"},
    )
    assert res.status_code == 400
    assert "opted out" in res.json()["detail"].lower()


def test_immediate_campaign_batch_send_workflow(client: TestClient, db_session: Session) -> None:
    """Verify campaigns execute immediately upon batch approval without APScheduler."""
    # Create approved template
    tpl = Template(
        template_name="immediate_promo_tpl",
        language="en",
        category="MARKETING",
        approval_status="APPROVED",
        body_text="Exclusive travel package!",
    )
    db_session.add(tpl)

    # Create 3 opted in leads
    leads = []
    for i in range(1, 4):
        l = Lead(
            customer_name=f"Campaign Recipient {i}",
            phone_number=f"+91987650010{i}",
            opt_in_status="OPTED_IN",
            status="Pending",
        )
        db_session.add(l)
        leads.append(l)
    db_session.flush()

    # Create campaign
    create_res = client.post("/api/campaigns", json={
        "campaign_name": "Immediate Winter Dubai 2026",
        "template_name": "immediate_promo_tpl",
        "template_language": "en",
        "auto_generate_batches": True,
        "batch_size": 50,
    })
    assert create_res.status_code == 201
    camp_data = create_res.json()
    campaign_id = camp_data["id"]

    # Fetch generated batch
    batches_res = client.get(f"/api/campaigns/{campaign_id}/batches")
    assert batches_res.status_code == 200
    batches = batches_res.json()["items"]
    assert len(batches) == 1
    batch_id = batches[0]["id"]
    assert batches[0]["approval_status"] == "PENDING_APPROVAL"

    # Attempt to send unapproved batch -> Must fail (Mandatory Approval Rule)
    unapproved_send_res = client.post(f"/api/campaigns/{campaign_id}/batches/{batch_id}/send")
    assert unapproved_send_res.status_code == 400
    assert "mandatory" in unapproved_send_res.json()["detail"].lower()

    # Approve batch
    approve_res = client.post(f"/api/campaigns/{campaign_id}/batches/{batch_id}/approve")
    assert approve_res.status_code == 200
    assert approve_res.json()["approval_status"] == "Approved"

    # Mock Meta client for batch dispatch
    mock_meta_client = AsyncMock()
    mock_meta_client.send_template_message.side_effect = [
        {"success": True, "whatsapp_message_id": "wamid.camp_imm_001"},
        {"success": True, "whatsapp_message_id": "wamid.camp_imm_002"},
        {"success": True, "whatsapp_message_id": "wamid.camp_imm_003"},
    ]

    # Immediate dispatch
    with patch("app.services.whatsapp_service.get_whatsapp_client", return_value=mock_meta_client):
        send_res = client.post(f"/api/campaigns/{campaign_id}/batches/{batch_id}/send")
    assert send_res.status_code == 200
    send_data = send_res.json()
    assert send_data["send_status"] == "Completed"
    assert send_data["sent_count"] == 3

    # Attempt duplicate dispatch -> Rejected
    dup_res = client.post(f"/api/campaigns/{campaign_id}/batches/{batch_id}/send")
    assert dup_res.status_code == 400
    assert "duplicate" in dup_res.json()["detail"].lower()
