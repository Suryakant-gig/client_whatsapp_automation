"""Automated test suite for Phase 6: Meta WhatsApp Cloud API Integration.

Tests cover:
1. Missing WhatsApp credentials
2. Invalid configuration (disabled toggle)
3. Valid template payload format matching Meta Cloud API
4. Unapproved template rejection
5. Missing template parameters rejection
6. Invalid phone number rejection
7. Paused lead rejection
8. Not Interested lead rejection
9. Missing consent / opt-in rejection (and opt-out suppression)
10. Successful Meta API response
11. Extraction and storage of WhatsApp message ID
12. API authentication failure (401/403)
13. Rate limiting (429)
14. Timeout handling
15. Server errors (500+)
16. Duplicate message ID prevention
17. API acceptance versus delivery-status distinction (Accepted vs Delivered)
18. Scheduler integration with WhatsAppMessageSender
19. Follow-up count updates only after API acceptance
20. No duplicate sends after uncertain API outcomes
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models.follow_up import FollowUpSchedule
from app.db.models.lead import Lead
from app.db.models.message import MessageLog
from app.db.models.template import Template
from app.integrations.whatsapp.client import WhatsAppCloudClient
from app.integrations.whatsapp.exceptions import (
    TemplateNotApprovedError,
    TemplateValidationError,
    WhatsAppAPIError,
    WhatsAppAuthError,
    WhatsAppConfigError,
    WhatsAppConsentError,
    WhatsAppRateLimitError,
    WhatsAppServerError,
    WhatsAppTimeoutError,
)
from app.services.followup_service import FollowUpService
from app.services.sender_boundary import WhatsAppMessageSender
from app.services.template_service import TemplateService
from app.services.whatsapp_service import WhatsAppService


# Helper fixtures & factories
def create_mock_settings(
    enabled: bool = True,
    token: str = "EAAG_TEST_TOKEN_12345",
    phone_id: str = "109876543210",
    api_version: str = "v21.0",
    base_url: str = "https://graph.facebook.com",
    timeout: float = 10.0,
) -> Settings:
    """Return Settings instance with mock WhatsApp Cloud API configuration."""
    return Settings(
        WHATSAPP_ENABLED=enabled,
        WHATSAPP_ACCESS_TOKEN=token,
        WHATSAPP_PHONE_NUMBER_ID=phone_id,
        WHATSAPP_API_VERSION=api_version,
        WHATSAPP_API_BASE_URL=base_url,
        WHATSAPP_REQUEST_TIMEOUT_SECONDS=timeout,
    )


def create_mock_client(
    handler,
    settings: Settings,
) -> WhatsAppCloudClient:
    """Create a WhatsAppCloudClient with custom httpx.MockTransport."""
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return WhatsAppCloudClient(settings=settings, http_client=http_client)


# ==============================================================================
# 1. Missing WhatsApp credentials
# ==============================================================================
@pytest.mark.anyio
async def test_missing_whatsapp_credentials() -> None:
    """1. Test that missing token or phone number ID raises WhatsAppConfigError."""
    # Empty token
    settings_no_token = create_mock_settings(enabled=True, token="", phone_id="123456")
    client_no_token = WhatsAppCloudClient(settings=settings_no_token)
    with pytest.raises(WhatsAppConfigError) as exc_info:
        await client_no_token.send_template_message(
            to="+919876543210",
            template_name="welcome_message",
        )
    assert "access token is not configured" in str(exc_info.value)

    # Empty phone number ID
    settings_no_phone = create_mock_settings(enabled=True, token="token_abc", phone_id="")
    client_no_phone = WhatsAppCloudClient(settings=settings_no_phone)
    with pytest.raises(WhatsAppConfigError) as exc_info2:
        await client_no_phone.send_template_message(
            to="+919876543210",
            template_name="welcome_message",
        )
    assert "phone number ID is not configured" in str(exc_info2.value)


# ==============================================================================
# 2. Invalid configuration (disabled toggle)
# ==============================================================================
@pytest.mark.anyio
async def test_invalid_configuration_disabled() -> None:
    """2. Test that WHATSAPP_ENABLED=False rejects send attempts with WhatsAppConfigError."""
    settings_disabled = create_mock_settings(enabled=False, token="token", phone_id="12345")
    client = WhatsAppCloudClient(settings=settings_disabled)

    with pytest.raises(WhatsAppConfigError) as exc_info:
        await client.send_template_message(
            to="+919876543210",
            template_name="welcome_message",
        )
    assert "disabled" in str(exc_info.value).lower()


# ==============================================================================
# 3. Valid template payload format matching Meta Cloud API
# ==============================================================================
@pytest.mark.anyio
async def test_valid_template_payload_structure() -> None:
    """3. Verify outgoing HTTP payload strictly matches Meta Graph API template format."""
    captured_request = {}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_request["url"] = str(request.url)
        captured_request["headers"] = dict(request.headers)
        captured_request["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": "919876543210", "wa_id": "919876543210"}],
                "messages": [{"id": "wamid.TEST_PAYLOAD_123"}],
            },
        )

    settings = create_mock_settings()
    client = create_mock_client(mock_handler, settings)

    components = [
        {"type": "header", "parameters": [{"type": "text", "text": "Special Deal"}]},
        {"type": "body", "parameters": [{"type": "text", "text": "Rahul"}, {"type": "text", "text": "Goa"}]},
    ]

    result = await client.send_template_message(
        to="+919876543210",
        template_name="travel_followup",
        language_code="en_US",
        components=components,
    )

    assert result["whatsapp_message_id"] == "wamid.TEST_PAYLOAD_123"

    # Verify Meta endpoint URL: /{version}/{phone_number_id}/messages
    assert captured_request["url"] == "https://graph.facebook.com/v21.0/109876543210/messages"
    assert captured_request["headers"]["authorization"] == "Bearer EAAG_TEST_TOKEN_12345"

    body = captured_request["body"]
    assert body["messaging_product"] == "whatsapp"
    assert body["recipient_type"] == "individual"
    assert body["to"] == "919876543210"  # Normalized E.164 digits
    assert body["type"] == "template"
    assert body["template"]["name"] == "travel_followup"
    assert body["template"]["language"]["code"] == "en_US"
    assert len(body["template"]["components"]) == 2
    assert body["template"]["components"][0]["type"] == "header"
    assert body["template"]["components"][1]["type"] == "body"


# ==============================================================================
# 4. Unapproved template rejection
# ==============================================================================
def test_unapproved_template_rejection(db_session: Session) -> None:
    """4. Test that unapproved templates (PENDING/REJECTED) are rejected."""
    # Register pending template
    pending_tmpl = Template(
        template_name="pending_promo",
        language="en",
        category="MARKETING",
        approval_status="PENDING",
    )
    db_session.add(pending_tmpl)
    db_session.commit()

    with pytest.raises(TemplateNotApprovedError) as exc_info:
        TemplateService.build_components(pending_tmpl, parameters={"name": "Alice"})
    assert "PENDING" in str(exc_info.value)

    # Register rejected template
    rejected_tmpl = Template(
        template_name="rejected_promo",
        language="en",
        category="MARKETING",
        approval_status="REJECTED",
    )
    db_session.add(rejected_tmpl)
    db_session.commit()

    with pytest.raises(TemplateNotApprovedError) as exc_info2:
        TemplateService.build_components(rejected_tmpl, parameters={"name": "Bob"})
    assert "REJECTED" in str(exc_info2.value)


# ==============================================================================
# 5. Missing template parameters rejection
# ==============================================================================
def test_missing_template_parameters(db_session: Session) -> None:
    """5. Test that missing or empty required parameters raise TemplateValidationError."""
    tmpl = Template(
        template_name="booking_confirm",
        language="en",
        category="UTILITY",
        approval_status="APPROVED",
        expected_parameters=json.dumps(["customer_name", "destination"]),
    )
    db_session.add(tmpl)
    db_session.commit()

    # Mismatched parameter key
    with pytest.raises(TemplateValidationError) as exc1:
        TemplateService.build_components(tmpl, parameters={"customer_name": "Sita"})
    assert "destination" in str(exc1.value)

    # Empty parameter value
    with pytest.raises(TemplateValidationError) as exc2:
        TemplateService.build_components(tmpl, parameters={"customer_name": "Sita", "destination": "   "})
    assert "cannot be empty" in str(exc2.value)

    # Completely omitted parameters
    with pytest.raises(TemplateValidationError) as exc3:
        TemplateService.build_components(tmpl, parameters=None)
    assert "requires parameters" in str(exc3.value)


# ==============================================================================
# 6. Invalid phone number rejection
# ==============================================================================
@pytest.mark.anyio
async def test_invalid_phone_number_rejection(db_session: Session) -> None:
    """6. Test that invalid phone number on lead fails validation before API call."""
    lead = Lead(
        customer_name="Invalid Phone Lead",
        phone_number="12345",  # Too short
        opt_in_status="OPTED_IN",
    )
    db_session.add(lead)
    db_session.commit()

    with pytest.raises(ValueError) as exc:
        await WhatsAppService.send_template_message(
            db=db_session,
            lead_id=lead.id,
            template_name="test_tmpl",
        )
    assert "invalid phone number" in str(exc.value).lower()


# ==============================================================================
# 7. Paused lead rejection
# ==============================================================================
@pytest.mark.anyio
async def test_paused_lead_rejection(db_session: Session) -> None:
    """7. Test that messages cannot be sent to leads with follow_up_paused=True."""
    lead = Lead(
        customer_name="Paused Customer",
        phone_number="+919876543210",
        follow_up_paused=True,
        opt_in_status="OPTED_IN",
    )
    db_session.add(lead)
    db_session.commit()

    with pytest.raises(WhatsAppAPIError) as exc:
        await WhatsAppService.send_template_message(
            db=db_session,
            lead_id=lead.id,
            template_name="test_tmpl",
        )
    assert "paused" in str(exc.value).lower()


# ==============================================================================
# 8. Not Interested lead rejection
# ==============================================================================
@pytest.mark.anyio
async def test_not_interested_lead_rejection(db_session: Session) -> None:
    """8. Test that messages cannot be sent to leads with status='Not Interested'."""
    lead = Lead(
        customer_name="Uninterested Lead",
        phone_number="+919876543211",
        status="Not Interested",
        opt_in_status="OPTED_IN",
    )
    db_session.add(lead)
    db_session.commit()

    with pytest.raises(WhatsAppAPIError) as exc:
        await WhatsAppService.send_template_message(
            db=db_session,
            lead_id=lead.id,
            template_name="test_tmpl",
        )
    assert "not interested" in str(exc.value).lower()


# ==============================================================================
# 9. Missing consent / opt-in rejection (and opt-out suppression)
# ==============================================================================
@pytest.mark.anyio
async def test_missing_consent_rejection(db_session: Session) -> None:
    """9. Test that recipients without documented consent or with opt-out are rejected."""
    # Case A: Not opted-in
    lead_no_consent = Lead(
        customer_name="No Consent Lead",
        phone_number="+919876543212",
        opt_in_status="NOT_OPTED_IN",
    )
    db_session.add(lead_no_consent)
    db_session.commit()

    with pytest.raises(WhatsAppConsentError) as exc_a:
        await WhatsAppService.send_template_message(
            db=db_session,
            lead_id=lead_no_consent.id,
            template_name="test_tmpl",
        )
    assert "opt-in consent" in str(exc_a.value).lower()

    # Case B: Opted-out
    lead_opted_out = Lead(
        customer_name="Opted Out Lead",
        phone_number="+919876543213",
        opt_in_status="OPTED_OUT",
    )
    db_session.add(lead_opted_out)
    db_session.commit()

    with pytest.raises(WhatsAppConsentError) as exc_b:
        await WhatsAppService.send_template_message(
            db=db_session,
            lead_id=lead_opted_out.id,
            template_name="test_tmpl",
        )
    assert "opted out" in str(exc_b.value).lower()


# ==============================================================================
# 10. Successful Meta API response
# ==============================================================================
@pytest.mark.anyio
async def test_successful_meta_api_response() -> None:
    """10. Test handling of successful Meta Graph API HTTP 200 response."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": "919876543210", "wa_id": "919876543210"}],
                "messages": [{"id": "wamid.HBgLMjA2MTIzNA=="}],
            },
        )

    settings = create_mock_settings()
    client = create_mock_client(mock_handler, settings)

    res = await client.send_template_message(
        to="+919876543210",
        template_name="welcome_message",
    )

    assert res["api_status"] == "ACCEPTED"
    assert res["whatsapp_message_id"] == "wamid.HBgLMjA2MTIzNA=="


