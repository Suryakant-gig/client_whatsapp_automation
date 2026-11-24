"""End-to-End Verification Script for Phase 9.5: Campaign & Batch Approval Endpoint Integration."""

import os
import sys
from datetime import datetime, timezone

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_current_user, verify_csrf
from app.db.models.campaign import Campaign, CampaignBatch, CampaignRecipient
from app.db.models.lead import Lead
from app.db.models.template import Template
from app.db.models.user import User
from app.db.session import SessionLocal, get_db
from app.main import app


def run_verification():
    print("=====================================================================")
    print("   PHASE 9.5: CAMPAIGN & BATCH APPROVAL ENDPOINT INTEGRATION VERIFICATION")
    print("=====================================================================")

    db = SessionLocal()
    try:
        # 1. Setup authenticated client with real database session
        admin = db.scalar(select(User).where(User.username == "admin"))
        if not admin:
            from app.core.security import hash_password
            admin = User(
                username="admin",
                password_hash=hash_password("StrongAdminPassword2026!"),
                role="admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)

        from app.core.config import get_settings
        from app.services.auth_service import AuthService

        settings = get_settings()
        user_sess, raw_token = AuthService.create_session(db, admin)

        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[verify_csrf] = lambda: True

        client = TestClient(app)
        client.cookies.set(settings.SESSION_COOKIE_NAME, raw_token)
        client.cookies.set(settings.CSRF_COOKIE_NAME, "verify_csrf_secret")
        client.headers.update({"X-CSRF-Token": "verify_csrf_secret"})
        print("[OK] Admin session created and cookies configured.")

        # 2. Ensure an approved template exists
        tpl_name = "phase95_verified_template"
        tpl = db.scalar(select(Template).where(Template.template_name == tpl_name))
        if not tpl:
            tpl = Template(
                template_name=tpl_name,
                language="en",
                category="MARKETING",
                approval_status="APPROVED",
                body_text="Hi {{customer_name}}, exclusive Goa holiday package starting at 9999!",
                expected_parameters='["customer_name"]',
            )
            db.add(tpl)
            db.commit()
            db.refresh(tpl)
        print(f"[OK] 1. Verified Meta-approved WhatsApp template: {tpl.template_name}")

        # 3. Ensure candidate leads exist across all consent statuses
        # Clean up existing test leads with these phones
        test_phones = ["+919999999501", "+919999999502", "+919999999503", "+919999999504"]
        db.query(Lead).filter(Lead.phone_number.in_(test_phones)).delete(synchronize_session=False)
        db.commit()

        lead_opted_in1 = Lead(
            serial_number="E2E-951",
            customer_name="Pooja Batra",
            phone_number="+919999999501",
            status="Pending",
            opt_in_status="OPTED_IN",
            opt_in_source="website_inquiry",
        )
        lead_opted_in2 = Lead(
            serial_number="E2E-952",
            customer_name="Sameer Khanna",
            phone_number="+919999999502",
            status="Replied",
            opt_in_status="OPTED_IN",
            opt_in_source="website_inquiry",
        )
        lead_opted_out = Lead(
            serial_number="E2E-953",
            customer_name="Anil Kapoor",
            phone_number="+919999999503",
            status="Pending",
            opt_in_status="OPTED_OUT",
        )
        lead_no_optin = Lead(
            serial_number="E2E-954",
            customer_name="Kavita Seth",
            phone_number="+919999999504",
            status="Pending",
            opt_in_status="NOT_OPTED_IN",
        )
        db.add_all([lead_opted_in1, lead_opted_in2, lead_opted_out, lead_no_optin])
        db.commit()
        db.refresh(lead_opted_in1)
        db.refresh(lead_opted_in2)
        print("[OK] 2. Seeded candidate leads with varying consent and status.")

        # 4. Test Eligibility Summary Endpoint
        res_summary = client.get("/api/campaigns/eligible-summary")
        assert res_summary.status_code == 200, f"Expected 200, got {res_summary.status_code}"
        sum_data = res_summary.json()
        assert sum_data["eligible_leads_count"] >= 2
        print(f"[OK] 3. Eligible leads summary verified: {sum_data['eligible_leads_count']} eligible, {sum_data['excluded_leads_count']} excluded.")

        # 5. Test Campaign Creation
        camp_name = f"E2E Holiday Broadcast {datetime.now(timezone.utc).strftime('%H%M%S')}"
        res_create = client.post(
            "/api/campaigns",
            json={
                "campaign_name": camp_name,
                "template_name": tpl_name,
                "template_language": "en",
                "batch_size": 50,
                "auto_generate_batches": True,
            },
        )
        assert res_create.status_code == 201, f"Expected 201, got {res_create.status_code}: {res_create.text}"
        camp_data = res_create.json()
        camp_id = camp_data["id"]
        assert camp_data["campaign_name"] == camp_name
        assert camp_data["total_leads_eligible"] >= 2
        print(f"[OK] 4. Created Campaign ID #{camp_id} with name '{camp_name}'.")

        # 6. Test Campaign Editing (Draft/Scheduled status)
        renamed = f"{camp_name} (Updated)"
        res_patch = client.patch(
            f"/api/campaigns/{camp_id}",
            json={"campaign_name": renamed},
        )
        assert res_patch.status_code == 200, f"Expected 200, got {res_patch.status_code}: {res_patch.text}"
        assert res_patch.json()["campaign_name"] == renamed
        print(f"[OK] 5. Edited Campaign successfully: Renamed to '{renamed}'.")

        # 7. Test Campaign Batches Query
        res_batches = client.get(f"/api/campaigns/{camp_id}/batches")
        assert res_batches.status_code == 200
        batches_list = res_batches.json()["items"]
        assert len(batches_list) >= 1
        batch_id = batches_list[0]["id"]
        assert batches_list[0]["approval_status"] == "PENDING_APPROVAL"
        print(f"[OK] 6. Retrieved Campaign Batches: Batch ID #{batch_id} in status PENDING_APPROVAL.")

        # 8. Test Global Batches Endpoint for Batch Approvals page
        res_all_batches = client.get("/api/campaigns/batches/all?approval_status=Pending")
        assert res_all_batches.status_code == 200
        pending_items = res_all_batches.json()["items"]
        assert any(b["id"] == batch_id for b in pending_items)
        print(f"[OK] 7. Cross-campaign pending batches endpoint verified with {len(pending_items)} items.")

        # 9. Test Batch Details & Recipients
        res_batch_detail = client.get(f"/api/campaigns/{camp_id}/batches/{batch_id}")
        assert res_batch_detail.status_code == 200
        recipients = res_batch_detail.json()["recipients"]
        assert len(recipients) >= 2
        # Ensure only OPTED_IN leads are present
        rec_lead_ids = [r["lead_id"] for r in recipients]
        assert lead_opted_in1.id in rec_lead_ids
        assert lead_opted_in2.id in rec_lead_ids
        assert lead_opted_out.id not in rec_lead_ids
        assert lead_no_optin.id not in rec_lead_ids
        print(f"[OK] 8. Recipient eligibility verified: Only OPTED_IN leads present ({len(recipients)} recipients).")

        # 10. Test Batch Approval
        res_app = client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/approve")
        assert res_app.status_code == 200
        assert res_app.json()["approval_status"] == "Approved"
        print(f"[OK] 9. Batch ID #{batch_id} approved successfully.")

        # 11. Test Batch Send Dispatch in MOCK mode with mocked client response
        import uuid
        from unittest.mock import AsyncMock, patch

        mock_meta_client = AsyncMock()
        mock_meta_client.send_template_message.side_effect = lambda **kwargs: {
            "success": True,
            "whatsapp_message_id": f"wamid.p95_e2e_{uuid.uuid4().hex[:12]}",
        }

        with patch("app.services.whatsapp_service.get_whatsapp_client", return_value=mock_meta_client):
            res_send = client.post(f"/api/campaigns/{camp_id}/batches/{batch_id}/send")

        assert res_send.status_code == 200
        send_data = res_send.json()
        assert send_data["send_status"] == "Completed"
        assert send_data["sent_count"] >= 2
        print(f"[OK] 10. Batch ID #{batch_id} dispatched: {send_data['sent_count']} sent, {send_data['failed_count']} failed.")

        # 12. Test Batch Rejection on a fresh batch
        camp_name_rej = f"Rejection Test Camp {datetime.now(timezone.utc).strftime('%H%M%S')}"
        res_rej_camp = client.post(
            "/api/campaigns",
            json={
                "campaign_name": camp_name_rej,
                "template_name": tpl_name,
                "auto_generate_batches": False,
            },
        )
        rej_camp_id = res_rej_camp.json()["id"]

        # Manually generate batch
        res_gen = client.post(
            f"/api/campaigns/{rej_camp_id}/generate-batches",
            json={"lead_ids": [lead_opted_in1.id], "batch_size": 50},
        )
        assert res_gen.status_code == 201
        rej_batch_id = res_gen.json()["items"][0]["id"]

        # Reject the batch
        res_rej = client.post(f"/api/campaigns/{rej_camp_id}/batches/{rej_batch_id}/reject")
        assert res_rej.status_code == 200
        assert res_rej.json()["approval_status"] == "Rejected"
        print(f"[OK] 11. Batch ID #{rej_batch_id} rejected successfully.")

        # Ensure rejected batch cannot be approved or sent
        bad_app = client.post(f"/api/campaigns/{rej_camp_id}/batches/{rej_batch_id}/approve")
        assert bad_app.status_code == 400
        bad_send = client.post(f"/api/campaigns/{rej_camp_id}/batches/{rej_batch_id}/send")
        assert bad_send.status_code == 400
        print("[OK] 12. Rejected batch approval & send prevention verified.")

        # 13. Verify Static Frontend Assets
        frontend_html = client.get("/dashboard/campaigns")
        assert frontend_html.status_code == 200
        assert "campaignsContainer" in frontend_html.text
        assert "approvalsContainer" in frontend_html.text
        assert "/static/js/campaigns.js" in frontend_html.text
        assert "/static/js/approvals.js" in frontend_html.text

        js_camp = client.get("/static/js/campaigns.js")
        assert js_camp.status_code == 200
        assert "CampaignsManager" in js_camp.text

        js_appr = client.get("/static/js/approvals.js")
        assert js_appr.status_code == 200
        assert "ApprovalsManager" in js_appr.text

        print("[OK] 13. Frontend HTML templates, JS controllers, and dashboard routes verified.")

        print("=====================================================================")
        print("   ALL PHASE 9.5 VERIFICATION SCENARIOS COMPLETED WITH 100% SUCCESS! ")
        print("=====================================================================")

    finally:
        app.dependency_overrides.clear()
        db.close()


if __name__ == "__main__":
    run_verification()
