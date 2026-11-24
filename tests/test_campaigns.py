"""Comprehensive test suite for Campaign Management and Batch Approval (Phase 8)."""

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
def approved_template(db_session: Session) -> Template:
    """Fixture ensuring an approved marketing template exists."""
    template = Template(
        template_name="summer_goa_offer",
        language="en",
        category="MARKETING",
        approval_status="APPROVED",
        body_text="Hi {{customer_name}}, special Goa packages starting at 9999!",
        expected_parameters='["customer_name"]',
        header_type="TEXT",
        header_text="Monsoon Special",
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


@pytest.fixture
def pending_template(db_session: Session) -> Template:
    """Fixture for an unapproved template."""
    template = Template(
        template_name="unapproved_kerala_tour",
        language="en",
        category="MARKETING",
        approval_status="PENDING",
        body_text="Hi {{customer_name}}, visit Kerala!",
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    return template


@pytest.fixture
def sample_leads(db_session: Session) -> dict:
    """Fixture providing leads across various consent and business statuses."""
    # 1. Fully eligible
    lead_ok_1 = Lead(
        serial_number=201,
        customer_name="Priya Sharma",
        phone_number="+919876543201",
        status="Pending",
        opt_in_status="OPTED_IN",
    )
    lead_ok_2 = Lead(
        serial_number=202,
        customer_name="Rohan Verma",
        phone_number="+919876543202",
        status="Pending",
        opt_in_status="OPTED_IN",
    )
    lead_ok_3 = Lead(
        serial_number=203,
        customer_name="Ananya Sen",
        phone_number="+919876543203",
        status="Replied",
        opt_in_status="OPTED_IN",
    )

    # 2. Ineligible: Not opted in
    lead_no_optin = Lead(
        serial_number=204,
        customer_name="Karan Patel",
        phone_number="+919876543204",
        status="Pending",
        opt_in_status="NOT_OPTED_IN",
    )

    # 3. Ineligible: Opted out
    lead_opted_out = Lead(
        serial_number=205,
        customer_name="Sanjay Rao",
        phone_number="+919876543205",
        status="Pending",
        opt_in_status="OPTED_OUT",
    )

    # 4. Ineligible: Not Interested
    lead_not_interested = Lead(
        serial_number=206,
        customer_name="Deepa Roy",
        phone_number="+919876543206",
        status="Not Interested",
        opt_in_status="OPTED_IN",
    )

    # 5. Ineligible: Follow-ups paused
    lead_paused = Lead(
        serial_number=207,
        customer_name="Manoj Das",
        phone_number="+919876543207",
        status="Pending",
        follow_up_paused=True,
        opt_in_status="OPTED_IN",
    )

    # 6. Ineligible: Invalid phone
    lead_bad_phone = Lead(
        serial_number=208,
        customer_name="Vikram Seth",
        phone_number="12345",  # Invalid short phone
        status="Pending",
        opt_in_status="OPTED_IN",
    )

    db_session.add_all([
        lead_ok_1,
        lead_ok_2,
        lead_ok_3,
        lead_no_optin,
        lead_opted_out,
        lead_not_interested,
        lead_paused,
        lead_bad_phone,
    ])
    db_session.commit()

    return {
        "eligible": [lead_ok_1, lead_ok_2, lead_ok_3],
        "no_optin": lead_no_optin,
        "opted_out": lead_opted_out,
        "not_interested": lead_not_interested,
        "paused": lead_paused,
        "bad_phone": lead_bad_phone,
    }


# ==============================================================================
# 1. Campaign Creation & Template Validation Tests
# ==============================================================================


def test_campaign_creation_with_approved_template(client: TestClient, approved_template: Template):
    """Verify campaign is successfully created when template is approved by Meta."""
    response = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Goa Summer Blast 2026",
            "template_name": approved_template.template_name,
            "template_language": "en",
            "auto_generate_batches": False,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["campaign_name"] == "Goa Summer Blast 2026"
    assert data["template_name"] == approved_template.template_name
    assert data["status"] == "Draft"
    assert data["batch_count"] == 0


def test_campaign_creation_rejects_unapproved_template(client: TestClient, pending_template: Template):
    """Verify campaign creation fails if template approval_status is not APPROVED."""
    response = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Kerala Backwaters Special",
            "template_name": pending_template.template_name,
            "template_language": "en",
        },
    )

    assert response.status_code == 400
    assert "not approved" in response.json()["detail"].lower()


