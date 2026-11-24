"""Automated tests for Phase 9.4 Client-Facing Lead Management Module."""

from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import FollowUpSchedule, IncomingMessage, Lead, MessageLog


def test_list_leads_filter_by_consent(client: TestClient, db_session: Session) -> None:
    """Test filtering leads by opt_in_status (OPTED_IN, NOT_OPTED_IN, OPTED_OUT)."""
    lead_opt_in = Lead(
        customer_name="Aarav Sharma",
        phone_number="+919811100001",
        status="Pending",
        opt_in_status="OPTED_IN",
        opt_in_source="website_form",
        opt_in_timestamp=datetime.now(timezone.utc),
    )
    lead_not_opted = Lead(
        customer_name="Bhavna Patel",
        phone_number="+919811100002",
        status="Pending",
        opt_in_status="NOT_OPTED_IN",
    )
    lead_opt_out = Lead(
        customer_name="Chetan Rao",
        phone_number="+919811100003",
        status="Replied",
        opt_in_status="OPTED_OUT",
        opt_out_timestamp=datetime.now(timezone.utc),
    )
    db_session.add_all([lead_opt_in, lead_not_opted, lead_opt_out])
    db_session.flush()

    # 1. Filter OPTED_IN
    res_in = client.get("/api/leads?opt_in_status=OPTED_IN")
    assert res_in.status_code == 200
    data_in = res_in.json()
    assert all(item["opt_in_status"] == "OPTED_IN" for item in data_in["items"])
    assert any(item["phone_number"] == "+919811100001" for item in data_in["items"])
    assert not any(item["phone_number"] == "+919811100002" for item in data_in["items"])

    # 2. Filter NOT_OPTED_IN
    res_not = client.get("/api/leads?opt_in_status=NOT_OPTED_IN")
    assert res_not.status_code == 200
    data_not = res_not.json()
    assert all(item["opt_in_status"] == "NOT_OPTED_IN" for item in data_not["items"])
    assert any(item["phone_number"] == "+919811100002" for item in data_not["items"])

    # 3. Filter OPTED_OUT
    res_out = client.get("/api/leads?opt_in_status=OPTED_OUT")
    assert res_out.status_code == 200
    data_out = res_out.json()
    assert all(item["opt_in_status"] == "OPTED_OUT" for item in data_out["items"])
    assert any(item["phone_number"] == "+919811100003" for item in data_out["items"])


def test_list_leads_combined_filters(client: TestClient, db_session: Session) -> None:
    """Test filtering leads with combined status and opt_in_status parameters."""
    l1 = Lead(
        customer_name="Deepak Joshi",
        phone_number="+919822200001",
        status="Pending",
        opt_in_status="OPTED_IN",
        opt_in_source="web_form",
    )
    l2 = Lead(
        customer_name="Divya Nair",
        phone_number="+919822200002",
        status="Replied",
        opt_in_status="OPTED_IN",
        opt_in_source="web_form",
    )
    db_session.add_all([l1, l2])
    db_session.flush()

    res = client.get("/api/leads?status=Pending&opt_in_status=OPTED_IN")
    assert res.status_code == 200
    data = res.json()
    assert any(item["phone_number"] == "+919822200001" for item in data["items"])
    assert not any(item["phone_number"] == "+919822200002" for item in data["items"])


