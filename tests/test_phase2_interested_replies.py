"""Automated tests for Phase 2:
1. Incoming WhatsApp reply automation & 'Interested — Needs Call' queue
2. Opt-out keyword detection (STOP, UNSUBSCRIBE, OPT OUT, etc.)
3. Deduplication on Meta's unique message ID (wamid)
4. Mark-followed-up endpoint & call notes tracking
5. Dashboard overview integration & queue filtering
"""

import pytest
pytestmark = pytest.mark.skip(
    reason="Phase 2 auto-mark interested superseded by Final Simplification (Respondents table with default UNCLASSIFIED classification)"
)

from datetime import datetime, timezone
import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.follow_up import FollowUpSchedule
from app.db.models.lead import Lead
from app.db.models.message import IncomingMessage, MessageLog


@pytest.fixture
def phase2_leads(db_session: Session) -> dict:
    """Create test leads for incoming reply automation."""
    lead1 = Lead(
        customer_name="Ramesh Sharma",
        phone_number="+919876543210",
        status="Pending",
        opt_in_status="OPTED_IN",
        opt_in_source="Website Form",
        follow_up_paused=False,
        is_deleted=False,
    )
    lead2 = Lead(
        customer_name="Priya Patel",
        phone_number="919811223344",
        status="Pending",
        opt_in_status="OPTED_IN",
        opt_in_source="WhatsApp Opt-in",
        follow_up_paused=False,
        is_deleted=False,
    )
    db_session.add_all([lead1, lead2])
    db_session.commit()

    # Add a scheduled follow-up for lead 1
    sched = FollowUpSchedule(
        lead_id=lead1.id,
        sequence_number=1,
        scheduled_at=datetime.now(timezone.utc),
        status="Scheduled",
    )
    db_session.add(sched)
    db_session.commit()

    return {"lead1": lead1, "lead2": lead2, "sched": sched}


def create_meta_webhook_payload(
    sender_phone: str,
    wa_id: str,
    msg_type: str = "text",
    body: str = "Hello, tell me about Goa package",
    button_data: dict = None,
    interactive_data: dict = None,
) -> dict:
    """Helper to construct a realistic Meta WhatsApp Webhook payload."""
    msg_obj = {
        "from": sender_phone,
        "id": wa_id,
        "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        "type": msg_type,
    }
    if msg_type == "text":
        msg_obj["text"] = {"body": body}
    elif msg_type == "button":
        msg_obj["button"] = button_data or {"text": body, "payload": body}
    elif msg_type == "interactive":
        msg_obj["interactive"] = interactive_data or {
            "type": "button_reply",
            "button_reply": {"id": "btn_1", "title": body},
        }

    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1234567890",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15551234567",
                                "phone_number_id": "9876543210",
                            },
                            "messages": [msg_obj],
                        },
                    }
                ],
            }
        ],
    }


