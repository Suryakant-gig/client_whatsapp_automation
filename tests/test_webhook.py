"""Comprehensive tests for Meta WhatsApp Webhook integration (Phase 7)."""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.lead import Lead
from app.db.models.message import IncomingMessage, MessageLog
from app.services.webhook_service import WebhookService, mask_phone, sanitize_dict


def compute_hub_signature(body: bytes, secret: str) -> str:
    """Helper to compute X-Hub-Signature-256 header."""
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def build_status_payload(
    message_id: str,
    status: str,
    timestamp: int = 1710000000,
    errors: list = None,
) -> dict:
    """Construct a standard Meta webhook status event payload."""
    status_item = {
        "id": message_id,
        "status": status,
        "timestamp": str(timestamp),
        "recipient_id": "919876543210",
    }
    if errors:
        status_item["errors"] = errors

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "3559058894173825",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "+919853763511",
                                "phone_number_id": "1081975885009463",
                            },
                            "statuses": [status_item],
                        },
                    }
                ],
            }
        ],
    }


def build_message_payload(
    message_id: str,
    from_phone: str,
    msg_type: str = "text",
    content: dict = None,
    timestamp: int = 1710000000,
) -> dict:
    """Construct a standard Meta webhook incoming message event payload."""
    msg_obj = {
        "from": from_phone,
        "id": message_id,
        "timestamp": str(timestamp),
        "type": msg_type,
    }
    if content:
        msg_obj[msg_type] = content
    elif msg_type == "text":
        msg_obj["text"] = {"body": "Hello, I am interested in your Dubai package"}

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "3559058894173825",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "+919853763511",
                                "phone_number_id": "1081975885009463",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Test Customer"},
                                    "wa_id": from_phone,
                                }
                            ],
                            "messages": [msg_obj],
                        },
                    }
                ],
            }
        ],
    }


# ==============================================================================
# 1. Webhook Verification Tests (GET /api/whatsapp/webhook)
# ==============================================================================


def test_webhook_verification_success(client: TestClient):
    """Verify that Meta challenge succeeds with valid verify token and mode."""
    settings = get_settings()
    token = settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN
    challenge = "test_challenge_code_987654"

    response = client.get(
        "/api/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": token,
            "hub.challenge": challenge,
        },
    )

    assert response.status_code == 200
    assert response.text == challenge


def test_webhook_verification_invalid_token(client: TestClient):
    """Verify that Meta challenge is rejected with HTTP 403 on invalid verify token."""
    response = client.get(
        "/api/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token_1234",
            "hub.challenge": "challenge_123",
        },
    )

    assert response.status_code == 403
    assert "verification failed" in response.json()["detail"].lower()


def test_webhook_verification_invalid_mode(client: TestClient):
    """Verify that Meta challenge is rejected when mode is not 'subscribe'."""
    settings = get_settings()
    response = client.get(
        "/api/whatsapp/webhook",
        params={
            "hub.mode": "publish",
            "hub.verify_token": settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN,
            "hub.challenge": "challenge_123",
        },
    )

    assert response.status_code == 403


def test_webhook_verification_missing_params(client: TestClient):
    """Verify that missing challenge parameters are rejected with HTTP 403."""
    response = client.get("/api/whatsapp/webhook")
    assert response.status_code == 403


# ==============================================================================
# 2. Signature Validation Tests (POST /api/whatsapp/webhook)
# ==============================================================================


def test_webhook_signature_valid(client: TestClient):
    """Verify that requests with valid X-Hub-Signature-256 are accepted."""
    settings = get_settings()
    payload = {"object": "whatsapp_business_account", "entry": []}
    body_bytes = json.dumps(payload).encode("utf-8")
    signature = compute_hub_signature(body_bytes, settings.META_APP_SECRET)

    response = client.post(
        "/api/whatsapp/webhook",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_webhook_signature_invalid(client: TestClient):
    """Verify that requests with incorrect signature are rejected with HTTP 401."""
    body_bytes = json.dumps({"object": "whatsapp_business_account"}).encode("utf-8")
    invalid_signature = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

    response = client.post(
        "/api/whatsapp/webhook",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": invalid_signature,
        },
    )

    assert response.status_code == 401
    assert "invalid or missing" in response.json()["detail"].lower()