def test_get_lead_detail_with_history_and_schedules(client: TestClient, db_session: Session) -> None:
    """Test GET /api/leads/{id}/detail returns lead info, follow-up schedules, and message logs."""
    lead = Lead(
        customer_name="Esha Gupta",
        phone_number="+919833300001",
        serial_number="LEAD-EG-01",
        status="Pending",
        opt_in_status="OPTED_IN",
        opt_in_source="qr_code",
        opt_in_timestamp=datetime.now(timezone.utc),
    )
    db_session.add(lead)
    db_session.flush()

    # Add follow-up schedule
    sched1 = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
        status="Scheduled",
        attempt_number=1,
    )
    sched2 = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=2,
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=3),
        status="Scheduled",
        attempt_number=2,
    )
    db_session.add_all([sched1, sched2])

    # Add outbound message log
    msg_log = MessageLog(
        lead_id=lead.id,
        message_type="template",
        template_name="travel_itinerary",
        whatsapp_message_id="wamid.HBgLMTIzNDU2",
        delivery_status="Delivered",
        delivered_at=datetime.now(timezone.utc),
    )
    db_session.add(msg_log)

    # Add inbound incoming message
    incoming = IncomingMessage(
        lead_id=lead.id,
        whatsapp_message_id="wamid.INBOUND_998877",
        sender_phone="+919833300001",
        message_text="Interested in the Dubai package",
        message_type="text",
        received_at=datetime.now(timezone.utc),
        processing_status="PROCESSED",
    )
    db_session.add(incoming)
    db_session.flush()

    # Call endpoint
    res = client.get(f"/api/leads/{lead.id}/detail")
    assert res.status_code == 200
    data = res.json()

    # Assert Lead info
    assert data["id"] == lead.id
    assert data["customer_name"] == "Esha Gupta"
    assert data["phone_number"] == "+919833300001"
    assert data["serial_number"] == "LEAD-EG-01"
    assert data["opt_in_status"] == "OPTED_IN"
    assert data["opt_in_source"] == "qr_code"

    # Assert Follow-up Schedules
    assert len(data["follow_up_schedules"]) == 2
    assert data["follow_up_schedules"][0]["sequence_number"] == 1
    assert data["follow_up_schedules"][0]["status"] == "Scheduled"
    assert data["follow_up_schedules"][1]["sequence_number"] == 2

    # Assert Outbound Message Logs
    assert len(data["message_logs"]) == 1
    assert data["message_logs"][0]["whatsapp_message_id"] == "wamid.HBgLMTIzNDU2"
    assert data["message_logs"][0]["delivery_status"] == "Delivered"

    # Assert Inbound Incoming Messages
    assert len(data["incoming_messages"]) == 1
    assert data["incoming_messages"][0]["whatsapp_message_id"] == "wamid.INBOUND_998877"
    assert data["incoming_messages"][0]["message_text"] == "Interested in the Dubai package"


def test_get_lead_detail_not_found(client: TestClient) -> None:
    """Test GET /api/leads/{id}/detail returns 404 for nonexistent lead."""
    res = client.get("/api/leads/999999/detail")
    assert res.status_code == 404
    assert "does not exist" in res.json()["detail"].lower()