def test_campaign_creation_rejects_missing_template(client: TestClient):
    """Verify campaign creation fails if template does not exist."""
    response = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Nonexistent Campaign",
            "template_name": "ghost_template_xyz",
            "template_language": "en",
        },
    )

    assert response.status_code == 400
    assert "not registered" in response.json()["detail"].lower()


# ==============================================================================
# 2. Consent and Lead Eligibility Enforcement Tests
# ==============================================================================


def test_lead_consent_and_eligibility_enforcement(
    client: TestClient,
    approved_template: Template,
    sample_leads: dict,
):
    """Verify that only OPTED_IN leads with valid phones and unpaused status are included."""
    response = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Strict Consent Campaign",
            "template_name": approved_template.template_name,
            "auto_generate_batches": True,
            "batch_size": 50,
        },
    )

    assert response.status_code == 201
    data = response.json()
    # Exactly 3 leads are eligible (lead_ok_1, lead_ok_2, lead_ok_3)
    assert data["total_leads_eligible"] == 3
    # 5 leads are excluded (no_optin, opted_out, not_interested, paused, bad_phone)
    assert data["total_leads_excluded"] == 5
    assert data["total_leads_selected"] == 8
    assert data["batch_count"] == 1


# ==============================================================================
# 3. Configurable Batch Generation Tests
# ==============================================================================


def test_configurable_batch_size_partitioning(
    client: TestClient,
    approved_template: Template,
    db_session: Session,
):
    """Verify configurable batch size splits eligible leads into sequential chunks."""
    # Seed 5 eligible leads
    for i in range(1, 6):
        lead = Lead(
            serial_number=300 + i,
            customer_name=f"Customer {i}",
            phone_number=f"+91980000000{i}",
            status="Pending",
            opt_in_status="OPTED_IN",
        )
        db_session.add(lead)
    db_session.commit()

    # Create campaign with batch_size=2
    response = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Partitioning Test Campaign",
            "template_name": approved_template.template_name,
            "auto_generate_batches": True,
            "batch_size": 2,
        },
    )

    assert response.status_code == 201
    camp_data = response.json()
    assert camp_data["batch_count"] == 3  # 5 leads / 2 = 3 batches (2, 2, 1)

    # Inspect individual batches
    batches_res = client.get(f"/api/campaigns/{camp_data['id']}/batches")
    assert batches_res.status_code == 200
    batch_items = batches_res.json()["items"]
    assert len(batch_items) == 3
    assert batch_items[0]["batch_number"] == 1
    assert batch_items[0]["batch_size"] == 2
    assert batch_items[1]["batch_number"] == 2
    assert batch_items[1]["batch_size"] == 2
    assert batch_items[2]["batch_number"] == 3
    assert batch_items[2]["batch_size"] == 1


def test_batch_size_validation_limits(
    client: TestClient,
    approved_template: Template,
):
    """Verify batch_size validation enforces 1 <= batch_size <= 50."""
    # Test batch_size > 50
    res1 = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Over Limit Batch Campaign",
            "template_name": approved_template.template_name,
            "batch_size": 51,
        },
    )
    assert res1.status_code == 422  # Pydantic validation error

    # Test batch_size <= 0
    res2 = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Zero Limit Batch Campaign",
            "template_name": approved_template.template_name,
            "batch_size": 0,
        },
    )
    assert res2.status_code == 422


def test_prevent_duplicate_recipients_within_campaign(
    client: TestClient,
    approved_template: Template,
    sample_leads: dict,
):
    """Verify that a lead cannot be added more than once across batches of the same campaign."""
    # 1. Create campaign with auto-generation
    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "No Duplicates Campaign",
            "template_name": approved_template.template_name,
            "auto_generate_batches": True,
        },
    )
    camp_id = create_res.json()["id"]

    # 2. Attempt to generate batches again with the exact same eligible leads
    eligible_ids = [l.id for l in sample_leads["eligible"]]
    gen_res = client.post(
        f"/api/campaigns/{camp_id}/generate-batches",
        json={"lead_ids": eligible_ids, "batch_size": 50},
    )

    assert gen_res.status_code == 201
    # No new batches should be created because all leads are already in this campaign
    assert gen_res.json()["total"] == 0


