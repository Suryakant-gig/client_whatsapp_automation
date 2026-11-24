"""Automated tests for Phase 1 Stabilization:
1. Schedule Timezone IST to UTC Conversion & Due-Batch Dispatch
2. Failed Recipient Audit Log & Delivery Report Synchronization
3. Meta Token 190 Error Handling & Template Sync Verification
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.campaign import Campaign, CampaignBatch, CampaignRecipient
from app.db.models.lead import Lead
from app.db.models.template import Template
from app.integrations.whatsapp.exceptions import WhatsAppAuthError
from app.schemas.campaign_schemas import CampaignCreate
from app.services.campaign_service import CampaignService
from app.services.template_service import TemplateService


@pytest.fixture
def stabilization_data(db_session: Session) -> dict:
    """Setup templates and opted-in leads for stabilization tests."""
    tpl = Template(
        template_name="phase1_test_tmpl",
        language="en",
        category="MARKETING",
        approval_status="APPROVED",
        body_text="Hello {{customer_name}}, greetings from our travel desk!",
        expected_parameters='["customer_name"]',
        header_type="TEXT",
        header_text="Special Travel Alert",
    )
    db_session.add(tpl)

    leads = []
    for i in range(1, 5):
        lead = Lead(
            customer_name=f"Stabilization User {i}",
            phone_number=f"+91911122233{i}",
            opt_in_status="OPTED_IN",
            opt_in_source="API Test",
            status="Pending",
            follow_up_paused=False,
            is_deleted=False,
        )
        db_session.add(lead)
        leads.append(lead)

    db_session.commit()
    return {"template": tpl, "leads": leads}


# =============================================================================
# Task 1: Schedule Timezone IST to UTC Conversion & Due-Batch Dispatch
# =============================================================================

def test_schedule_timezone_ist_to_utc_normalization(db_session: Session, stabilization_data: dict):
    """Verify that timezone-aware schedule strings (e.g. IST +05:30) are normalized to UTC in DB."""
    # 2026-11-21 16:10:00 IST is 2026-11-21 10:40:00 UTC
    ist_time_str = "2026-11-21T16:10:00+05:30"
    payload = CampaignCreate(
        campaign_name="Timezone IST Test Campaign",
        template_name="phase1_test_tmpl",
        template_language="en",
        batch_size=2,
        auto_generate_batches=True,
        scheduled_at=ist_time_str,
    )

    campaign, batches, _ = CampaignService.create_campaign(db_session, payload)
    assert campaign.scheduled_at is not None
    # Stored as UTC: hour must be 10, minute must be 40
    assert campaign.scheduled_at.hour == 10
    assert campaign.scheduled_at.minute == 40
    assert len(batches) == 2
    # Batch scheduled_at must also be normalized to UTC
    for b in batches:
        assert b.scheduled_at is not None
        assert b.scheduled_at.hour == 10
        assert b.scheduled_at.minute == 40


@pytest.mark.skip(
    reason="Campaign polling worker process_due_campaign_batches decommissioned; campaigns are now sent immediately upon manual batch approval."
)
def test_process_due_campaign_batches_respects_utc_timing(db_session: Session, stabilization_data: dict):
    """Verify APScheduler due-batch runner processes only UTC due batches."""
    now_utc = datetime.now(timezone.utc)
    past_due_utc = now_utc - timedelta(minutes=5)
    future_utc = now_utc + timedelta(hours=2)

    # Past due campaign
    campaign_past, batches_past, _ = CampaignService.create_campaign(
        db_session,
        CampaignCreate(
            campaign_name="Past Due Campaign",
            template_name="phase1_test_tmpl",
            template_language="en",
            batch_size=2,
            auto_generate_batches=True,
            scheduled_at=past_due_utc.isoformat(),
        ),
    )
    # Approve first batch so it is ready to dispatch
    batches_past[0].approval_status = "Approved"
    batches_past[0].send_status = "Pending"
    db_session.commit()

    # Future campaign
    campaign_future, batches_future, _ = CampaignService.create_campaign(
        db_session,
        CampaignCreate(
            campaign_name="Future Campaign",
            template_name="phase1_test_tmpl",
            template_language="en",
            batch_size=2,
            auto_generate_batches=True,
            scheduled_at=future_utc.isoformat(),
        ),
    )
    batches_future[0].approval_status = "Approved"
    batches_future[0].send_status = "Pending"
    db_session.commit()

    # Run due batch processor
    processed = CampaignService.process_due_campaign_batches(db_session)
    assert len(processed) >= 1

    # Verify past batch was picked up and dispatched (no longer Pending)
    db_session.refresh(batches_past[0])
    assert batches_past[0].send_status != "Pending"
    assert batches_past[0].send_status in ("Completed", "In Progress", "Partially Failed", "Failed")

    # Verify future batch was NOT picked up (remains Pending)
    db_session.refresh(batches_future[0])
    assert batches_future[0].send_status == "Pending"


# =============================================================================
# Task 2: Failed Recipient Audit Log & Delivery Report Synchronization
# =============================================================================

def test_failed_recipients_audit_log_and_report_sync(client: TestClient, db_session: Session, stabilization_data: dict):
    """Verify failed recipients are returned with full details and match campaign report summary."""
    campaign, batches, _ = CampaignService.create_campaign(
        db_session,
        CampaignCreate(
            campaign_name="Failed Recipient Audit Campaign",
            template_name="phase1_test_tmpl",
            template_language="en",
            batch_size=2,
            auto_generate_batches=True,
        ),
    )
    batch = batches[0]
    batch.approval_status = "Approved"
    db_session.commit()

    # Simulate one recipient failing
    recipients = db_session.query(CampaignRecipient).filter(CampaignRecipient.batch_id == batch.id).all()
    failed_rec = recipients[0]
    failed_rec.send_status = "Failed"
    failed_rec.error_details = "Missing required parameter 'customer_name'"
    batch.failed_messages_count = 1
    batch.send_status = "Partially Failed"
    db_session.commit()

    # 1. Inspect failed-recipients endpoint
    failed_res = client.get(f"/api/campaigns/{campaign.id}/failed-recipients")
    assert failed_res.status_code == 200
    failed_data = failed_res.json()
    assert isinstance(failed_data, list)
    assert len(failed_data) == 1
    item = failed_data[0]
    assert item["phone_number"] == stabilization_data["leads"][0].phone_number
    assert "Missing required parameter" in (item.get("error_details") or item.get("error_message"))

    # 2. Inspect delivery report summary
    report_res = client.get(f"/api/campaigns/{campaign.id}/report")
    assert report_res.status_code == 200
    report_data = report_res.json()
    assert report_data["failed_messages"] == 1
    assert report_data["failed_messages"] == len(failed_data)


# =============================================================================
# Task 3: Meta Token 190 Error Handling & Template Sync Verification
# =============================================================================

def test_meta_sync_mock_mode_response(client: TestClient):
    """Verify that when WHATSAPP_ENABLED=False, /api/templates/sync safely returns mock mode info."""
    res = client.post("/api/templates/sync")
    assert res.status_code == 200
    data = res.json()
    assert data["synced"] is True
    assert data["mock_mode"] is True
    assert "local development mock mode" in data["message"]


def test_meta_sync_expired_token_190_error(client: TestClient):
    """Verify Meta HTTP 401 / error code 190 returns structured HTTP 401 without exposing raw token."""
    secret_token = "EAABtest_secret_meta_token_never_expose"

    mock_settings = get_settings().model_copy()
    mock_settings.WHATSAPP_ENABLED = True
    mock_settings.WHATSAPP_ACCESS_TOKEN = secret_token
    mock_settings.WHATSAPP_BUSINESS_ACCOUNT_ID = "1234567890"

    mock_client = AsyncMock()
    mock_client.fetch_meta_templates.side_effect = WhatsAppAuthError(
        message="Meta Access Token is expired or invalid (Error 190). Please update WHATSAPP_ACCESS_TOKEN in .env with a permanent System User token and restart the server.",
        error_code=190,
    )

    with patch("app.api.routes.templates.get_settings", return_value=mock_settings), \
         patch("app.api.routes.templates.get_whatsapp_client", return_value=mock_client):

        res = client.post("/api/templates/sync")
        assert res.status_code == 401
        data = res.json()
        detail = data.get("detail", "")
        assert "Error 190" in detail
        assert "permanent System User token" in detail
        # Verify secret token is never exposed in response
        assert secret_token not in str(data)


def test_meta_template_submit_expired_token_190_error(client: TestClient):
    """Verify Meta HTTP 401 / error code 190 during template submit returns structured HTTP 401."""
    secret_token = "EAABtest_secret_meta_token_never_expose"

    mock_settings = get_settings().model_copy()
    mock_settings.WHATSAPP_ENABLED = True
    mock_settings.WHATSAPP_ACCESS_TOKEN = secret_token
    mock_settings.WHATSAPP_BUSINESS_ACCOUNT_ID = "1234567890"

    mock_client = AsyncMock()
    mock_client.create_meta_template.side_effect = WhatsAppAuthError(
        message="Meta Access Token is expired or invalid (Error 190). Please update WHATSAPP_ACCESS_TOKEN in .env with a permanent System User token and restart the server.",
        error_code=190,
    )

    with patch("app.api.routes.templates.get_settings", return_value=mock_settings), \
         patch("app.api.routes.templates.get_whatsapp_client", return_value=mock_client):

        payload = {
            "template_name": "test_auth_error_tmpl",
            "category": "MARKETING",
            "language": "en",
            "body_text": "Hello world {{1}}",
        }
        res = client.post("/api/templates", json=payload)
        assert res.status_code == 401
        data = res.json()
        detail = data.get("detail", "")
        assert "Error 190" in detail
        assert "permanent System User token" in detail
        # Verify secret token is never exposed
        assert secret_token not in str(data)