def test_update_lead_fields_and_status(client: TestClient, db_session: Session) -> None:
    """Test updating lead fields and status."""
    lead = Lead(
        customer_name="Farhan Akhtar",
        phone_number="+919844400001",
        status="Pending",
        opt_in_status="NOT_OPTED_IN",
    )
    db_session.add(lead)
    db_session.flush()

    # Create a scheduled follow-up
    sched = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=2),
        status="Scheduled",
    )
    db_session.add(sched)
    db_session.flush()

    # Update name and status to "Replied"
    res1 = client.patch(
        f"/api/leads/{lead.id}",
        json={"customer_name": "Farhan A. Khan", "status": "Replied"},
    )
    assert res1.status_code == 200
    assert res1.json()["customer_name"] == "Farhan A. Khan"
    assert res1.json()["status"] == "Replied"

    # Verify schedule is NOT cancelled on "Replied"
    db_session.refresh(sched)
    assert sched.status == "Scheduled"

    # Update status to "Not Interested" -> Must cancel future schedules
    res2 = client.patch(
        f"/api/leads/{lead.id}",
        json={"status": "Not Interested"},
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == "Not Interested"

    db_session.refresh(sched)
    assert sched.status == "Cancelled"


def test_update_lead_duplicate_phone_rejected(client: TestClient, db_session: Session) -> None:
    """Test updating lead with a conflicting phone number returns 409 Conflict."""
    l1 = Lead(customer_name="Geeta Kapoor", phone_number="+919855500001")
    l2 = Lead(customer_name="Govinda Ahuja", phone_number="+919855500002")
    db_session.add_all([l1, l2])
    db_session.flush()

    # Try to set l2's phone to l1's phone
    res = client.patch(
        f"/api/leads/{l2.id}",
        json={"phone_number": "+919855500001"},
    )
    assert res.status_code == 409
    assert "already assigned" in res.json()["detail"].lower()


def test_pause_and_resume_lead_followups(client: TestClient, db_session: Session) -> None:
    """Test pausing and resuming automated follow-ups via dedicated endpoints."""
    lead = Lead(customer_name="Harish Verma", phone_number="+919866600001", follow_up_paused=False)
    db_session.add(lead)
    db_session.flush()

    # 1. Pause follow-ups
    res_pause = client.post(f"/api/leads/{lead.id}/pause-followups")
    assert res_pause.status_code == 200
    assert res_pause.json()["follow_up_paused"] is True

    # 2. Resume follow-ups
    res_resume = client.post(f"/api/leads/{lead.id}/resume-followups")
    assert res_resume.status_code == 200
    assert res_resume.json()["follow_up_paused"] is False


def test_consent_update_opt_in_validation(client: TestClient, db_session: Session) -> None:
    """Test that setting OPTED_IN requires an explicit, verifiable opt_in_source."""
    lead = Lead(customer_name="Ishaan Khattar", phone_number="+919877700001", opt_in_status="NOT_OPTED_IN")
    db_session.add(lead)
    db_session.flush()

    # 1. Attempt OPTED_IN without opt_in_source -> 422 Unprocessable Entity
    res_fail = client.post(
        f"/api/leads/{lead.id}/consent",
        json={"opt_in_status": "OPTED_IN"},
    )
    assert res_fail.status_code == 422
    assert "opt_in_source is required" in res_fail.json()["detail"].lower()

    # 2. Attempt OPTED_IN with whitespace-only source -> 422 Unprocessable Entity
    res_fail_ws = client.post(
        f"/api/leads/{lead.id}/consent",
        json={"opt_in_status": "OPTED_IN", "opt_in_source": "   "},
    )
    assert res_fail_ws.status_code == 422

    # 3. Successful OPTED_IN with verifiable source
    res_ok = client.post(
        f"/api/leads/{lead.id}/consent",
        json={"opt_in_status": "OPTED_IN", "opt_in_source": "verbal_inquiry"},
    )
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["opt_in_status"] == "OPTED_IN"
    assert data["opt_in_source"] == "verbal_inquiry"
    assert data["opt_in_timestamp"] is not None

    # 4. Successful OPTED_OUT sets opt_out_timestamp
    res_out = client.post(
        f"/api/leads/{lead.id}/consent",
        json={"opt_in_status": "OPTED_OUT"},
    )
    assert res_out.status_code == 200
    data_out = res_out.json()
    assert data_out["opt_in_status"] == "OPTED_OUT"
    assert data_out["opt_out_timestamp"] is not None


def test_create_lead_opt_in_requires_source(client: TestClient) -> None:
    """Test that creating a lead directly with OPTED_IN requires opt_in_source."""
    # Without opt_in_source
    res_fail = client.post(
        "/api/leads",
        json={
            "customer_name": "Jaya Bachchan",
            "phone_number": "+919888800001",
            "opt_in_status": "OPTED_IN",
        },
    )
    assert res_fail.status_code == 422
    assert "opt_in_source is required" in res_fail.json()["detail"].lower()

    # With opt_in_source
    res_ok = client.post(
        "/api/leads",
        json={
            "customer_name": "Jaya Bachchan",
            "phone_number": "+919888800001",
            "opt_in_status": "OPTED_IN",
            "opt_in_source": "signed_form",
        },
    )
    assert res_ok.status_code == 201
    assert res_ok.json()["opt_in_status"] == "OPTED_IN"
    assert res_ok.json()["opt_in_source"] == "signed_form"


def test_leads_endpoints_protected_against_unauthenticated_access(
    unauthenticated_client: TestClient, db_session: Session
) -> None:
    """Test that all lead endpoints require authentication."""
    lead = Lead(customer_name="Kavita Rao", phone_number="+919899900001")
    db_session.add(lead)
    db_session.flush()

    assert unauthenticated_client.get("/api/leads").status_code == 401
    assert unauthenticated_client.get(f"/api/leads/{lead.id}").status_code == 401
    assert unauthenticated_client.get(f"/api/leads/{lead.id}/detail").status_code == 401
    assert unauthenticated_client.post("/api/leads", json={"customer_name": "Test", "phone_number": "+919000000000"}).status_code == 401
    assert unauthenticated_client.patch(f"/api/leads/{lead.id}", json={"customer_name": "Test"}).status_code == 401
    assert unauthenticated_client.post(f"/api/leads/{lead.id}/consent", json={"opt_in_status": "OPTED_OUT"}).status_code == 401
    assert unauthenticated_client.post(f"/api/leads/{lead.id}/pause-followups").status_code == 401
    assert unauthenticated_client.post(f"/api/leads/{lead.id}/resume-followups").status_code == 401
    assert unauthenticated_client.delete(f"/api/leads/{lead.id}").status_code == 401