# ==============================================================================
# 4. Mandatory Batch Approval Tests
# ==============================================================================


def test_newly_generated_batch_is_pending_approval(
    client: TestClient,
    approved_template: Template,
    sample_leads: dict,
):
    """Verify newly generated batches default to PENDING_APPROVAL and cannot send."""
    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Pending Approval Verification",
            "template_name": approved_template.template_name,
            "auto_generate_batches": True,
        },
    )
    camp_id = create_res.json()["id"]

    batches_res = client.get(f"/api/campaigns/{camp_id}/batches")
    batch = batches_res.json()["items"][0]

    assert batch["approval_status"] == "PENDING_APPROVAL"
    assert batch["approved_at"] is None
    assert batch["send_status"] == "Pending"


def test_unapproved_batch_cannot_send(
    client: TestClient,
    approved_template: Template,
    sample_leads: dict,
):
    """Verify that sending an unapproved batch returns HTTP 400."""
    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Unapproved Send Rejection",
            "template_name": approved_template.template_name,
            "auto_generate_batches": True,
        },
    )
    camp_id = create_res.json()["id"]
    batch_id = client.get(f"/api/campaigns/{camp_id}/batches").json()["items"][0]["id"]

    # Attempt to send without approving
    send_res = client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/send")
    assert send_res.status_code == 400
    assert "mandatory individual approval is required" in send_res.json()["detail"].lower()


def test_individual_batch_approval_isolation(
    client: TestClient,
    approved_template: Template,
    db_session: Session,
):
    """Verify approving one batch does NOT approve other batches in the campaign."""
    # Seed 4 eligible leads with batch_size=2 -> 2 batches
    for i in range(1, 5):
        db_session.add(
            Lead(
                serial_number=400 + i,
                customer_name=f"Lead {i}",
                phone_number=f"+91981111110{i}",
                status="Pending",
                opt_in_status="OPTED_IN",
            )
        )
    db_session.commit()

    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Approval Isolation Campaign",
            "template_name": approved_template.template_name,
            "auto_generate_batches": True,
            "batch_size": 2,
        },
    )
    camp_id = create_res.json()["id"]
    batches = client.get(f"/api/campaigns/{camp_id}/batches").json()["items"]
    assert len(batches) == 2
    b1_id = batches[0]["id"]
    b2_id = batches[1]["id"]

    # Approve only batch 1
    appr_res = client.post(f"/api/campaigns/{camp_id}/batches/{b1_id}/approve")
    assert appr_res.status_code == 200
    assert appr_res.json()["approval_status"] == "Approved"

    # Re-fetch both batches
    updated_b1 = client.get(f"/api/campaigns/{camp_id}/batches/{b1_id}").json()
    updated_b2 = client.get(f"/api/campaigns/{camp_id}/batches/{b2_id}").json()

    assert updated_b1["approval_status"] == "Approved"
    assert updated_b1["approved_at"] is not None

    # Batch 2 MUST still be PENDING_APPROVAL!
    assert updated_b2["approval_status"] == "PENDING_APPROVAL"
    assert updated_b2["approved_at"] is None


def test_duplicate_approval_is_idempotent(
    client: TestClient,
    approved_template: Template,
    sample_leads: dict,
):
    """Verify approving an already approved batch succeeds idempotently without error."""
    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Idempotent Approval Campaign",
            "template_name": approved_template.template_name,
            "auto_generate_batches": True,
        },
    )
    camp_id = create_res.json()["id"]
    batch_id = client.get(f"/api/campaigns/{camp_id}/batches").json()["items"][0]["id"]

    # First approval
    res1 = client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/approve")
    assert res1.status_code == 200

    # Second approval (idempotent)
    res2 = client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/approve")
    assert res2.status_code == 200
    assert res2.json()["approval_status"] == "Approved"