def test_webhook_signature_missing(client: TestClient):
    """Verify that requests missing X-Hub-Signature-256 header are rejected with HTTP 401."""
    body_bytes = json.dumps({"object": "whatsapp_business_account"}).encode("utf-8")

    response = client.post(
        "/api/whatsapp/webhook",
        content=body_bytes,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401


# ==============================================================================
# 3. Delivery Status Progression and Invariant Tests
# ==============================================================================


def test_delivery_status_sent_preserves_historical_sent_at(client: TestClient, db_session: Session):
    """Verify that a 'sent' status event does not overwrite an existing sent_at timestamp."""
    settings = get_settings()
    historical_time = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)

    # Seed message log with historical sent_at
    msg = MessageLog(
        lead_id=None,
        message_type="template",
        template_name="lead_followup_intro",
        whatsapp_message_id="wamid.test_sent_preservation",
        delivery_status="Accepted",
        api_status="ACCEPTED",
        sent_at=historical_time,
    )
    db_session.add(msg)
    db_session.commit()

    # Webhook arrives with a new timestamp
    payload = build_status_payload("wamid.test_sent_preservation", "sent", timestamp=1710500000)
    body_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_hub_signature(body_bytes, settings.META_APP_SECRET)

    response = client.post(
        "/api/whatsapp/webhook",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert response.status_code == 200

    db_session.refresh(msg)
    assert msg.delivery_status == "Sent"
    # sent_at must NOT be overwritten!
    assert msg.sent_at.replace(tzinfo=timezone.utc) == historical_time


def test_delivery_status_delivered_and_read_progression(client: TestClient, db_session: Session):
    """Verify the normal status lifecycle: Accepted -> Delivered -> Read."""
    settings = get_settings()
    msg = MessageLog(
        lead_id=None,
        message_type="template",
        whatsapp_message_id="wamid.test_progression",
        delivery_status="Accepted",
    )
    db_session.add(msg)
    db_session.commit()

    # 1. Delivered event
    payload_del = build_status_payload("wamid.test_progression", "delivered", timestamp=1710100000)
    body_del = json.dumps(payload_del).encode("utf-8")
    sig_del = compute_hub_signature(body_del, settings.META_APP_SECRET)

    res1 = client.post(
        "/api/whatsapp/webhook",
        content=body_del,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig_del},
    )
    assert res1.status_code == 200

    db_session.refresh(msg)
    assert msg.delivery_status == "Delivered"
    assert msg.delivered_at is not None
    assert msg.read_at is None

    # 2. Read event
    payload_read = build_status_payload("wamid.test_progression", "read", timestamp=1710100100)
    body_read = json.dumps(payload_read).encode("utf-8")
    sig_read = compute_hub_signature(body_read, settings.META_APP_SECRET)

    res2 = client.post(
        "/api/whatsapp/webhook",
        content=body_read,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig_read},
    )
    assert res2.status_code == 200

    db_session.refresh(msg)
    assert msg.delivery_status == "Read"
    assert msg.read_at is not None


def test_delivery_status_failed_preserves_terminal_states(client: TestClient, db_session: Session):
    """Verify that a delayed 'failed' event does NOT overwrite Delivered or Read terminal states."""
    settings = get_settings()

    # Message already Delivered
    msg_delivered = MessageLog(
        lead_id=None,
        message_type="template",
        whatsapp_message_id="wamid.test_delivered_stays_delivered",
        delivery_status="Delivered",
        delivered_at=datetime.now(timezone.utc),
    )
    # Message already Read
    msg_read = MessageLog(
        lead_id=None,
        message_type="template",
        whatsapp_message_id="wamid.test_read_stays_read",
        delivery_status="Read",
        read_at=datetime.now(timezone.utc),
    )
    db_session.add_all([msg_delivered, msg_read])
    db_session.commit()

    # Late failure webhook for delivered message
    fail_errors = [{"code": 131026, "title": "Message undeliverable", "error_data": {"details": "Phone unreachable"}}]
    payload1 = build_status_payload("wamid.test_delivered_stays_delivered", "failed", timestamp=1710200000, errors=fail_errors)
    body1 = json.dumps(payload1).encode("utf-8")
    sig1 = compute_hub_signature(body1, settings.META_APP_SECRET)

    res1 = client.post(
        "/api/whatsapp/webhook",
        content=body1,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig1},
    )
    assert res1.status_code == 200

    db_session.refresh(msg_delivered)
    # Must PRESERVE Delivered status!
    assert msg_delivered.delivery_status == "Delivered"
    assert msg_delivered.failed_at is not None
    assert "131026" in msg_delivered.error_details

    # Late failure webhook for read message
    payload2 = build_status_payload("wamid.test_read_stays_read", "failed", timestamp=1710200100, errors=fail_errors)
    body2 = json.dumps(payload2).encode("utf-8")
    sig2 = compute_hub_signature(body2, settings.META_APP_SECRET)

    res2 = client.post(
        "/api/whatsapp/webhook",
        content=body2,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig2},
    )
    assert res2.status_code == 200

    db_session.refresh(msg_read)
    # Must PRESERVE Read status!
    assert msg_read.delivery_status == "Read"
    assert msg_read.failed_at is not None