# ==============================================================================
# 11. Extraction and storage of WhatsApp message ID
# ==============================================================================
@pytest.mark.anyio
async def test_extraction_and_storage_of_whatsapp_message_id(db_session: Session) -> None:
    """11. Verify WhatsApp message ID is extracted and stored in MessageLog."""
    lead = Lead(
        customer_name="Vikas Kumar",
        phone_number="+919876543214",
        opt_in_status="OPTED_IN",
    )
    template = Template(
        template_name="vacation_update",
        language="en",
        category="UTILITY",
        approval_status="APPROVED",
    )
    db_session.add_all([lead, template])
    db_session.commit()

    wa_id_expected = "wamid.EXTRACT_TEST_998877"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"messages": [{"id": wa_id_expected}]},
        )

    settings = create_mock_settings()
    client = create_mock_client(mock_handler, settings)

    log = await WhatsAppService.send_template_message(
        db=db_session,
        lead_id=lead.id,
        template_name="vacation_update",
        client=client,
    )

    assert log.whatsapp_message_id == wa_id_expected
    assert log.api_status == "ACCEPTED"

    # Query DB directly to verify persistence
    persisted = db_session.get(MessageLog, log.id)
    assert persisted is not None
    assert persisted.whatsapp_message_id == wa_id_expected


