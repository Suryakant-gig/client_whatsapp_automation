"""Phase 9.6 Automated Tests: Production UI, Functionality & Reliability Hardening.

Covers:
- All 8 frontend dashboard routes and HTML delivery
- Static JavaScript assets serving (modals.js, followups.js, excel.js, reports.js, settings.js)
- Modal attribute compliance (data-dismiss="modal", type="button")
- Follow-up manual execution endpoint (POST /api/followups/process-due)
- Excel backup listing endpoint (GET /api/excel/backups)
- Administrator password change endpoint (POST /api/auth/change-password) with CSRF and auth
"""

import os
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.models.user import User
from app.main import app
from app.services.auth_service import AuthService

settings = get_settings()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def auth_client(client, db_session):
    """Test client with an active admin session and CSRF cookie."""
    admin = db_session.query(User).filter(User.username == "admin").first()
    if not admin:
        admin = AuthService.initialize_admin(db_session, "admin", "AdminSecure123!", settings.SETUP_SECRET)

    _, session_token = AuthService.create_session(db_session, admin)
    csrf_token = "test_csrf_token_phase96"

    client.cookies.set(settings.SESSION_COOKIE_NAME, session_token)
    client.cookies.set(settings.CSRF_COOKIE_NAME, csrf_token)
    return client, csrf_token, admin


# =============================================================================
# 1. Dashboard Routes & Static Assets Tests
# =============================================================================

def test_all_eight_dashboard_frontend_routes(auth_client):
    """Ensure all navigation routes return 200 OK HTML without unhandled errors."""
    client, _, _ = auth_client

    routes = [
        "/dashboard",
        "/dashboard/leads",
        "/dashboard/campaigns",
        "/dashboard/approvals",
        "/dashboard/respondents",
        "/dashboard/interested",
        "/dashboard/excel",
        "/dashboard/reports",
        "/dashboard/settings",
    ]

    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, f"Route {route} failed with status {response.status_code}"
        assert "text/html" in response.headers.get("content-type", "")
        # Verify DOM containers are delivered
        assert "respondentsContainer" in response.text
        assert "interestedContainer" in response.text
        assert "excelContainer" in response.text
        assert "reportsContainer" in response.text
        assert "settingsContainer" in response.text


def test_static_js_assets_served(auth_client):
    """Ensure all required module scripts are successfully delivered."""
    client, _, _ = auth_client

    scripts = [
        "/static/js/api.js",
        "/static/js/modals.js",
        "/static/js/leads.js",
        "/static/js/campaigns.js",
        "/static/js/approvals.js",
        "/static/js/followups.js",
        "/static/js/excel.js",
        "/static/js/reports.js",
        "/static/js/settings.js",
        "/static/js/dashboard.js",
    ]

    for script in scripts:
        res = client.get(script)
        assert res.status_code == 200, f"Script {script} failed with status {res.status_code}"
        assert len(res.text) > 50, f"Script {script} returned empty or truncated content"


def test_modal_dismiss_attributes_in_html():
    """Verify that all close and cancel buttons in index.html specify data-dismiss='modal' and type='button'."""
    index_path = os.path.join(BASE_DIR, "app", "frontend", "index.html")
    assert os.path.isfile(index_path)

    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Required button IDs that must carry data-dismiss="modal"
    close_button_ids = [
        "closeDetailModalBtn",
        "closeDetailModalBottomBtn",
        "closeEditModalBtn",
        "cancelEditModalBtn",
        "closeConsentModalBtn",
        "cancelConsentModalBtn",
        "closeCreateModalBtn",
        "cancelCreateModalBtn",
        "closeCreateCampaignModalBtn",
        "cancelCreateCampaignBtn",
        "closeEditCampaignModalBtn",
        "cancelEditCampaignBtn",
        "closeCampaignDetailBtn",
        "closeCampaignDetailFooterBtn",
        "closeBatchReviewHeaderBtn",
        "closeBatchReviewBtn",
    ]

    for btn_id in close_button_ids:
        assert f'id="{btn_id}"' in content, f"Missing modal button #{btn_id}"
        start_idx = content.find(f'id="{btn_id}"')
        tag_start = content.rfind("<button", 0, start_idx)
        tag_end = content.find(">", start_idx)
        tag_html = content[tag_start:tag_end + 1]

        assert 'data-dismiss="modal"' in tag_html, f"Button #{btn_id} lacks data-dismiss='modal': {tag_html}"
        assert 'type="button"' in tag_html, f"Button #{btn_id} lacks type='button': {tag_html}"


# =============================================================================
# 2. Endpoint Functionality Tests
# =============================================================================

@pytest.mark.skip(
    reason="/api/followups endpoint decommissioned per final CRM simplification requirements"
)
def test_process_due_schedules_endpoint(auth_client):
    """Test manual trigger of due follow-up processing."""
    client, csrf_token, _ = auth_client

    with patch("app.services.followup_service.FollowUpService.process_due_schedules") as mock_process:
        mock_process.return_value = (2, 1, 0)

        res = client.post(
            "/api/followups/process-due",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] in ("ok", "success")
        assert data["sent_count"] == 2
        assert data["skipped_count"] == 1
        assert data["failed_count"] == 0


def test_excel_backups_endpoint(auth_client):
    """Test retrieving list of automated Excel backups."""
    client, _, _ = auth_client

    res = client.get("/api/excel/backups")
    assert res.status_code == 200
    data = res.json()
    assert "workbook_path" in data
    assert "backup_dir" in data
    assert "backups" in data
    assert isinstance(data["backups"], list)


def test_change_password_workflow(unauthenticated_client, db_session):
    """Test administrator password update endpoint with validation, old password rejection, and session reset."""
    admin = db_session.query(User).filter(User.username == "admin").first()
    if not admin:
        admin = AuthService.initialize_admin(db_session, "admin", "AdminSecure123!", settings.SETUP_SECRET)
    else:
        AuthService.reset_admin_password(db_session, "admin", "AdminSecure123!")

    _, session_token = AuthService.create_session(db_session, admin)
    csrf_token = "test_csrf_token_phase96"

    unauthenticated_client.cookies.set(settings.SESSION_COOKIE_NAME, session_token)
    unauthenticated_client.cookies.set(settings.CSRF_COOKIE_NAME, csrf_token)

    # 1. Test incorrect current password
    bad_req = unauthenticated_client.post(
        "/api/auth/change-password",
        json={
            "current_password": "WrongPassword123!",
            "new_password": "BrandNewAdminPassword2026!",
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert bad_req.status_code == 400
    assert "Current password verification failed" in bad_req.json()["detail"]

    # 2. Test successful password change
    good_req = unauthenticated_client.post(
        "/api/auth/change-password",
        json={
            "current_password": "AdminSecure123!",
            "new_password": "BrandNewAdminPassword2026!",
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert good_req.status_code == 200
    assert good_req.json()["status"] == "ok"

    # 3. Verify old password no longer works for login
    old_login = unauthenticated_client.post(
        "/api/auth/login",
        json={
            "username": "admin",
            "password": "AdminSecure123!",
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert old_login.status_code == 401

    # 4. Verify new password works for login
    new_login = unauthenticated_client.post(
        "/api/auth/login",
        json={
            "username": "admin",
            "password": "BrandNewAdminPassword2026!",
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert new_login.status_code == 200
    assert new_login.json()["username"] == "admin"

    # Restore password for other tests
    AuthService.reset_admin_password(db_session, "admin", "AdminSecure123!")