def test_delivery_status_failed_marks_non_terminal_messages(client: TestClient, db_session: Session):
    """Verify that a 'failed' event correctly updates messages in non-terminal states (Accepted/Sent)."""
    settings = get_settings()
    msg = MessageLog(
        lead_id=None,
        message_type="template",
        whatsapp_message_id="wamid.test_failure_transition",
        delivery_status="Accepted",
    )
    db_session.add(msg)
    db_session.commit()

    fail_errors = [{"code": 131047, "title": "Re-engagement message"}]
    payload = build_status_payload("wamid.test_failure_transition", "failed", errors=fail_errors)
    body = json.dumps(payload).encode("utf-8")
    sig = compute_hub_signature(body, settings.META_APP_SECRET)

    response = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert response.status_code == 200

    db_session.refresh(msg)
    assert msg.delivery_status == "Failed"
    assert msg.failed_at is not None
    assert "131047" in msg.error_details


def test_out_of_order_status_events(client: TestClient, db_session: Session):
    """Verify that older status events (e.g. Sent) do not regress higher status states (e.g. Delivered)."""
    settings = get_settings()
    msg = MessageLog(
        lead_id=None,
        message_type="template",
        whatsapp_message_id="wamid.test_out_of_order",
        delivery_status="Delivered",
        delivered_at=datetime.now(timezone.utc),
    )
    db_session.add(msg)
    db_session.commit()

    # Late arrival of 'sent' status event
    payload = build_status_payload("wamid.test_out_of_order", "sent")
    body = json.dumps(payload).encode("utf-8")
    sig = compute_hub_signature(body, settings.META_APP_SECRET)

    response = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert response.status_code == 200

    db_session.refresh(msg)
    # Status remains Delivered, not reverted to Sent
    assert msg.delivery_status == "Delivered"


def test_multiple_status_updates_in_single_payload(client: TestClient, db_session: Session):
    """Verify that multiple status notifications inside a single webhook payload are all processed."""
    settings = get_settings()
    msg1 = MessageLog(
        lead_id=None,
        message_type="template",
        whatsapp_message_id="wamid.batch_msg_1",
        delivery_status="Accepted",
    )
    msg2 = MessageLog(
        lead_id=None,
        message_type="template",
        whatsapp_message_id="wamid.batch_msg_2",
        delivery_status="Accepted",
    )
    db_session.add_all([msg1, msg2])
    db_session.commit()

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "3559058894173825",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [
                                {
                                    "id": "wamid.batch_msg_1",
                                    "status": "delivered",
                                    "timestamp": "1710000000",
                                },
                                {
                                    "id": "wamid.batch_msg_2",
                                    "status": "read",
                                    "timestamp": "1710000005",
                                },
                            ],
                        },
                    }
                ],
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    sig = compute_hub_signature(body, settings.META_APP_SECRET)

    response = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert response.status_code == 200
    assert response.json()["processed_statuses"] == 2

    db_session.refresh(msg1)
    db_session.refresh(msg2)
    assert msg1.delivery_status == "Delivered"
    assert msg2.delivery_status == "Read"


# ==============================================================================
# 4. Inbound Customer Message Processing Tests
# ==============================================================================