# ==============================================================================
# 12. API authentication failure (401/403)
# ==============================================================================
@pytest.mark.anyio
async def test_api_authentication_failure() -> None:
    """12. Test that Meta API 401 raises WhatsAppAuthError without revealing tokens."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {
                    "message": "Invalid OAuth access token - Cannot parse access token",
                    "type": "OAuthException",
                    "code": 190,
                    "fbtrace_id": "AbCdEfGh123",
                }
            },
        )

    settings = create_mock_settings()
    client = create_mock_client(mock_handler, settings)

    with pytest.raises(WhatsAppAuthError) as exc_info:
        await client.send_template_message(
            to="+919876543210",
            template_name="test_tmpl",
        )
    assert exc_info.value.error_code == 190
    assert "authentication failed" in str(exc_info.value).lower()
    # Ensure sensitive secret token is not in exception message
    assert settings.WHATSAPP_ACCESS_TOKEN not in str(exc_info.value)


# ==============================================================================
# 13. Rate limiting (429)
# ==============================================================================
@pytest.mark.anyio
async def test_rate_limiting_handling() -> None:
    """13. Test that Meta API 429 response raises WhatsAppRateLimitError with Retry-After."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "60"},
            json={
                "error": {
                    "message": "(#130429) Rate limit hit for this phone number",
                    "type": "OAuthException",
                    "code": 130429,
                }
            },
        )

    settings = create_mock_settings()
    client = create_mock_client(mock_handler, settings)

    with pytest.raises(WhatsAppRateLimitError) as exc_info:
        await client.send_template_message(
            to="+919876543210",
            template_name="test_tmpl",
        )
    assert exc_info.value.retry_after == 60
    assert "rate limit" in str(exc_info.value).lower()


