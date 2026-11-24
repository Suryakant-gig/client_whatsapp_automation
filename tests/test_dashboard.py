"""Automated test suite for Phase 9.3 Dashboard Overview & Database Metrics."""

from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.campaign import Campaign
from app.db.models.follow_up import FollowUpSchedule
from app.db.models.lead import Lead
from app.db.models.message import IncomingMessage, MessageLog
from app.db.models.sync_log import SyncLog
from app.db.models.user import User
from app.services.dashboard_service import DashboardService


# ==============================================================================
# 1. Route Protection & Authorization Tests
# ==============================================================================

def test_dashboard_stats_unauthenticated_rejected(unauthenticated_client: TestClient) -> None:
    """GET /api/dashboard/stats must return HTTP 401 when unauthenticated."""
    response = unauthenticated_client.get("/api/dashboard/stats")
    assert response.status_code == 401


def test_dashboard_activity_unauthenticated_rejected(unauthenticated_client: TestClient) -> None:
    """GET /api/dashboard/recent-activity must return HTTP 401 when unauthenticated."""
    response = unauthenticated_client.get("/api/dashboard/recent-activity")
    assert response.status_code == 401


def test_dashboard_overview_unauthenticated_rejected(unauthenticated_client: TestClient) -> None:
    """GET /api/dashboard/overview must return HTTP 401 when unauthenticated."""
    response = unauthenticated_client.get("/api/dashboard/overview")
    assert response.status_code == 401


# ==============================================================================
# 2. Database Statistics Calculation & Aggregation Tests
# ==============================================================================

def test_dashboard_stats_accuracy_with_seed_data(client: TestClient, db_session: Session) -> None:
    """Ensure aggregated stats accurately calculate counts across leads, campaigns, messages, and schedules."""
    # 1. Create leads with distinct statuses and opt-in states
    leads_to_create = [
        Lead(customer_name="Lead 1", phone_number="+919800000001", status="Pending", opt_in_status="OPTED_IN", is_deleted=False),
        Lead(customer_name="Lead 2", phone_number="+919800000002", status="Pending", opt_in_status="OPTED_OUT", is_deleted=False),
        Lead(customer_name="Lead 3", phone_number="+919800000003", status="Replied", opt_in_status="OPTED_IN", is_deleted=False),
        Lead(customer_name="Lead 4", phone_number="+919800000004", status="Not Interested", opt_in_status="NOT_OPTED_IN", is_deleted=False),
        Lead(customer_name="Lead 5 (Deleted)", phone_number="+919800000005", status="Pending", opt_in_status="OPTED_IN", is_deleted=True),
    ]
    db_session.add_all(leads_to_create)
    db_session.flush()

    # 2. Create campaigns
    campaigns_to_create = [
        Campaign(campaign_name="Summer Promo", status="In Progress"),
        Campaign(campaign_name="Winter Getaways", status="Scheduled"),
        Campaign(campaign_name="Draft Campaign", status="Draft"),
    ]
    db_session.add_all(campaigns_to_create)
    db_session.flush()

    # 3. Create message logs with various delivery statuses
    messages_to_create = [
        MessageLog(lead_id=leads_to_create[0].id, message_type="template", delivery_status="Delivered"),
        MessageLog(lead_id=leads_to_create[1].id, message_type="template", delivery_status="Read"),
        MessageLog(lead_id=leads_to_create[2].id, message_type="follow_up", delivery_status="Failed"),
        MessageLog(lead_id=leads_to_create[3].id, message_type="campaign", delivery_status="Sent"),
    ]
    db_session.add_all(messages_to_create)
    db_session.flush()

    # 4. Create follow-up schedules
    now = datetime.now(timezone.utc)
    schedules_to_create = [
        FollowUpSchedule(lead_id=leads_to_create[0].id, sequence_number=1, scheduled_at=now, status="Scheduled"),
        FollowUpSchedule(lead_id=leads_to_create[0].id, sequence_number=2, scheduled_at=now + timedelta(days=2), status="Approved"),
        FollowUpSchedule(lead_id=leads_to_create[1].id, sequence_number=1, scheduled_at=now - timedelta(days=1), status="Sent"),
    ]
    db_session.add_all(schedules_to_create)

    # 5. Create sync log
    sync_log = SyncLog(operation="excel_import", sync_status="Success", records_processed=4)
    db_session.add(sync_log)
    db_session.commit()

    # Call API endpoint
    response = client.get("/api/dashboard/stats")
    assert response.status_code == 200
    stats = response.json()

    # Verify counts match database
    # Non-deleted leads = 4 (Lead 1, 2, 3, 4)
    assert stats["total_leads"] == 4
    assert stats["pending_leads"] == 2  # Lead 1, Lead 2
    assert stats["replied_leads"] == 1  # Lead 3
    assert stats["not_interested_leads"] == 1  # Lead 4
    assert stats["confirmed_leads"] == 0  # Allowed statuses are Pending, Replied, Not Interested
    assert stats["opted_in_leads"] == 2  # Lead 1, Lead 3
    assert stats["opted_out_leads"] == 1  # Lead 2

    # Campaigns: total 3, active (In Progress + Scheduled) = 2
    assert stats["total_campaigns"] == 3
    assert stats["active_campaigns"] == 2

    # Messages: total 4, delivered = 1, read = 1, failed = 1
    assert stats["total_messages_sent"] == 4
    assert stats["delivered_messages"] == 1
    assert stats["read_messages"] == 1
    assert stats["failed_messages"] == 1

    # Follow-ups: active (Scheduled + Approved) = 0 (decommissioned)
    assert stats["scheduled_follow_ups"] == 0
    assert stats["last_sync_timestamp"] is not None


