"""Phase 9.4 Lead Management E2E Verification Script."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import SessionLocal
from app.services.auth_service import AuthService
from app.db.models import Lead, FollowUpSchedule, MessageLog, IncomingMessage
from datetime import datetime, timezone, timedelta


def verify_phase94():
    print("=== Running Phase 9.4 Verification ===")
    client = TestClient(app)

    # 1. Verify unauthenticated access to /dashboard/leads redirects to /login
    resp = client.get("/dashboard/leads", follow_redirects=False)
    assert resp.status_code == 303, f"Expected 303 redirect, got {resp.status_code}"
    assert resp.headers["location"] == "/login"
    print("✓ [PASS] Unauthenticated access to /dashboard/leads redirected to /login (303)")

    # 2. Authenticate admin user
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "StrongAdminPassword2026!"},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    session_cookie = login_resp.cookies.get("travel_crm_session")
    csrf_token = login_resp.cookies.get("travel_crm_csrf")
    assert session_cookie, "Missing session cookie"
    assert csrf_token, "Missing CSRF cookie"
    print("✓ [PASS] Admin successfully authenticated, session & CSRF cookies acquired")

    # 3. Verify authenticated access to /dashboard/leads returns frontend HTML
    dash_resp = client.get("/dashboard/leads")
    assert dash_resp.status_code == 200
    html = dash_resp.text
    assert "leadsContainer" in html, "Missing #leadsContainer in index.html"
    assert "leadsTable" in html, "Missing #leadsTable in index.html"
    assert "leadDetailModal" in html, "Missing #leadDetailModal in index.html"
    assert "leadEditModal" in html, "Missing #leadEditModal in index.html"
    assert "leadConsentModal" in html, "Missing #leadConsentModal in index.html"
    assert "leadCreateModal" in html, "Missing #leadCreateModal in index.html"
    assert "/static/js/leads.js" in html, "Missing script tag for leads.js in index.html"
    print("✓ [PASS] Authenticated access to /dashboard/leads renders Lead Management shell and modals")

    # 4. Verify static assets
    js_resp = client.get("/static/js/leads.js")
    assert js_resp.status_code == 200
    assert "LeadsManager" in js_resp.text
    print("✓ [PASS] /static/js/leads.js served successfully with LeadsManager controller")

    # 5. Verify lead creation with consent rules
    headers = {"X-CSRF-Token": csrf_token}
    phone_test = "+919999900010"

    # Clean up any existing test lead with this phone number to ensure idempotency
    with SessionLocal() as db:
        existing = db.query(Lead).filter(Lead.phone_number == phone_test).first()
        if existing:
            db.delete(existing)
            db.commit()

    # Create lead without opt_in_source when OPTED_IN -> Must fail (422)
    bad_lead_resp = client.post(
        "/api/leads",
        json={
            "customer_name": "Test Consent Lead",
            "phone_number": phone_test,
            "opt_in_status": "OPTED_IN",
        },
        headers=headers,
    )
    assert bad_lead_resp.status_code == 422
    print("✓ [PASS] POST /api/leads with OPTED_IN and missing opt_in_source rejected with 422")

    # Create lead with valid opt_in_source

    good_lead_resp = client.post(
        "/api/leads",
        json={
            "customer_name": "Test Consent Lead",
            "phone_number": phone_test,
            "serial_number": "VERIFY-P94-01",
            "opt_in_status": "OPTED_IN",
            "opt_in_source": "website_booking_form",
        },
        headers=headers,
    )
    assert good_lead_resp.status_code == 201, f"Create failed: {good_lead_resp.text}"
    lead_id = good_lead_resp.json()["id"]
    print(f"✓ [PASS] POST /api/leads with valid opt_in_source created lead #{lead_id}")

    # 6. Verify lead listing with consent filter
    list_resp = client.get("/api/leads?opt_in_status=OPTED_IN&search=VERIFY-P94")
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) >= 1
    assert items[0]["id"] == lead_id
    print("✓ [PASS] GET /api/leads filtered by opt_in_status=OPTED_IN and search term")

    # 7. Add follow-up schedule and message logs to lead, then test detail view
    with SessionLocal() as db:
        sched = FollowUpSchedule(
            lead_id=lead_id,
            sequence_number=1,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            status="Scheduled",
            attempt_number=1,
        )
        ts = int(datetime.now(timezone.utc).timestamp())
        msg = MessageLog(
            lead_id=lead_id,
            message_type="template",
            template_name="welcome_pack",
            whatsapp_message_id=f"wamid.VERIFY_{lead_id}_{ts}",
            delivery_status="Delivered",
        )
        incoming = IncomingMessage(
            lead_id=lead_id,
            whatsapp_message_id=f"wamid.IN_{lead_id}_{ts}",
            sender_phone=phone_test,
            message_text="Please share hotel details",
            message_type="text",
            received_at=datetime.now(timezone.utc),
            processing_status="PROCESSED",
        )
        db.add_all([sched, msg, incoming])
        db.commit()

    detail_resp = client.get(f"/api/leads/{lead_id}/detail")
    assert detail_resp.status_code == 200
    det = detail_resp.json()
    assert det["id"] == lead_id
    assert det["opt_in_source"] == "website_booking_form"
    assert len(det["follow_up_schedules"]) >= 1
    assert len(det["message_logs"]) >= 1
    assert len(det["incoming_messages"]) >= 1
    print("✓ [PASS] GET /api/leads/{id}/detail returns complete lead info, schedules, and message logs")

    # 8. Test Pause / Resume follow-ups
    pause_resp = client.post(f"/api/leads/{lead_id}/pause-followups", headers=headers)
    assert pause_resp.status_code == 200
    assert pause_resp.json()["follow_up_paused"] is True
    print("✓ [PASS] POST /api/leads/{id}/pause-followups paused follow-ups")

    resume_resp = client.post(f"/api/leads/{lead_id}/resume-followups", headers=headers)
    assert resume_resp.status_code == 200
    assert resume_resp.json()["follow_up_paused"] is False
    print("✓ [PASS] POST /api/leads/{id}/resume-followups resumed follow-ups")

    # 9. Test updating consent to OPTED_OUT
    opt_out_resp = client.post(
        f"/api/leads/{lead_id}/consent",
        json={"opt_in_status": "OPTED_OUT"},
        headers=headers,
    )
    assert opt_out_resp.status_code == 200
    assert opt_out_resp.json()["opt_in_status"] == "OPTED_OUT"
    assert opt_out_resp.json()["opt_out_timestamp"] is not None
    print("✓ [PASS] POST /api/leads/{id}/consent updated to OPTED_OUT with opt_out_timestamp")

    print("\n=== All Phase 9.4 Verification Checks Passed Successfully ===")


if __name__ == "__main__":
    verify_phase94()