# ==============================================================================
# 14. Timeout handling
# ==============================================================================
@pytest.mark.anyio
async def test_timeout_handling() -> None:
    """14. Test that client network timeouts raise WhatsAppTimeoutError."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out after 10s")

    settings = create_mock_settings()
    client = create_mock_client(mock_handler, settings)

    with pytest.raises(WhatsAppTimeoutError) as exc_info:
        await client.send_template_message(
            to="+919876543210",
            template_name="test_tmpl",
        )
    assert "timed out" in str(exc_info.value).lower()


# ==============================================================================
# 15. Server errors (500+)
# ==============================================================================
@pytest.mark.anyio
async def test_server_errors_handling() -> None:
    """15. Test that Meta 500/503 responses raise WhatsAppServerError."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": {"message": "Service Temporarily Unavailable", "code": 2}},
        )

    settings = create_mock_settings()
    client = create_mock_client(mock_handler, settings)

    with pytest.raises(WhatsAppServerError) as exc_info:
        await client.send_template_message(
            to="+919876543210",
            template_name="test_tmpl",
        )
    assert exc_info.value.status_code == 503
    assert "server error" in str(exc_info.value).lower()


# ==============================================================================
# 16. Duplicate message ID prevention
# ==============================================================================
def test_duplicate_message_id_prevention(db_session: Session) -> None:
    """16. Verify that duplicate WhatsApp message ID cannot be inserted into MessageLog."""
    lead = Lead(
        customer_name="Dupe Test Lead",
        phone_number="+919876543215",
        opt_in_status="OPTED_IN",
    )
    db_session.add(lead)
    db_session.commit()

    wa_id = "wamid.DUPLICATE_GUARD_123"

    log1 = MessageLog(
        lead_id=lead.id,
        message_type="template",
        whatsapp_message_id=wa_id,
        delivery_status="Accepted",
        api_status="ACCEPTED",
    )
    db_session.add(log1)
    db_session.commit()

    # Attempt second insertion with same whatsapp_message_id
    log2 = MessageLog(
        lead_id=lead.id,
        message_type="template",
        whatsapp_message_id=wa_id,
        delivery_status="Accepted",
        api_status="ACCEPTED",
    )
    db_session.add(log2)

    with pytest.raises(Exception):  # IntegrityError on UniqueConstraint
        db_session.commit()
    db_session.rollback()


