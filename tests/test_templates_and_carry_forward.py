"""Automated tests for Image+Text Template Builder, Carry-Forward Scheduling, and Report Metrics."""

from datetime import datetime, timedelta, timezone
import io
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.campaign import Campaign, CampaignBatch, CampaignRecipient
from app.db.models.lead import Lead
from app.db.models.template import Template
from app.services.campaign_service import CampaignService
from app.services.template_service import TemplateService


@pytest.fixture
def test_setup_data(db_session: Session) -> dict:
    """Create template and consented leads for carry-forward testing."""
    tpl = Template(
        template_name="carry_forward_promo",
        language="en",
        category="MARKETING",
        approval_status="APPROVED",
        body_text="Hi {{customer_name}}, check our offers!",
        expected_parameters='["customer_name"]',
        header_type="IMAGE",
        header_image_path="data/uploads/templates/test.jpg",
    )
    db_session.add(tpl)

    # Create 8 consented leads
    leads = []
    for i in range(1, 9):
        l = Lead(
            customer_name=f"Lead {i}",
            phone_number=f"+9198765430{i:02d}",
            opt_in_status="OPTED_IN",
            opt_in_source="Website Form",
            status="Pending",
            follow_up_paused=False,
            is_deleted=False,
        )
        db_session.add(l)
        leads.append(l)

    db_session.commit()
    return {"template": tpl, "leads": leads}


# =============================================================================
# Task 1: Image Upload & Template Builder Tests
# =============================================================================

def test_template_image_upload_accepts_valid_image(client: TestClient):
    """Verify JPEG and PNG uploads succeed and return storage paths."""
    fake_jpeg_content = b"\xff\xd8\xff\xe0" + b"0" * 1024
    response = client.post(
        "/api/templates/upload-image",
        files={"file": ("banner.jpg", io.BytesIO(fake_jpeg_content), "image/jpeg")},
    )
    assert response.status_code == 201
    data = response.json()
    assert "image_path" in data
    assert "image_url" in data
    assert data["image_path"].startswith("data/uploads/templates/")
    assert data["image_url"].startswith("/uploads/templates/")


def test_template_image_upload_strictly_rejects_pdf(client: TestClient):
    """Verify PDFs are strictly rejected with HTTP 400 Bad Request."""
    fake_pdf = b"%PDF-1.4\n..."
    response = client.post(
        "/api/templates/upload-image",
        files={"file": ("flyer.pdf", io.BytesIO(fake_pdf), "application/pdf")},
    )
    assert response.status_code == 400
    assert "PDFs and documents are strictly prohibited" in response.json()["detail"]


def test_template_image_upload_strictly_rejects_video_or_doc(client: TestClient):
    """Verify other non-image formats are rejected with HTTP 400."""
    fake_doc = b"Document text..."
    response = client.post(
        "/api/templates/upload-image",
        files={"file": ("notes.docx", io.BytesIO(fake_doc), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert response.status_code == 400
    assert "Invalid image format" in response.json()["detail"]


def test_template_image_upload_rejects_oversized_file(client: TestClient):
    """Verify image files exceeding 5MB are rejected."""
    oversized = b"0" * (5 * 1024 * 1024 + 100)
    response = client.post(
        "/api/templates/upload-image",
        files={"file": ("large.png", io.BytesIO(oversized), "image/png")},
    )
    assert response.status_code == 400
    assert "exceeds maximum allowed size of 5MB" in response.json()["detail"]


def test_create_template_name_validation(client: TestClient):
    """Verify template name must follow Meta's lowercase underscore format."""
    # Invalid name with spaces and capital letters
    res_bad = client.post(
        "/api/templates",
        json={
            "template_name": "My Invalid Template!",
            "category": "MARKETING",
            "language": "en",
            "body_text": "Hello world",
        },
    )
    assert res_bad.status_code == 400
    assert "only lowercase alphanumeric characters and underscores" in res_bad.json()["detail"]

    # Valid name
    res_ok = client.post(
        "/api/templates",
        json={
            "template_name": "summer_promo_2026",
            "category": "MARKETING",
            "language": "en",
            "header_type": "TEXT",
            "header_text": "Exclusive Summer Deal",
            "body_text": "Hello {{1}}, enjoy our travel deals to {{2}}!",
        },
    )
    assert res_ok.status_code == 201
    tpl = res_ok.json()
    assert tpl["template_name"] == "summer_promo_2026"
    assert tpl["approval_status"] == "PENDING"
    assert tpl["expected_parameters"] == ["param_1", "param_2"]


def test_mock_approve_template(client: TestClient, db_session: Session):
    """Verify mock-approve endpoint transitions template from PENDING to APPROVED."""
    # Create pending template
    pending_tpl = Template(
        template_name="mock_test_pending_tpl",
        language="en",
        category="MARKETING",
        approval_status="PENDING",
        body_text="Hi {{1}}, this is pending review.",
    )
    db_session.add(pending_tpl)
    db_session.commit()
    db_session.refresh(pending_tpl)

    res = client.post(f"/api/templates/{pending_tpl.id}/mock-approve")
    assert res.status_code == 200
    data = res.json()
    assert data["approval_status"] == "APPROVED"

    # Verify persisted in database
    db_session.refresh(pending_tpl)
    assert pending_tpl.approval_status == "APPROVED"


def test_sync_templates_endpoint(client: TestClient):
    """Verify POST /api/templates/sync succeeds."""
    res = client.post("/api/templates/sync")
    assert res.status_code == 200
    assert res.json()["synced"] is True


# =============================================================================
# Task 2: Batch Sizing & Carry-Forward Scheduling Tests
# =============================================================================

def test_batch_sizing_and_carry_forward_timestamps(client: TestClient, test_setup_data: dict, db_session: Session):
    """Verify partitioned batches receive sequential carry-forward scheduled_at timestamps."""
    base_time = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)

    # 8 leads partitioned with batch_size=3 and carry_forward_interval_hours=24
    # Expected: 3 batches (sizes 3, 3, 2)
    # Batch 1: scheduled_at = base_time
    # Batch 2: scheduled_at = base_time + 24 hours
    # Batch 3: scheduled_at = base_time + 48 hours
    res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Carry Forward Test Campaign",
            "template_name": "carry_forward_promo",
            "template_language": "en",
            "batch_size": 3,
            "carry_forward_interval_hours": 24,
            "scheduled_at": base_time.isoformat(),
            "auto_generate_batches": True,
        },
    )
    assert res.status_code == 201
    camp_data = res.json()
    assert camp_data["batch_count"] == 3

    batches = CampaignService.list_batches(db_session, camp_data["id"])
    assert len(batches) == 3
    assert batches[0].batch_size == 3
    assert batches[1].batch_size == 3
    assert batches[2].batch_size == 2

    # Check timestamps (normalizing SQLite naive datetime to UTC)
    def to_utc(dt):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    assert to_utc(batches[0].scheduled_at) == base_time
    assert to_utc(batches[1].scheduled_at) == base_time + timedelta(hours=24)
    assert to_utc(batches[2].scheduled_at) == base_time + timedelta(hours=48)