# ==============================================================================
# 5. Batch Sending & Duplicate Prevention Tests
# ==============================================================================


def test_successful_batch_send_workflow(
    client: TestClient,
    approved_template: Template,
    sample_leads: dict,
    db_session: Session,
):
    """Verify explicit batch sending dispatches messages and records relationships."""
    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Successful Send Campaign",
            "template_name": approved_template.template_name,
            "auto_generate_batches": True,
        },
    )
    camp_id = create_res.json()["id"]
    batch_id = client.get(f"/api/campaigns/{camp_id}/batches").json()["items"][0]["id"]

    # 1. Approve batch
    client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/approve")

    # 2. Mock Meta WhatsApp API client
    mock_meta_client = AsyncMock()
    mock_meta_client.send_template_message.side_effect = [
        {"success": True, "whatsapp_message_id": "wamid.camp_test_001"},
        {"success": True, "whatsapp_message_id": "wamid.camp_test_002"},
        {"success": True, "whatsapp_message_id": "wamid.camp_test_003"},
    ]

    with patch("app.services.whatsapp_service.get_whatsapp_client", return_value=mock_meta_client):
        send_res = client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/send")

    assert send_res.status_code == 200
    result = send_res.json()
    assert result["sent_count"] == 3
    assert result["failed_count"] == 0
    assert result["send_status"] == "Completed"

    # Verify message logs in DB contain campaign_id and batch_id
    logs = db_session.scalars(
        select(MessageLog).where(MessageLog.campaign_id == camp_id)
    ).all()
    assert len(logs) == 3
    for log in logs:
        assert log.batch_id == batch_id
        assert log.delivery_status == "Accepted"
        assert log.api_status == "ACCEPTED"


def test_prevent_duplicate_batch_send(
    client: TestClient,
    approved_template: Template,
    sample_leads: dict,
):
    """Verify attempting to send a batch that has already completed is rejected."""
    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "No Duplicate Sends Campaign",
            "template_name": approved_template.template_name,
            "auto_generate_batches": True,
        },
    )
    camp_id = create_res.json()["id"]
    batch_id = client.get(f"/api/campaigns/{camp_id}/batches").json()["items"][0]["id"]

    client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/approve")

    mock_meta_client = AsyncMock()
    mock_meta_client.send_template_message.return_value = {
        "success": True,
        "whatsapp_message_id": "wamid.dup_prevent_001",
    }

    with patch("app.services.whatsapp_service.get_whatsapp_client", return_value=mock_meta_client):
        res1 = client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/send")
        assert res1.status_code == 200

        # Attempt to send again
        res2 = client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/send")
        assert res2.status_code == 400
        assert "duplicate send request rejected" in res2.json()["detail"].lower()


def test_partial_failure_handling(
    client: TestClient,
    approved_template: Template,
    db_session: Session,
):
    """Verify that if one message in a batch fails, the other messages proceed safely."""
    # Seed 2 leads
    lead1 = Lead(
        serial_number=501,
        customer_name="Success Lead",
        phone_number="+919800000501",
        status="Pending",
        opt_in_status="OPTED_IN",
    )
    lead2 = Lead(
        serial_number=502,
        customer_name="Fail Lead",
        phone_number="+919800000502",
        status="Pending",
        opt_in_status="OPTED_IN",
    )
    db_session.add_all([lead1, lead2])
    db_session.commit()

    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Partial Failure Test",
            "template_name": approved_template.template_name,
            "lead_ids": [lead1.id, lead2.id],
            "batch_size": 2,
        },
    )
    camp_id = create_res.json()["id"]
    batch_id = client.get(f"/api/campaigns/{camp_id}/batches").json()["items"][0]["id"]

    client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/approve")

    # Mock Meta client: First call succeeds, second call fails
    mock_meta_client = AsyncMock()
    mock_meta_client.send_template_message.side_effect = [
        {"success": True, "whatsapp_message_id": "wamid.success_501"},
        RuntimeError("Meta API 500 internal server error"),
    ]

    with patch("app.services.whatsapp_service.get_whatsapp_client", return_value=mock_meta_client):
        send_res = client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/send")

    assert send_res.status_code == 200
    data = send_res.json()
    assert data["sent_count"] == 1
    assert data["failed_count"] == 1
    assert data["send_status"] == "Partially Failed"

    # Check recipient records
    recipients = client.get(f"/api/campaigns/{camp_id}/batches/{batch_id}").json()["recipients"]
    assert len(recipients) == 2
    r_map = {r["lead_id"]: r for r in recipients}
    assert r_map[lead1.id]["send_status"] == "Sent"
    assert r_map[lead2.id]["send_status"] == "Failed"
    assert "Meta API 500" in r_map[lead2.id]["error_details"]