# ==============================================================================
# 3. Recent Activity Feed Tests
# ==============================================================================

def test_dashboard_recent_activity(client: TestClient, db_session: Session) -> None:
    """Recent activity endpoint must return sorted chronological event entries."""
    lead = Lead(customer_name="Activity Lead", phone_number="+919800000099", status="Pending")
    db_session.add(lead)
    db_session.flush()

    msg = MessageLog(lead_id=lead.id, message_type="template", template_name="welcome_msg", delivery_status="Delivered")
    db_session.add(msg)

    sync = SyncLog(operation="manual_sync", sync_status="Success", records_processed=10)
    db_session.add(sync)

    inc = IncomingMessage(
        lead_id=lead.id,
        whatsapp_message_id="wamid.ACTTEST123",
        sender_phone="+919800000099",
        message_text="Hello travel agency!",
        received_at=datetime.now(timezone.utc),
        processing_status="PROCESSED",
    )
    db_session.add(inc)
    db_session.commit()

    response = client.get("/api/dashboard/recent-activity?limit=5")
    assert response.status_code == 200
    items = response.json()
    assert len(items) >= 3

    # Ensure items have required normalized fields
    for item in items:
        assert "id" in item
        assert "category" in item
        assert "title" in item
        assert "description" in item
        assert "timestamp" in item


def test_dashboard_overview_combined(client: TestClient, db_session: Session) -> None:
    """GET /api/dashboard/overview returns stats, activity, and server status."""
    response = client.get("/api/dashboard/overview")
    assert response.status_code == 200
    data = response.json()

    assert "stats" in data
    assert "recent_activity" in data
    assert "server_time" in data
    assert "scheduler_enabled" in data
    assert "whatsapp_enabled" in data


# ==============================================================================
# 4. Frontend Navigation Route Tests
# ==============================================================================

FRONTEND_DASHBOARD_ROUTES = [
    "/dashboard",
    "/dashboard/leads",
    "/dashboard/campaigns",
    "/dashboard/excel",
    "/dashboard/approvals",
    "/dashboard/followups",
    "/dashboard/reports",
    "/dashboard/settings",
]


def test_frontend_routes_unauthenticated_redirects(unauthenticated_client: TestClient) -> None:
    """Unauthenticated access to any frontend dashboard route must redirect to /login."""
    for route in FRONTEND_DASHBOARD_ROUTES:
        response = unauthenticated_client.get(route, follow_redirects=False)
        assert response.status_code == 303, f"Route {route} did not redirect (status: {response.status_code})"
        assert response.headers["location"] == "/login"


def test_root_path_redirects_to_dashboard(unauthenticated_client: TestClient) -> None:
    """GET / must redirect to /dashboard."""
    response = unauthenticated_client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"


def test_frontend_routes_authenticated_serves_html(db_session: Session, unauthenticated_client: TestClient) -> None:
    """Authenticated user accessing any dashboard route receives the frontend HTML shell."""
    from app.core.config import get_settings
    from app.core.security import hash_password
    from app.services.auth_service import AuthService

    # Create user and active session
    user = User(
        username="nav_tester",
        password_hash=hash_password("NavPassword123!", iterations=5_000),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    _, raw_token = AuthService.create_session(db_session, user)
    settings = get_settings()
    unauthenticated_client.cookies.set(settings.SESSION_COOKIE_NAME, raw_token)

    for route in FRONTEND_DASHBOARD_ROUTES:
        response = unauthenticated_client.get(route, follow_redirects=False)
        assert response.status_code == 200, f"Route {route} failed (status: {response.status_code})"
        assert "text/html" in response.headers.get("content-type", "")
        assert "Travel CRM" in response.text

