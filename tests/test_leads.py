"""Automated tests for Phase 4 Lead Management."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import FollowUpSchedule, IncomingMessage, Lead, MessageLog
from app.schemas.lead_schemas import LeadCreate, LeadUpdate
from app.services.lead_service import LeadService


def test_create_valid_lead(client: TestClient, db_session: Session) -> None:
    """1. Test creating a valid lead via POST /api/leads."""
    payload = {
        "customer_name": "Rohan Mehra",
        "phone_number": "+919876543210",
        "serial_number": "LEAD-001",
        "status": "Pending",
        "follow_up_paused": False,
    }
    response = client.post("/api/leads", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["customer_name"] == "Rohan Mehra"
    assert data["phone_number"] == "+919876543210"
    assert data["status"] == "Pending"
    assert data["follow_up_paused"] is False
    assert data["is_deleted"] is False
    assert data["id"] is not None


def test_reject_invalid_lead(client: TestClient) -> None:
    """2. Test rejecting an invalid lead (empty name or bad phone number)."""
    # Empty customer name
    resp1 = client.post("/api/leads", json={"customer_name": "   ", "phone_number": "+919876543210"})
    assert resp1.status_code == 422

    # Malformed phone number (letters)
    resp2 = client.post("/api/leads", json={"customer_name": "John Doe", "phone_number": "invalid-phone"})
    assert resp2.status_code == 422


def test_reject_duplicate_phone_numbers(client: TestClient, db_session: Session) -> None:
    """3. Test rejecting duplicate phone numbers with HTTP 409 Conflict."""
    lead = Lead(customer_name="Original Lead", phone_number="+919876543210")
    db_session.add(lead)
    db_session.flush()

    response = client.post("/api/leads", json={
        "customer_name": "Duplicate Lead",
        "phone_number": "+919876543210",
    })
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()


def test_list_leads_pagination(client: TestClient, db_session: Session) -> None:
    """4. Test listing leads with pagination."""
    for i in range(15):
        lead = Lead(customer_name=f"Customer {i}", phone_number=f"+9198765432{i:02d}")
        db_session.add(lead)
    db_session.flush()

    response = client.get("/api/leads?page=1&page_size=10")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 15
    assert len(data["items"]) == 10
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert data["total_pages"] >= 2


def test_search_by_name(client: TestClient, db_session: Session) -> None:
    """5. Test searching leads by customer name."""
    db_session.add(Lead(customer_name="Priya Sharma", phone_number="+919811111111"))
    db_session.add(Lead(customer_name="Rahul Verma", phone_number="+919822222222"))
    db_session.flush()

    response = client.get("/api/leads?search=sharma")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["customer_name"] == "Priya Sharma"


def test_search_by_phone(client: TestClient, db_session: Session) -> None:
    """6. Test searching leads by phone number."""
    db_session.add(Lead(customer_name="Manish Jain", phone_number="+919833333333"))
    db_session.add(Lead(customer_name="Sanjay Gupta", phone_number="+919844444444"))
    db_session.flush()

    response = client.get("/api/leads?search=983333")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["customer_name"] == "Manish Jain"


def test_filter_by_status(client: TestClient, db_session: Session) -> None:
    """7. Test filtering leads by status."""
    db_session.add(Lead(customer_name="Lead A", phone_number="+919855555551", status="Pending"))
    db_session.add(Lead(customer_name="Lead B", phone_number="+919855555552", status="Replied"))
    db_session.add(Lead(customer_name="Lead C", phone_number="+919855555553", status="Not Interested"))
    db_session.flush()

    response = client.get("/api/leads?status=Replied")
    assert response.status_code == 200
    data = response.json()
    assert all(item["status"] == "Replied" for item in data["items"])
    assert any(item["customer_name"] == "Lead B" for item in data["items"])


def test_get_lead_by_id(client: TestClient, db_session: Session) -> None:
    """8. Test retrieving a single lead by ID."""
    lead = Lead(customer_name="Deepa Roy", phone_number="+919866666666", serial_number="SR-99")
    db_session.add(lead)
    db_session.flush()

    response = client.get(f"/api/leads/{lead.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == lead.id
    assert data["customer_name"] == "Deepa Roy"
    assert data["serial_number"] == "SR-99"


def test_update_lead_details(client: TestClient, db_session: Session) -> None:
    """9. Test updating lead details (name, phone, serial)."""
    lead = Lead(customer_name="Original Name", phone_number="+919877777777")
    db_session.add(lead)
    db_session.flush()

    update_payload = {
        "customer_name": "Updated Name",
        "phone_number": "+919888888888",
        "serial_number": "NEW-SR-01",
    }
    response = client.patch(f"/api/leads/{lead.id}", json=update_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["customer_name"] == "Updated Name"
    assert data["phone_number"] == "+919888888888"
    assert data["serial_number"] == "NEW-SR-01"


def test_reject_invalid_statuses(client: TestClient, db_session: Session) -> None:
    """10. Test rejecting prohibited statuses."""
    lead = Lead(customer_name="Test Status", phone_number="+919899999999")
    db_session.add(lead)
    db_session.flush()

    # Invalid status is strictly rejected
    response = client.patch(f"/api/leads/{lead.id}", json={"status": "InvalidStatus"})
    assert response.status_code == 422


def test_pause_followups(client: TestClient, db_session: Session) -> None:
    """11. Test pausing follow-ups sets follow_up_paused = True."""
    lead = Lead(customer_name="Pause Test", phone_number="+919800000001", follow_up_paused=False)
    db_session.add(lead)
    db_session.flush()

    response = client.post(f"/api/leads/{lead.id}/pause-followups")
    assert response.status_code == 200
    assert response.json()["follow_up_paused"] is True

    # Verify database state
    updated_lead = db_session.get(Lead, lead.id)
    assert updated_lead.follow_up_paused is True


def test_resume_followups(client: TestClient, db_session: Session) -> None:
    """12. Test resuming follow-ups sets follow_up_paused = False."""
    lead = Lead(customer_name="Resume Test", phone_number="+919800000002", follow_up_paused=True)
    db_session.add(lead)
    db_session.flush()

    response = client.post(f"/api/leads/{lead.id}/resume-followups")
    assert response.status_code == 200
    assert response.json()["follow_up_paused"] is False

    updated_lead = db_session.get(Lead, lead.id)
    assert updated_lead.follow_up_paused is False


def test_replied_status_does_not_pause_followups(client: TestClient, db_session: Session) -> None:
    """13. Business Rule: Changing status to Replied must NOT automatically pause follow-ups."""
    lead = Lead(customer_name="Reply Test", phone_number="+919800000003", status="Pending", follow_up_paused=False)
    db_session.add(lead)
    db_session.flush()

    response = client.patch(f"/api/leads/{lead.id}", json={"status": "Replied"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Replied"
    assert data["follow_up_paused"] is False  # Must remain False!


def test_not_interested_cancels_future_followups(client: TestClient, db_session: Session) -> None:
    """14. Business Rule: Not Interested must cancel future scheduled follow-ups."""
    lead = Lead(customer_name="Not Interested Test", phone_number="+919800000004", status="Pending")
    db_session.add(lead)
    db_session.flush()

    now = datetime.now(timezone.utc)
    s1 = FollowUpSchedule(lead_id=lead.id, sequence_number=1, scheduled_at=now + timedelta(days=1), status="Scheduled")
    s2 = FollowUpSchedule(lead_id=lead.id, sequence_number=2, scheduled_at=now + timedelta(days=3), status="Approved")
    db_session.add_all([s1, s2])
    db_session.flush()

    response = client.patch(f"/api/leads/{lead.id}", json={"status": "Not Interested"})
    assert response.status_code == 200
    assert response.json()["status"] == "Not Interested"

    # Verify both schedules became 'Cancelled'
    sched1 = db_session.get(FollowUpSchedule, s1.id)
    sched2 = db_session.get(FollowUpSchedule, s2.id)
    assert sched1.status == "Cancelled"
    assert sched2.status == "Cancelled"


def test_handle_nonexistent_lead_id(client: TestClient) -> None:
    """15. Test requesting a nonexistent lead ID returns HTTP 404."""
    resp_get = client.get("/api/leads/999999")
    assert resp_get.status_code == 404

    resp_patch = client.patch("/api/leads/999999", json={"customer_name": "Ghost"})
    assert resp_patch.status_code == 404

    resp_del = client.delete("/api/leads/999999")
    assert resp_del.status_code == 404


def test_safe_deletion_and_history_preservation(client: TestClient, db_session: Session) -> None:
    """16. Test soft deletion cancels pending schedules while preserving past communication history."""
    lead = Lead(customer_name="Delete Candidate", phone_number="+919800000005")
    db_session.add(lead)
    db_session.flush()

    # Add historical message log and incoming message
    msg_log = MessageLog(lead_id=lead.id, message_type="follow_up", delivery_status="Delivered")
    inc_msg = IncomingMessage(
        lead_id=lead.id,
        whatsapp_message_id="wamid.HIST.001",
        sender_phone="+919800000005",
        received_at=datetime.now(timezone.utc),
    )
    sched = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
        status="Scheduled",
    )
    db_session.add_all([msg_log, inc_msg, sched])
    db_session.flush()

    # Delete lead
    response = client.delete(f"/api/leads/{lead.id}")
    assert response.status_code == 200
    assert response.json()["is_deleted"] is True

    # 1. Lead is not returned in standard list
    list_resp = client.get("/api/leads")
    assert not any(item["id"] == lead.id for item in list_resp.json()["items"])

    # 2. History records are preserved!
    assert db_session.get(MessageLog, msg_log.id) is not None
    assert db_session.get(IncomingMessage, inc_msg.id) is not None
    # 3. Pending schedule was cancelled
    assert db_session.get(FollowUpSchedule, sched.id).status == "Cancelled"


def test_excel_synchronization_on_lead_change(tmp_path: Path, client: TestClient, db_session: Session) -> None:
    """17. Test that lead creation/update triggers safe synchronization if workbook exists."""
    settings = get_settings()
    wb_file = tmp_path / "leads.xlsx"
    backup_dir = tmp_path / "backups"

    original_auth_path = settings.AUTHORIZED_EXCEL_PATH
    original_backup_dir = settings.BACKUP_DIR
    settings.AUTHORIZED_EXCEL_PATH = str(wb_file)
    settings.BACKUP_DIR = str(backup_dir)

    try:
        # Create initial workbook
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Serial Number", "Name", "Contact Number"])
        ws.append(["L-99", "Sync Customer", "+919800000009"])
        wb.save(wb_file)
        wb.close()

        # Create lead matching the workbook
        client.post("/api/leads", json={
            "customer_name": "Sync Customer",
            "phone_number": "+919800000009",
            "serial_number": "L-99",
            "status": "Pending",
        })

        # Check that workbook was synchronized with automation columns
        updated_wb = openpyxl.load_workbook(wb_file)
        updated_ws = updated_wb.active
        headers = [c.value for c in updated_ws[1]]
        assert "Status" in headers
        assert "Follow-up Paused" in headers
        updated_wb.close()

    finally:
        settings.AUTHORIZED_EXCEL_PATH = original_auth_path
        settings.BACKUP_DIR = original_backup_dir


def test_transaction_rollback_on_failure(db_session: Session) -> None:
    """18. Test transaction rollback when lead creation fails."""
    # Pre-add lead
    db_session.add(Lead(customer_name="Existing Phone", phone_number="+919800000010"))
    db_session.flush()

    # Attempt to create duplicate lead through LeadService: should raise LeadDuplicateError and rollback
    with pytest.raises(Exception):
        LeadService.create_lead(
            db=db_session,
            payload=LeadCreate(customer_name="New Lead", phone_number="+919800000010"),
        )