def test_opt_out_between_approval_and_send(
    client: TestClient,
    approved_template: Template,
    db_session: Session,
):
    """Verify that if a customer opts out after approval, immediate pre-send check suppresses them."""
    lead = Lead(
        serial_number=601,
        customer_name="Optout In Flight",
        phone_number="+919800000601",
        status="Pending",
        opt_in_status="OPTED_IN",
    )
    db_session.add(lead)
    db_session.commit()

    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "In Flight Optout Campaign",
            "template_name": approved_template.template_name,
            "lead_ids": [lead.id],
        },
    )
    camp_id = create_res.json()["id"]
    batch_id = client.get(f"/api/campaigns/{camp_id}/batches").json()["items"][0]["id"]

    # Approve batch
    client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/approve")

    # Customer changes their mind and opts out
    lead.opt_in_status = "OPTED_OUT"
    db_session.commit()

    mock_meta_client = AsyncMock()
    with patch("app.services.whatsapp_service.get_whatsapp_client", return_value=mock_meta_client):
        send_res = client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/send")

    assert send_res.status_code == 200
    data = send_res.json()
    assert data["skipped_count"] == 1
    assert data["sent_count"] == 0
    # Meta API must NOT have been called!
    mock_meta_client.send_template_message.assert_not_called()


# ==============================================================================
# 6. Webhook Delivery Status & Reporting Tests
# ==============================================================================


def test_webhook_delivery_status_tracking_for_campaign(
    client: TestClient,
    approved_template: Template,
    sample_leads: dict,
    db_session: Session,
):
    """Verify that Phase 7 webhook delivery status updates are reflected in campaign reporting."""
    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Webhook Campaign Tracking",
            "template_name": approved_template.template_name,
            "lead_ids": [sample_leads["eligible"][0].id],
        },
    )
    camp_id = create_res.json()["id"]
    batch_id = client.get(f"/api/campaigns/{camp_id}/batches").json()["items"][0]["id"]

    client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/approve")

    mock_meta_client = AsyncMock()
    mock_meta_client.send_template_message.return_value = {
        "success": True,
        "whatsapp_message_id": "wamid.camp_webhook_test_99",
    }

    with patch("app.services.whatsapp_service.get_whatsapp_client", return_value=mock_meta_client):
        client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/send")

    # 1. Check report right after API acceptance
    rep1 = client.get(f"/api/campaigns/{camp_id}/report").json()
    assert rep1["accepted_messages"] == 1
    assert rep1["delivered_messages"] == 0

    # 2. Simulate Webhook 'delivered' event from Meta
    from tests.test_webhook import build_status_payload, compute_hub_signature
    from app.core.config import get_settings

    settings = get_settings()
    payload_del = build_status_payload("wamid.camp_webhook_test_99", "delivered")
    body_del = __import__("json").dumps(payload_del).encode("utf-8")
    sig_del = compute_hub_signature(body_del, settings.META_APP_SECRET)

    client.post(
        "/api/whatsapp/webhook",
        content=body_del,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig_del},
    )

    # 3. Check report after webhook
    rep2 = client.get(f"/api/campaigns/{camp_id}/report").json()
    assert rep2["delivered_messages"] == 1