# ==============================================================================
# 17. API acceptance versus delivery-status distinction
# ==============================================================================
@pytest.mark.anyio
async def test_api_acceptance_vs_delivery_status_distinction(db_session: Session) -> None:
    """17. Critical: API acceptance must set status='Accepted', NEVER 'Delivered'."""
    lead = Lead(
        customer_name="Status Check Lead",
        phone_number="+919876543216",
        opt_in_status="OPTED_IN",
    )
    template = Template(
        template_name="status_check_tmpl",
        language="en",
        category="MARKETING",
        approval_status="APPROVED",
    )
    db_session.add_all([lead, template])
    db_session.commit()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": [{"id": "wamid.ACCEPTED_NOT_DELIVERED"}]})

    settings = create_mock_settings()
    client = create_mock_client(mock_handler, settings)

    log = await WhatsAppService.send_template_message(
        db=db_session,
        lead_id=lead.id,
        template_name="status_check_tmpl",
        client=client,
    )

    # Must be 'Accepted', not 'Delivered' (Phase 7 webhooks will handle delivery confirmation)
    assert log.delivery_status == "Accepted"
    assert log.api_status == "ACCEPTED"
    assert log.delivery_status != "Delivered"


# ==============================================================================
# 18. Scheduler integration with WhatsAppMessageSender
# ==============================================================================
def test_scheduler_integration_with_whatsapp_sender(db_session: Session) -> None:
    """18. Test that scheduler dispatches due follow-ups using WhatsAppMessageSender."""
    lead = Lead(
        customer_name="Scheduler WhatsApp Lead",
        phone_number="+919876543217",
        opt_in_status="OPTED_IN",
    )
    template = Template(
        template_name="follow_up_general",
        language="en",
        category="UTILITY",
        approval_status="APPROVED",
    )
    db_session.add_all([lead, template])
    db_session.commit()

    # Create due schedule
    due_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    schedule = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=due_time,
        status="Scheduled",
    )
    db_session.add(schedule)
    db_session.commit()

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": [{"id": "wamid.SCHEDULER_SEND_1"}]})

    settings = create_mock_settings()
    mock_client = create_mock_client(mock_handler, settings)
    sender = WhatsAppMessageSender(client=mock_client, template_name="follow_up_general")

    sent, skipped, failed = FollowUpService.process_due_schedules(db=db_session, sender=sender)

    assert sent == 1
    assert skipped == 0
    assert failed == 0

    # Verify schedule state
    db_session.refresh(schedule)
    assert schedule.status == "Sent"
    assert schedule.processed_at is not None

    # Verify MessageLog recorded
    msg = db_session.scalar(
        select(MessageLog).where(MessageLog.whatsapp_message_id == "wamid.SCHEDULER_SEND_1")
    )
    assert msg is not None
    assert msg.lead_id == lead.id
    assert msg.delivery_status == "Accepted"


# ==============================================================================
# 19. Follow-up count updates only after API acceptance
# ==============================================================================
def test_followup_count_updates_only_after_send(db_session: Session) -> None:
    """19. Verify lead's sent follow-up count increments strictly on success, not failure."""
    lead = Lead(
        customer_name="Count Check Lead",
        phone_number="+919876543218",
        opt_in_status="OPTED_IN",
        max_follow_up_limit=3,
    )
    template = Template(
        template_name="follow_up_general",
        language="en",
        category="UTILITY",
        approval_status="APPROVED",
    )
    db_session.add_all([lead, template])
    db_session.commit()

    initial_count = FollowUpService.get_sent_count(db_session, lead.id)
    assert initial_count == 0

    # 1. Execute a failed attempt
    def fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "Internal error"}})

    settings = create_mock_settings()
    fail_client = create_mock_client(fail_handler, settings)
    fail_sender = WhatsAppMessageSender(client=fail_client)

    sched1 = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        status="Scheduled",
    )
    db_session.add(sched1)
    db_session.commit()

    FollowUpService.process_due_schedules(db=db_session, sender=fail_sender)
    assert FollowUpService.get_sent_count(db_session, lead.id) == 0  # Still 0 after failure!

    # 2. Execute a successful attempt
    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": [{"id": "wamid.COUNT_INCREMENT_OK"}]})

    ok_client = create_mock_client(ok_handler, settings)
    ok_sender = WhatsAppMessageSender(client=ok_client)

    sched2 = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=2,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        status="Scheduled",
    )
    db_session.add(sched2)
    db_session.commit()

    FollowUpService.process_due_schedules(db=db_session, sender=ok_sender)
    assert FollowUpService.get_sent_count(db_session, lead.id) == 1  # Incremented to 1!