def test_incoming_text_message_associated_with_lead(client: TestClient, db_session: Session):
    """Verify that an incoming text message correctly links to an existing Lead."""
    settings = get_settings()

    # Create lead with formatted phone
    lead = Lead(
        serial_number=101,
        customer_name="Aarav Sharma",
        phone_number="+919876543210",
        status="Pending",
        opt_in_status="OPTED_IN",
    )
    db_session.add(lead)
    db_session.commit()

    # Meta sends phone number without leading +
    payload = build_message_payload(
        message_id="wamid.inbound_text_001",
        from_phone="919876543210",
        msg_type="text",
        content={"body": "Hello, I want details about the Europe tour"},
    )
    body = json.dumps(payload).encode("utf-8")
    sig = compute_hub_signature(body, settings.META_APP_SECRET)

    response = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert response.status_code == 200
    assert response.json()["processed_messages"] == 1

    inbound = db_session.execute(
        select(IncomingMessage).where(IncomingMessage.whatsapp_message_id == "wamid.inbound_text_001")
    ).scalar_one_or_none()

    assert inbound is not None
    assert inbound.lead_id == lead.id
    assert inbound.sender_phone == "919876543210"
    assert inbound.message_text == "Hello, I want details about the Europe tour"
    assert inbound.message_type == "text"
    assert inbound.processing_status == "RECEIVED"
    assert inbound.raw_payload is not None
    assert "inbound_text_001" in inbound.raw_payload


def test_incoming_non_text_messages(client: TestClient, db_session: Session):
    """Verify safe processing of non-text message types without raising KeyError."""
    settings = get_settings()

    test_cases = [
        ("wamid.img_01", "image", {"caption": "Passport scan", "id": "img123"}, "[Received image message] Passport scan"),
        ("wamid.aud_01", "audio", {"id": "aud123"}, "[Received audio message]"),
        ("wamid.doc_01", "document", {"filename": "tickets.pdf", "caption": "Booking"}, "[Received document message] Booking"),
        ("wamid.btn_01", "button", {"text": "Yes, I am available"}, "Yes, I am available"),
        (
            "wamid.int_01",
            "interactive",
            {"type": "button_reply", "button_reply": {"id": "b1", "title": "Book Now"}},
            "Book Now",
        ),
    ]

    for wa_id, mtype, content, expected_text in test_cases:
        payload = build_message_payload(
            message_id=wa_id,
            from_phone="919111222333",
            msg_type=mtype,
            content=content,
        )
        body = json.dumps(payload).encode("utf-8")
        sig = compute_hub_signature(body, settings.META_APP_SECRET)

        res = client.post(
            "/api/whatsapp/webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert res.status_code == 200

        record = db_session.execute(
            select(IncomingMessage).where(IncomingMessage.whatsapp_message_id == wa_id)
        ).scalar_one_or_none()

        assert record is not None
        assert record.message_type == mtype
        assert record.message_text == expected_text
        assert record.processing_status == "RECEIVED"


def test_incoming_message_unknown_sender(client: TestClient, db_session: Session):
    """Verify that an inbound message from an unknown number is stored with lead_id=None."""
    settings = get_settings()

    payload = build_message_payload(
        message_id="wamid.unknown_sender_001",
        from_phone="919999888777",
        msg_type="text",
        content={"body": "Query from unknown customer"},
    )
    body = json.dumps(payload).encode("utf-8")
    sig = compute_hub_signature(body, settings.META_APP_SECRET)

    response = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert response.status_code == 200

    inbound = db_session.execute(
        select(IncomingMessage).where(IncomingMessage.whatsapp_message_id == "wamid.unknown_sender_001")
    ).scalar_one_or_none()

    assert inbound is not None
    assert inbound.lead_id is None
    assert inbound.sender_phone == "919999888777"


def test_multiple_incoming_messages_in_single_payload(client: TestClient, db_session: Session):
    """Verify that multiple incoming messages in one payload are all persisted."""
    settings = get_settings()

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "3559058894173825",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919100000001",
                                    "id": "wamid.multi_inbound_1",
                                    "timestamp": "1710000000",
                                    "type": "text",
                                    "text": {"body": "First message"},
                                },
                                {
                                    "from": "919100000002",
                                    "id": "wamid.multi_inbound_2",
                                    "timestamp": "1710000001",
                                    "type": "text",
                                    "text": {"body": "Second message"},
                                },
                            ],
                        },
                    }
                ],
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    sig = compute_hub_signature(body, settings.META_APP_SECRET)

    response = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert response.status_code == 200
    assert response.json()["processed_messages"] == 2

    m1 = db_session.execute(
        select(IncomingMessage).where(IncomingMessage.whatsapp_message_id == "wamid.multi_inbound_1")
    ).scalar_one_or_none()
    m2 = db_session.execute(
        select(IncomingMessage).where(IncomingMessage.whatsapp_message_id == "wamid.multi_inbound_2")
    ).scalar_one_or_none()

    assert m1 is not None and m2 is not None