def test_campaign_reporting_metrics(
    client: TestClient,
    approved_template: Template,
    sample_leads: dict,
):
    """Verify complete campaign metrics report."""
    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Full Metrics Report Campaign",
            "template_name": approved_template.template_name,
            "auto_generate_batches": True,
        },
    )
    camp_id = create_res.json()["id"]

    report_res = client.get(f"/api/campaigns/{camp_id}/report")
    assert report_res.status_code == 200
    report = report_res.json()

    assert report["campaign_id"] == camp_id
    assert report["campaign_name"] == "Full Metrics Report Campaign"
    assert report["eligible_leads"] == 3
    assert report["excluded_leads"] == 5
    assert report["number_of_batches"] == 1
    assert report["pending_approvals"] == 1
    assert report["approved_batches"] == 0


def test_failed_recipients_review_endpoint(
    client: TestClient,
    approved_template: Template,
    db_session: Session,
):
    """Verify failed recipients review endpoint lists failure details."""
    lead = Lead(
        serial_number=701,
        customer_name="Failed Customer",
        phone_number="+919800000701",
        status="Pending",
        opt_in_status="OPTED_IN",
    )
    db_session.add(lead)
    db_session.commit()

    create_res = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "Failed Review Campaign",
            "template_name": approved_template.template_name,
            "lead_ids": [lead.id],
        },
    )
    camp_id = create_res.json()["id"]
    batch_id = client.get(f"/api/campaigns/{camp_id}/batches").json()["items"][0]["id"]

    client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/approve")

    # Mock failure
    mock_meta_client = AsyncMock()
    mock_meta_client.send_template_message.side_effect = RuntimeError("Invalid recipient WhatsApp ID")

    with patch("app.services.whatsapp_service.get_whatsapp_client", return_value=mock_meta_client):
        client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/send")

    # Query failed recipients endpoint
    failed_res = client.get(f"/api/campaigns/{camp_id}/failed-recipients")
    assert failed_res.status_code == 200
    failed_list = failed_res.json()
    assert len(failed_list) == 1
    assert failed_list[0]["customer_name"] == "Failed Customer"
    assert "Invalid recipient WhatsApp ID" in failed_list[0]["error_details"]


def test_list_campaigns_and_get_details(
    client: TestClient,
    approved_template: Template,
):
    """Verify listing campaigns with pagination and getting details by ID."""
    res1 = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "List Test Campaign A",
            "template_name": approved_template.template_name,
            "auto_generate_batches": False,
        },
    )
    camp_a_id = res1.json()["id"]

    res2 = client.post(
        "/api/campaigns",
        json={
            "campaign_name": "List Test Campaign B",
            "template_name": approved_template.template_name,
            "auto_generate_batches": False,
        },
    )
    camp_b_id = res2.json()["id"]

    # List campaigns
    list_res = client.get("/api/campaigns?page=1&page_size=10")
    assert list_res.status_code == 200
    data = list_res.json()
    assert data["total"] >= 2
    ids = [c["id"] for c in data["items"]]
    assert camp_a_id in ids
    assert camp_b_id in ids

    # Get single campaign
    get_res = client.get(f"/api/campaigns/{camp_a_id}")
    assert get_res.status_code == 200
    assert get_res.json()["campaign_name"] == "List Test Campaign A"

    # Get non-existent campaign
    not_found = client.get("/api/campaigns/999999")
    assert not_found.status_code == 404


def test_database_rollback_on_campaign_creation_error(
    client: TestClient,
    approved_template: Template,
    db_session: Session,
):
    """Verify that an unexpected error during campaign batch generation rolls back database changes."""
    with patch("app.services.campaign_service.CampaignService.generate_batches", side_effect=RuntimeError("Simulated DB failure")):
        try:
            from app.schemas.campaign_schemas import CampaignCreate
            from app.services.campaign_service import CampaignService
            CampaignService.create_campaign(
                db=db_session,
                payload=CampaignCreate(
                    campaign_name="Rollback Test Campaign",
                    template_name=approved_template.template_name,
                    auto_generate_batches=True,
                ),
            )
        except RuntimeError:
            db_session.rollback()

    # Verify campaign was NOT saved due to rollback
    camp = db_session.scalar(
        select(Campaign).where(Campaign.campaign_name == "Rollback Test Campaign")
    )
    assert camp is None