@pytest.mark.skip(
    reason="Campaign polling worker process_due_campaign_batches decommissioned; campaigns are now sent immediately upon manual batch approval."
)
def test_process_due_campaign_batches_carry_forward_progression(db_session: Session, test_setup_data: dict):
    """Verify process_due_campaign_batches only sends batches whose scheduled_at has arrived."""
    base_time = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)

    # Create campaign
    camp = Campaign(
        campaign_name="Sequential Dispatch Campaign",
        template_name="carry_forward_promo",
        template_language="en",
        status="Scheduled",
        scheduled_at=base_time,
        total_leads_selected=0,
        total_leads_eligible=0,
        total_leads_excluded=0,
    )
    db_session.add(camp)
    db_session.flush()

    # Generate batches with 24-hour carry-forward interval (batch_size=3 over 8 leads = 3 batches)
    batches, _ = CampaignService.generate_batches(
        db=db_session,
        campaign_id=camp.id,
        batch_size=3,
        carry_forward_interval_hours=24,
    )
    assert len(batches) == 3

    # Approve all batches in advance
    for b in batches:
        b.approval_status = "Approved"
        b.approved_at = base_time
    db_session.commit()

    mock_client = AsyncMock()
    mock_client.send_template_message.return_value = {
        "messages": [{"id": "wamid.mock.test"}],
        "contacts": [{"wa_id": "919876543201"}],
    }

    with patch("app.services.whatsapp_service.get_whatsapp_client", return_value=mock_client):
        # Time 1: At base_time -> Only Batch 1 should dispatch
        results_t1 = CampaignService.process_due_campaign_batches(
            db=db_session,
            now_utc=base_time,
            client=mock_client,
        )
        assert len(results_t1) == 1
        assert results_t1[0]["batch_number"] == 1
        assert results_t1[0]["send_status"] == "Completed"

        db_session.refresh(batches[0])
        db_session.refresh(batches[1])
        db_session.refresh(batches[2])
        assert batches[0].send_status == "Completed"
        assert batches[1].send_status == "Pending"
        assert batches[2].send_status == "Pending"

        # Time 2: 12 hours later -> Still before Batch 2 (scheduled at 24h) -> No new batches sent
        results_t2 = CampaignService.process_due_campaign_batches(
            db=db_session,
            now_utc=base_time + timedelta(hours=12),
            client=mock_client,
        )
        assert len(results_t2) == 0

        # Time 3: 25 hours later -> Batch 2 is now due and should dispatch
        results_t3 = CampaignService.process_due_campaign_batches(
            db=db_session,
            now_utc=base_time + timedelta(hours=25),
            client=mock_client,
        )
        assert len(results_t3) == 1
        assert results_t3[0]["batch_number"] == 2
        assert results_t3[0]["send_status"] == "Completed"

        db_session.refresh(batches[1])
        db_session.refresh(batches[2])
        assert batches[1].send_status == "Completed"
        assert batches[2].send_status == "Pending"  # Batch 3 scheduled for 48h remains queued


# =============================================================================
# Task 3: Delivery Reports Accuracy Tests
# =============================================================================

def test_delivery_report_zero_sent_yields_zero_percent_rate(client: TestClient, test_setup_data: dict, db_session: Session):
    """Verify delivery rate is 0.0% when 0 messages sent (never false 100%)."""
    camp = Campaign(
        campaign_name="Zero Delivery Test Campaign",
        template_name="carry_forward_promo",
        template_language="en",
        status="Draft",
        total_leads_selected=0,
        total_leads_eligible=0,
        total_leads_excluded=0,
    )
    db_session.add(camp)
    db_session.flush()

    batches, _ = CampaignService.generate_batches(
        db=db_session,
        campaign_id=camp.id,
        batch_size=4,
    )
    assert len(batches) == 2

    # Fetch report via API
    res = client.get(f"/api/campaigns/{camp.id}/report")
    assert res.status_code == 200
    report = res.json()

    # Total partitioned recipients must match sum of batch recipients (8)
    assert report["total_partitioned_recipients"] == 8
    assert report["total_recipients"] == 8
    assert report["number_of_batches"] == 2
    assert report["batches_total"] == 2
    assert report["pending_approvals"] == 2
    assert report["sent_messages"] == 0
    assert report["delivered_messages"] == 0
    # Delivery rate must be 0.0%
    assert report["delivery_rate"] == 0.0