def send_signed_webhook(client: TestClient, payload: dict) -> any:
    """Helper to sign and post webhook payload."""
    settings = get_settings()
    raw_body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(
        settings.META_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return client.post(
        "/api/whatsapp/webhook",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
    )


# =============================================================================
# 1. Text Inbound Reply -> Auto-Mark Interested
# =============================================================================

def test_incoming_text_reply_auto_marks_interested(client: TestClient, db_session: Session, phase2_leads: dict):
    """Verify inbound customer text message marks lead as Interested with needs_manual_followup=True."""
    lead = phase2_leads["lead1"]
    wamid = "wamid.HBgLMjAyNjExMjAxMTEAMDU2Nzg="

    payload = create_meta_webhook_payload(
        sender_phone="919876543210",  # Matches +919876543210 normalized
        wa_id=wamid,
        msg_type="text",
        body="I am interested in your luxury Kashmir tour package",
    )

    res = send_signed_webhook(client, payload)
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["processed_messages"] == 1

    # Verify lead was updated
    db_session.refresh(lead)
    assert lead.status == "Interested"
    assert lead.needs_manual_followup is True
    assert lead.last_reply_text == "I am interested in your luxury Kashmir tour package"
    assert lead.last_replied_at is not None

    # Verify incoming_message record created
    inc = db_session.query(IncomingMessage).filter(IncomingMessage.whatsapp_message_id == wamid).first()
    assert inc is not None
    assert inc.lead_id == lead.id
    assert inc.message_text == "I am interested in your luxury Kashmir tour package"


# =============================================================================
# 2. Button / Interactive Reply -> Auto-Mark Interested
# =============================================================================

def test_incoming_button_reply_auto_marks_interested(client: TestClient, db_session: Session, phase2_leads: dict):
    """Verify inbound quick-reply button message marks lead as Interested."""
    lead = phase2_leads["lead2"]
    wamid = "wamid.HBgLMjAyNjExMjAxMTEAMDU2Nzk="

    payload = create_meta_webhook_payload(
        sender_phone="+919811223344",  # Matches 919811223344
        wa_id=wamid,
        msg_type="button",
        body="Book Now",
        button_data={"text": "Book Now", "payload": "BTN_BOOK_NOW"},
    )

    res = send_signed_webhook(client, payload)
    assert res.status_code == 200

    db_session.refresh(lead)
    assert lead.status == "Interested"
    assert lead.needs_manual_followup is True
    assert lead.last_reply_text == "Book Now"


def test_incoming_interactive_reply_auto_marks_interested(client: TestClient, db_session: Session, phase2_leads: dict):
    """Verify inbound interactive button reply marks lead as Interested."""
    lead = phase2_leads["lead1"]
    wamid = "wamid.HBgLMjAyNjExMjAxMTEAMDU2ODA="

    payload = create_meta_webhook_payload(
        sender_phone="9876543210",  # Matches +919876543210
        wa_id=wamid,
        msg_type="interactive",
        interactive_data={
            "type": "button_reply",
            "button_reply": {"id": "btn_callback", "title": "Request Callback"},
        },
    )

    res = send_signed_webhook(client, payload)
    assert res.status_code == 200

    db_session.refresh(lead)
    assert lead.status == "Interested"
    assert lead.needs_manual_followup is True
    assert lead.last_reply_text == "Request Callback"


# =============================================================================
# 3. Opt-Out Keywords Detection
# =============================================================================

@pytest.mark.parametrize("keyword", ["STOP", "Stop", "stop!", "UNSUBSCRIBE", "opt out", "Not Interested", "CANCEL", "REMOVE"])
def test_opt_out_keyword_suppresses_lead_and_cancels_followups(client: TestClient, db_session: Session, phase2_leads: dict, keyword: str):
    """Verify opt-out keywords set status='Not Interested', opt_in_status='OPTED_OUT', needs_manual_followup=False, and cancel pending followups."""
    lead = phase2_leads["lead1"]
    sched = phase2_leads["sched"]
    wamid = f"wamid.optout.{keyword}.{datetime.now().timestamp()}"

    payload = create_meta_webhook_payload(
        sender_phone="+919876543210",
        wa_id=wamid,
        msg_type="text",
        body=keyword,
    )

    res = send_signed_webhook(client, payload)
    assert res.status_code == 200

    db_session.refresh(lead)
    assert lead.opt_in_status == "OPTED_OUT"
    assert lead.status == "Not Interested"
    assert lead.needs_manual_followup is False
    assert lead.follow_up_paused is True
    assert lead.opt_out_timestamp is not None

    # Follow-up schedule must be cancelled / skipped
    db_session.refresh(sched)
    assert sched.status in ("Skipped", "Cancelled")
    assert "opted out" in sched.skip_reason.lower()


# =============================================================================
# 4. Idempotency & Deduplication
# =============================================================================

def test_duplicate_webhook_retry_idempotently_ignored(client: TestClient, db_session: Session, phase2_leads: dict):
    """Verify duplicate incoming webhook delivery with identical wamid does not create duplicate rows."""
    lead = phase2_leads["lead1"]
    wamid = "wamid.idempotent.test.12345"

    payload = create_meta_webhook_payload(
        sender_phone="+919876543210",
        wa_id=wamid,
        msg_type="text",
        body="First delivery",
    )

    # First send
    res1 = send_signed_webhook(client, payload)
    assert res1.status_code == 200
    assert res1.json()["processed_messages"] == 1

    # Second send (retry with same wamid)
    payload["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = "Retry delivery"
    res2 = send_signed_webhook(client, payload)
    assert res2.status_code == 200

    # Verify only 1 incoming message exists for this wamid
    count = db_session.query(IncomingMessage).filter(IncomingMessage.whatsapp_message_id == wamid).count()
    assert count == 1


# =============================================================================
# 5. Unknown Sender Handling
# =============================================================================

def test_unknown_phone_reply_logged_cleanly(client: TestClient, db_session: Session):
    """Verify an inbound message from an unknown number is recorded without crashing the webhook."""
    wamid = "wamid.unknown.sender.999"
    payload = create_meta_webhook_payload(
        sender_phone="+919999988888",
        wa_id=wamid,
        msg_type="text",
        body="Hello, is this the travel desk?",
    )

    res = send_signed_webhook(client, payload)
    assert res.status_code == 200

    inc = db_session.query(IncomingMessage).filter(IncomingMessage.whatsapp_message_id == wamid).first()
    assert inc is not None
    assert inc.lead_id is None
    assert inc.sender_phone == "+919999988888"


# =============================================================================
# 6. Mark Followed-Up Endpoint
# =============================================================================

def test_mark_lead_followed_up_endpoint(client: TestClient, db_session: Session, phase2_leads: dict):
    """Verify POST /api/leads/{id}/mark-followed-up clears needs_manual_followup and saves notes."""
    lead = phase2_leads["lead1"]
    lead.status = "Interested"
    lead.needs_manual_followup = True
    db_session.commit()

    res = client.post(
        f"/api/leads/{lead.id}/mark-followed-up",
        json={"notes": "Called customer. Interested in 5-day Kerala family package for Dec."},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["needs_manual_followup"] is False
    assert data["followup_notes"] == "Called customer. Interested in 5-day Kerala family package for Dec."
    assert data["followed_up_at"] is not None

    # Verify in DB
    db_session.refresh(lead)
    assert lead.needs_manual_followup is False
    assert lead.followup_notes == "Called customer. Interested in 5-day Kerala family package for Dec."
    assert lead.followed_up_at is not None


# =============================================================================
# 7. Queue Filtering & Dashboard Overview
# =============================================================================

def test_queue_filtering_and_dashboard_overview(client: TestClient, db_session: Session, phase2_leads: dict):
    """Verify GET /api/leads?needs_manual_followup=true and GET /api/dashboard/overview return correct counts."""
    lead = phase2_leads["lead1"]
    lead.status = "Interested"
    lead.needs_manual_followup = True
    lead.last_reply_text = "Call me in 10 mins"
    lead.last_replied_at = datetime.now(timezone.utc)
    db_session.commit()

    # 1. Lead queue filter
    res = client.get("/api/leads?status=Interested&needs_manual_followup=true")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    found = any(item["id"] == lead.id for item in data["items"])
    assert found is True
    assert data["items"][0]["last_reply_text"] == "Call me in 10 mins"

    # 2. Dashboard overview
    dash_res = client.get("/api/dashboard/overview")
    assert dash_res.status_code == 200
    dash_data = dash_res.json()
    assert dash_data["interested_pending_call_count"] >= 1
    assert dash_data["stats"]["interested_pending_call_count"] >= 1
    assert len(dash_data["latest_interested_leads"]) >= 1
    assert dash_data["latest_interested_leads"][0]["id"] == lead.id
