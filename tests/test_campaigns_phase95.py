"""Unit and integration tests for Phase 9.5: Campaign Management & Batch Approval endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.campaign import Campaign, CampaignBatch, CampaignRecipient
from app.db.models.lead import Lead
from app.db.models.message import MessageLog
from app.db.models.template import Template


@pytest.fixture
def phase95_templates(db_session: Session) -> dict:
    """Provide approved and pending templates for Phase 9.5 tests."""
    t1 = Template(
        template_name="p95_welcome_offer",
        language="en",
        category="MARKETING",
        approval_status="APPROVED",
        body_text="Hello {{customer_name}}, welcome to our holiday discounts!",
        expected_parameters='["customer_name"]',
    )
    t2 = Template(
        template_name="p95_alternative_offer",
        language="en",
        category="MARKETING",
        approval_status="APPROVED",
        body_text="Hello {{customer_name}}, check out our Maldives special!",
        expected_parameters='["customer_name"]',
    )
    t_unapproved = Template(
        template_name="p95_draft_template",
        language="en",
        category="MARKETING",
        approval_status="PENDING",
        body_text="Draft offer",
    )
    db_session.add_all([t1, t2, t_unapproved])
    db_session.commit()
    return {"approved1": t1, "approved2": t2, "unapproved": t_unapproved}


@pytest.fixture
def phase95_leads(db_session: Session) -> dict:
    """Provide opted-in and ineligible leads."""
    l1 = Lead(
        serial_number=951,
        customer_name="Alok Nath",
        phone_number="+919811111111",
        status="Pending",
        opt_in_status="OPTED_IN",
        opt_in_source="website_inquiry",
    )
    l2 = Lead(
        serial_number=952,
        customer_name="Sunita Rao",
        phone_number="+919822222222",
        status="Replied",
        opt_in_status="OPTED_IN",
        opt_in_source="website_inquiry",
    )
    l_optout = Lead(
        serial_number=953,
        customer_name="Rajesh Kumar",
        phone_number="+919833333333",
        status="Pending",
        opt_in_status="OPTED_OUT",
    )
    l_no_optin = Lead(
        serial_number=954,
        customer_name="Meena Kumari",
        phone_number="+919844444444",
        status="Pending",
        opt_in_status="NOT_OPTED_IN",
    )
    db_session.add_all([l1, l2, l_optout, l_no_optin])
    db_session.commit()
    return {"eligible": [l1, l2], "opted_out": l_optout, "not_opted_in": l_no_optin}


def test_eligible_leads_summary_endpoint(
    client: TestClient, phase95_leads: dict
):
    """GET /api/campaigns/eligible-summary returns accurate candidate counts."""
    res = client.get("/api/campaigns/eligible-summary")
    assert res.status_code == 200
    data = res.json()
    assert "total_leads" in data
    assert "eligible_leads_count" in data
    assert "excluded_leads_count" in data
    assert data["eligible_leads_count"] >= 2
    assert data["excluded_leads_count"] >= 2


def test_campaign_update_name_and_template_success(
    client: TestClient, phase95_templates: dict
):
    """PATCH /api/campaigns/{id} modifies campaign in Draft or Scheduled status."""
    # 1. Create a campaign
    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Phase 95 Update Test Campaign",
            "template_name": "p95_welcome_offer",
            "template_language": "en",
            "auto_generate_batches": False,
        },
    )
    assert create_res.status_code == 201
    c_id = create_res.json()["id"]

    # 2. Update campaign name and switch to another approved template
    patch_res = client.patch(
        f"/api/campaigns/{c_id}",
        json={
            "campaign_name": "Phase 95 Renamed Campaign",
            "template_name": "p95_alternative_offer",
        },
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["campaign_name"] == "Phase 95 Renamed Campaign"
    assert updated["template_name"] == "p95_alternative_offer"


def test_campaign_update_fails_with_unapproved_template(
    client: TestClient, phase95_templates: dict
):
    """PATCH /api/campaigns/{id} rejects updating to an unapproved template."""
    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Phase 95 Unapproved Template Campaign",
            "template_name": "p95_welcome_offer",
            "auto_generate_batches": False,
        },
    )
    c_id = create_res.json()["id"]

    patch_res = client.patch(
        f"/api/campaigns/{c_id}",
        json={"template_name": "p95_draft_template"},
    )
    assert patch_res.status_code == 400
    assert "not APPROVED by Meta" in patch_res.json()["detail"]


def test_campaign_update_blocked_when_in_progress(
    client: TestClient, db_session: Session, phase95_templates: dict
):
    """PATCH /api/campaigns/{id} is prohibited once campaign status is In Progress."""
    camp = Campaign(
        campaign_name="Phase 95 Active Campaign",
        template_name="p95_welcome_offer",
        status="In Progress",
    )
    db_session.add(camp)
    db_session.commit()

    patch_res = client.patch(
        f"/api/campaigns/{camp.id}",
        json={"campaign_name": "Illegal Rename"},
    )
    assert patch_res.status_code == 400
    assert "cannot be modified" in patch_res.json()["detail"]


def test_batch_rejection_workflow(
    client: TestClient, phase95_templates: dict, phase95_leads: dict
):
    """POST /api/campaigns/{c_id}/batches/{b_id}/reject marks batch as Rejected."""
    # 1. Create campaign with batches
    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Phase 95 Batch Rejection Campaign",
            "template_name": "p95_welcome_offer",
            "batch_size": 50,
            "auto_generate_batches": True,
        },
    )
    c_id = create_res.json()["id"]

    # 2. Get batches
    batches_res = client.get(f"/api/campaigns/{c_id}/batches")
    assert batches_res.status_code == 200
    batch = batches_res.json()["items"][0]
    b_id = batch["id"]

    # 3. Reject batch
    reject_res = client.post(f"/api/campaigns/{c_id}/batches/{b_id}/reject")
    assert reject_res.status_code == 200
    rej_data = reject_res.json()
    assert rej_data["approval_status"] == "Rejected"
    assert "rejected" in rej_data["message"].lower()

    # 4. Idempotent check
    reject_repeat = client.post(f"/api/campaigns/{c_id}/batches/{b_id}/reject")
    assert reject_repeat.status_code == 200
    assert reject_repeat.json()["approval_status"] == "Rejected"

    # 5. Attempt to approve rejected batch should fail
    approve_res = client.post(f"/api/campaigns/{c_id}/batches/{b_id}/approve")
    assert approve_res.status_code == 400
    assert "rejected and cannot be approved" in approve_res.json()["detail"]

    # 6. Attempt to send rejected batch should fail
    send_res = client.post(f"/api/campaigns/{c_id}/batches/{b_id}/send")
    assert send_res.status_code == 400
    assert "Mandatory individual approval is required" in send_res.json()["detail"]


def test_cannot_reject_already_approved_batch(
    client: TestClient, phase95_templates: dict, phase95_leads: dict
):
    """POST /api/campaigns/{c_id}/batches/{b_id}/reject fails if batch is already approved."""
    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Phase 95 Cannot Reject Approved Campaign",
            "template_name": "p95_welcome_offer",
            "auto_generate_batches": True,
        },
    )
    c_id = create_res.json()["id"]
    batches_res = client.get(f"/api/campaigns/{c_id}/batches")
    b_id = batches_res.json()["items"][0]["id"]

    # Approve first
    app_res = client.post(f"/api/campaigns/{c_id}/batches/{b_id}/approve")
    assert app_res.status_code == 200

    # Try to reject
    rej_res = client.post(f"/api/campaigns/{c_id}/batches/{b_id}/reject")
    assert rej_res.status_code == 400
    assert "already been approved" in rej_res.json()["detail"]


def test_cross_campaign_batch_endpoints(
    client: TestClient, phase95_templates: dict, phase95_leads: dict
):
    """GET /api/campaigns/batches/all and /batches/pending retrieve global batch lists."""
    # Create two campaigns
    c1 = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Phase 95 Cross Campaign 1",
            "template_name": "p95_welcome_offer",
            "auto_generate_batches": True,
        },
    ).json()

    c2 = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Phase 95 Cross Campaign 2",
            "template_name": "p95_alternative_offer",
            "auto_generate_batches": True,
        },
    ).json()

    # Query all batches
    all_res = client.get("/api/campaigns/batches/all")
    assert all_res.status_code == 200
    all_data = all_res.json()
    assert all_data["total"] >= 2
    assert any(b["campaign_name"] == "Phase 95 Cross Campaign 1" for b in all_data["items"])
    assert any(b["campaign_name"] == "Phase 95 Cross Campaign 2" for b in all_data["items"])

    # Query pending batches
    pending_res = client.get("/api/campaigns/batches/pending")
    assert pending_res.status_code == 200
    pending_data = pending_res.json()
    assert pending_data["total"] >= 2
    assert all(b["approval_status"] == "PENDING_APPROVAL" for b in pending_data["items"])


def test_approved_batch_send_mock_simulation(
    client: TestClient, phase95_templates: dict, phase95_leads: dict
):
    """Approved batch dispatches successfully under OFFLINE (MOCK) mode."""
    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Phase 95 Send Mock Simulation Campaign",
            "template_name": "p95_welcome_offer",
            "auto_generate_batches": True,
        },
    )
    c_id = create_res.json()["id"]
    batches_res = client.get(f"/api/campaigns/{c_id}/batches")
    b_id = batches_res.json()["items"][0]["id"]

    # Approve batch
    app_res = client.post(f"/api/campaigns/{c_id}/batches/{b_id}/approve")
    assert app_res.status_code == 200

    mock_meta_client = AsyncMock()
    mock_meta_client.send_template_message.side_effect = [
        {"success": True, "whatsapp_message_id": "wamid.p95_test_001"},
        {"success": True, "whatsapp_message_id": "wamid.p95_test_002"},
    ]

    with patch("app.services.whatsapp_service.get_whatsapp_client", return_value=mock_meta_client):
        send_res = client.post(f"/api/campaigns/{c_id}/batches/{b_id}/send")
        assert send_res.status_code == 200
        send_data = send_res.json()
        assert send_data["send_status"] == "Completed"
        assert send_data["sent_count"] >= 1