# ==============================================================================
# 5. Idempotency and Deduplication Tests
# ==============================================================================


def test_idempotent_duplicate_incoming_message(client: TestClient, db_session: Session):
    """Verify that duplicate incoming webhook messages do not create duplicate records."""
    settings = get_settings()

    payload = build_message_payload(
        message_id="wamid.idempotent_msg_test",
        from_phone="919123456789",
        msg_type="text",
        content={"body": "Testing idempotency"},
    )
    body = json.dumps(payload).encode("utf-8")
    sig = compute_hub_signature(body, settings.META_APP_SECRET)

    # First send
    res1 = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert res1.status_code == 200

    # Second send of identical message (e.g. Meta retry)
    res2 = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert res2.status_code == 200

    # Assert exactly 1 record in database
    results = db_session.execute(
        select(IncomingMessage).where(IncomingMessage.whatsapp_message_id == "wamid.idempotent_msg_test")
    ).scalars().all()

    assert len(results) == 1


def test_idempotent_duplicate_status_event(client: TestClient, db_session: Session):
    """Verify that duplicate status event deliveries are processed idempotently."""
    settings = get_settings()

    msg = MessageLog(
        lead_id=None,
        message_type="template",
        whatsapp_message_id="wamid.idempotent_status",
        delivery_status="Accepted",
    )
    db_session.add(msg)
    db_session.commit()

    payload = build_status_payload("wamid.idempotent_status", "delivered")
    body = json.dumps(payload).encode("utf-8")
    sig = compute_hub_signature(body, settings.META_APP_SECRET)

    res1 = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert res1.status_code == 200

    res2 = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert res2.status_code == 200

    db_session.refresh(msg)
    assert msg.delivery_status == "Delivered"


def test_unknown_whatsapp_message_id_ignored_safely(client: TestClient, db_session: Session):
    """Verify that a status update for an untracked message ID does not raise an error."""
    settings = get_settings()

    payload = build_status_payload("wamid.untracked_external_message", "delivered")
    body = json.dumps(payload).encode("utf-8")
    sig = compute_hub_signature(body, settings.META_APP_SECRET)

    response = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert response.status_code == 200
    assert response.json()["processed_statuses"] == 0


# ==============================================================================
# 6. Error Handling and Resiliency Tests
# ==============================================================================


def test_malformed_json_payload(client: TestClient):
    """Verify that malformed JSON payloads return HTTP 400 Bad Request."""
    settings = get_settings()
    malformed_body = b"not a valid json {{"
    sig = compute_hub_signature(malformed_body, settings.META_APP_SECRET)

    response = client.post(
        "/api/whatsapp/webhook",
        content=malformed_body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )
    assert response.status_code == 400
    assert "malformed json" in response.json()["detail"].lower()


def test_database_rollback_on_error(client: TestClient):
    """Verify that database transaction rollback is triggered on unexpected processing failure."""
    settings = get_settings()
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"messages": [{"id": "bad"}]}}]}]}
    body = json.dumps(payload).encode("utf-8")
    sig = compute_hub_signature(body, settings.META_APP_SECRET)

    with patch("app.services.webhook_service.WebhookService.process_incoming_message", side_effect=RuntimeError("Simulated DB error")):
        response = client.post(
            "/api/whatsapp/webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert response.status_code == 500
        assert "error processing webhook events" in response.json()["detail"].lower()


# ==============================================================================
# 7. Privacy Masking and Sanitization Unit Tests
# ==============================================================================


def test_privacy_masking_and_payload_sanitization():
    """Verify masking helper and recursive dictionary sanitization for customer protection."""
    # Phone masking
    assert mask_phone("+919876543210") == "+91****10"
    assert mask_phone("123") == "***"
    assert mask_phone(None) == "***"

    # Payload sanitization
    raw = {
        "user_name": "Test",
        "access_token": "secret_token_abc",
        "auth": {"password": "supersecretpassword"},
        "nested": [{"client_secret": "xyz123", "data": "clean"}],
    }
    clean = sanitize_dict(raw)
    assert clean["access_token"] == "[REDACTED]"
    assert clean["auth"]["password"] == "[REDACTED]"
    assert clean["nested"][0]["client_secret"] == "[REDACTED]"
    assert clean["nested"][0]["data"] == "clean"