# ==============================================================================
# 20. No duplicate sends after uncertain API outcomes
# ==============================================================================
def test_no_duplicate_sends_after_uncertain_api_outcomes(db_session: Session) -> None:
    """20. Test that timeouts or failed sends mark status='Failed' and are NOT re-polled as due."""
    lead = Lead(
        customer_name="Uncertain Lead",
        phone_number="+919876543219",
        opt_in_status="OPTED_IN",
    )
    template = Template(
        template_name="follow_up_general",
        language="en",
        category="UTILITY",
        approval_status="APPROVED",
    )
    db_session.add_all([lead, template])
    db_session.commit()

    due_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    schedule = FollowUpSchedule(
        lead_id=lead.id,
        sequence_number=1,
        scheduled_at=due_time,
        status="Scheduled",
    )
    db_session.add(schedule)
    db_session.commit()

    call_count = 0

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("Timeout communicating with Meta")

    settings = create_mock_settings()
    timeout_client = create_mock_client(timeout_handler, settings)
    sender = WhatsAppMessageSender(client=timeout_client)

    # First poll cycle: Encounter timeout
    sent, skipped, failed = FollowUpService.process_due_schedules(db=db_session, sender=sender)
    assert failed == 1
    assert call_count == 1

    db_session.refresh(schedule)
    assert schedule.status == "Failed"
    assert "timed out" in schedule.skip_reason.lower()

    # Second poll cycle: Because status is 'Failed' (not Scheduled/Approved), it must NOT be re-processed
    sent2, skipped2, failed2 = FollowUpService.process_due_schedules(db=db_session, sender=sender)
    assert sent2 == 0
    assert skipped2 == 0
    assert failed2 == 0
    assert call_count == 1  # No secondary attempt triggered!


# ==============================================================================
# 21. API Endpoints Integration (FastAPI TestClient)
# ==============================================================================
def test_api_template_registration_and_send(client: TestClient, db_session: Session) -> None:
    """Integration test verifying template registration and direct send API endpoint."""
    # 1. Register template via API
    res_tmpl = client.post(
        "/api/templates",
        json={
            "template_name": "festive_greeting",
            "language": "en",
            "category": "MARKETING",
            "approval_status": "APPROVED",
            "body_text": "Hello {{1}}, check our {{2}} packages!",
            "expected_parameters": ["customer_name", "package_name"],
        },
    )
    assert res_tmpl.status_code == 201
    tmpl_data = res_tmpl.json()
    assert tmpl_data["template_name"] == "festive_greeting"

    # 2. Create lead with consent
    res_lead = client.post(
        "/api/leads",
        json={
            "customer_name": "Ananya Roy",
            "phone_number": "+919876543220",
            "opt_in_status": "OPTED_IN",
            "opt_in_source": "web_form",
        },
    )
    assert res_lead.status_code == 201
    lead_id = res_lead.json()["id"]

    # 3. Send template message via API with mock client
    def mock_send(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": [{"id": "wamid.API_INTEG_TEST_101"}]})

    settings = create_mock_settings()
    mock_wa_client = create_mock_client(mock_send, settings)

    with patch("app.api.routes.whatsapp.WhatsAppService.send_template_message") as mock_service_send:
        # Simulate successful service return
        now_utc = datetime.now(timezone.utc)
        mock_log = MessageLog(
            id=101,
            lead_id=lead_id,
            message_type="template",
            template_name="festive_greeting",
            whatsapp_message_id="wamid.API_INTEG_TEST_101",
            delivery_status="Accepted",
            api_status="ACCEPTED",
            sent_at=now_utc,
            created_at=now_utc,
        )
        mock_service_send.return_value = mock_log

        send_res = client.post(
            "/api/whatsapp/send-template",
            json={
                "lead_id": lead_id,
                "template_name": "festive_greeting",
                "parameters": {"customer_name": "Ananya", "package_name": "Kashmir Summer"},
            },
        )
        assert send_res.status_code == 200
        send_data = send_res.json()
        assert send_data["success"] is True
        assert send_data["whatsapp_message_id"] == "wamid.API_INTEG_TEST_101"
        assert send_data["delivery_status"] == "Accepted"
