"""Tests for Phase 9.7: Campaign Targeting, Scheduling, and Meta Template Integration."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.campaign import Campaign, CampaignBatch, CampaignRecipient
from app.db.models.lead import Lead
from app.db.models.template import Template
from app.services.campaign_service import CampaignService


@pytest.fixture
def targeting_leads_and_templates(db_session: Session) -> dict:
    """Provide verified leads and templates for targeting and scheduling tests."""
    # Template
    tpl = Template(
        template_name="p97_special_promo",
        language="en",
        category="MARKETING",
        approval_status="APPROVED",
        body_text="Hi {{customer_name}}, get 20% off on your holiday!",
        expected_parameters='["customer_name"]',
    )
    db_session.add(tpl)

    # 4 Opted-in leads
    leads = []
    for i in range(1, 5):
        l = Lead(
            customer_name=f"Consented Lead {i}",
            phone_number=f"+91987654320{i}",
            opt_in_status="OPTED_IN",
            opt_in_source="Website Form",
            status="Pending",
            follow_up_paused=False,
            is_deleted=False,
        )
        db_session.add(l)
        leads.append(l)

    # 1 Ineligible lead (Not Opted In)
    ineligible = Lead(
        customer_name="Non Consented Lead",
        phone_number="+919876543299",
        opt_in_status="NOT_OPTED_IN",
        status="Pending",
        follow_up_paused=False,
        is_deleted=False,
    )
    db_session.add(ineligible)
    db_session.commit()

    return {"template": tpl, "leads": leads, "ineligible": ineligible}


def test_get_eligible_leads_endpoint(client: TestClient, targeting_leads_and_templates: dict):
    """Verify GET /api/campaigns/eligible-leads returns only consented, eligible leads."""
    response = client.get("/api/campaigns/eligible-leads")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 4
    # Ensure all returned leads have opt_in_status == OPTED_IN
    for item in data:
        assert item["opt_in_status"] == "OPTED_IN"
        assert item["phone_number"]


def test_create_campaign_with_max_recipients(
    client: TestClient, db_session: Session, targeting_leads_and_templates: dict
):
    """Verify max_recipients caps the total candidate recipients partitioned."""
    payload = {
        "campaign_name": "Capped Broadcast Test",
        "template_name": "p97_special_promo",
        "template_language": "en",
        "batch_size": 2,
        "max_recipients": 2,  # Cap to 2 leads despite 4 available
        "auto_generate_batches": True,
    }
    response = client.post("/api/campaigns", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["total_leads_eligible"] == 2
    assert data["batch_count"] == 1  # 2 leads in 1 batch of size 2


def test_create_campaign_with_specific_lead_ids(
    client: TestClient, db_session: Session, targeting_leads_and_templates: dict
):
    """Verify selecting specific lead_ids targets only those chosen leads."""
    target_leads = targeting_leads_and_templates["leads"][:2]
    selected_ids = [l.id for l in target_leads]

    payload = {
        "campaign_name": "Specific Leads Targeted Broadcast",
        "template_name": "p97_special_promo",
        "template_language": "en",
        "batch_size": 50,
        "lead_ids": selected_ids,
        "auto_generate_batches": True,
    }
    response = client.post("/api/campaigns", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["total_leads_eligible"] == 2
    assert data["total_leads_selected"] == 2


def test_create_campaign_with_scheduled_at(
    client: TestClient, db_session: Session, targeting_leads_and_templates: dict
):
    """Verify scheduled_at timestamp is saved and campaign status is Scheduled."""
    future_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    payload = {
        "campaign_name": "Scheduled Promo Campaign",
        "template_name": "p97_special_promo",
        "template_language": "en",
        "batch_size": 50,
        "scheduled_at": future_time,
        "auto_generate_batches": True,
    }
    response = client.post("/api/campaigns", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "Scheduled"
    assert data["scheduled_at"] is not None


@pytest.mark.skip(
    reason="Campaign polling worker process_due_campaign_batches decommissioned; campaigns are now sent immediately upon manual batch approval."
)
def test_process_due_campaign_batches_scheduler_dispatch(
    db_session: Session, targeting_leads_and_templates: dict
):
    """Verify APScheduler worker dispatches approved batches whose scheduled_at has arrived."""
    past_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    lead = targeting_leads_and_templates["leads"][0]

    # Create campaign scheduled in the past
    campaign = Campaign(
        campaign_name="Due Scheduled Campaign",
        template_name="p97_special_promo",
        template_language="en",
        status="Scheduled",
        scheduled_at=past_time,
        total_leads_selected=1,
        total_leads_eligible=1,
        total_leads_excluded=0,
    )
    db_session.add(campaign)
    db_session.flush()

    batch = CampaignBatch(
        campaign_id=campaign.id,
        batch_number=1,
        batch_size=50,
        approval_status="Approved",  # Approved by administrator
        approved_at=past_time,
        send_status="Pending",
        total_messages_count=1,
    )
    db_session.add(batch)
    db_session.flush()

    recipient = CampaignRecipient(
        batch_id=batch.id,
        lead_id=lead.id,
        send_status="Pending",
    )
    db_session.add(recipient)
    db_session.commit()

    # Mock WhatsApp Cloud Client to ensure ZERO live messages are dispatched
    mock_client = AsyncMock()
    mock_client.send_template_message.return_value = {
        "whatsapp_message_id": "mock_sched_msg_999",
        "api_status": "ACCEPTED",
        "raw_response": {"messages": [{"id": "mock_sched_msg_999"}]},
    }

    results = CampaignService.process_due_campaign_batches(
        db=db_session,
        now_utc=datetime.now(timezone.utc),
        client=mock_client,
    )

    assert len(results) == 1
    db_session.refresh(batch)
    assert batch.send_status == "Completed"
    assert batch.sent_messages_count == 1
    assert mock_client.send_template_message.called


def test_templates_endpoint_approved_fallback(client: TestClient):
    """Verify GET /api/templates?approval_status=APPROVED returns list of approved templates."""
    response = client.get("/api/templates?approval_status=APPROVED")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert isinstance(data["items"], list)
    assert len(data["items"]) > 0
    for tpl in data["items"]:
        assert tpl["approval_status"] == "APPROVED"
        assert tpl["template_name"]
