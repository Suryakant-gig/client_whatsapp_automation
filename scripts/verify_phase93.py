"""Verification script comparing SQLite raw counts against Dashboard API values."""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sqlite3
from fastapi.testclient import TestClient
from app.main import app

def main():
    conn = sqlite3.connect('travel_agency.db')
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM leads WHERE is_deleted = 0")
    db_total_leads = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE is_deleted = 0 AND status = 'Pending'")
    db_pending_leads = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE is_deleted = 0 AND status = 'Replied'")
    db_replied_leads = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE is_deleted = 0 AND opt_in_status = 'OPTED_IN'")
    db_opted_in = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE is_deleted = 0 AND opt_in_status = 'OPTED_OUT'")
    db_opted_out = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM campaigns")
    db_campaigns = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM campaigns WHERE status IN ('Scheduled', 'In Progress')")
    db_active_campaigns = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM message_logs")
    db_messages = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM message_logs WHERE delivery_status = 'Delivered'")
    db_delivered = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM message_logs WHERE delivery_status = 'Read'")
    db_read = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM message_logs WHERE delivery_status = 'Failed'")
    db_failed = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM follow_up_schedules WHERE status IN ('Scheduled', 'Approved')")
    db_followups = cur.fetchone()[0]
    conn.close()

    # Query Dashboard API via authenticated client
    client = TestClient(app)
    login_res = client.post('/api/auth/login', json={'username': 'admin', 'password': 'StrongAdminPassword2026!'})
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"

    stats_res = client.get('/api/dashboard/stats')
    assert stats_res.status_code == 200, f"Stats failed: {stats_res.text}"
    api_stats = stats_res.json()

    print("=== COMPARISON: SQLite Raw Records vs API Dashboard Stats ===")
    metrics = [
        ('total_leads', db_total_leads, api_stats['total_leads']),
        ('pending_leads', db_pending_leads, api_stats['pending_leads']),
        ('replied_leads', db_replied_leads, api_stats['replied_leads']),
        ('opted_in_leads', db_opted_in, api_stats['opted_in_leads']),
        ('opted_out_leads', db_opted_out, api_stats['opted_out_leads']),
        ('total_campaigns', db_campaigns, api_stats['total_campaigns']),
        ('active_campaigns', db_active_campaigns, api_stats['active_campaigns']),
        ('total_messages_sent', db_messages, api_stats['total_messages_sent']),
        ('delivered_messages', db_delivered, api_stats['delivered_messages']),
        ('read_messages', db_read, api_stats['read_messages']),
        ('failed_messages', db_failed, api_stats['failed_messages']),
        ('scheduled_follow_ups', db_followups, api_stats['scheduled_follow_ups']),
    ]

    for name, db_val, api_val in metrics:
        match = "MATCH" if db_val == api_val else "MISMATCH"
        print(f"{name:22} | DB: {db_val:4} | API: {api_val:4} | {match}")
        assert db_val == api_val, f"Mismatch for {name}: {db_val} vs {api_val}"

    print("\nALL 12 DATABASE-BACKED METRICS MATCH 100% PERFECTLY!")

    # Navigation routing verification
    print("\n=== Navigation Architecture Verification ===")
    routes = [
        "/dashboard",
        "/dashboard/leads",
        "/dashboard/campaigns",
        "/dashboard/excel",
        "/dashboard/approvals",
        "/dashboard/followups",
        "/dashboard/reports",
        "/dashboard/settings",
    ]

    # Test unauthenticated access to frontend routes
    unauth_client = TestClient(app)
    for r in routes:
        res = unauth_client.get(r, follow_redirects=False)
        print(f"Unauthenticated {r:22} -> Status: {res.status_code} Redirect: {res.headers.get('location')}")
        assert res.status_code == 303
        assert res.headers.get('location') == '/login'

    # Test authenticated access to frontend routes
    for r in routes:
        res = client.get(r, follow_redirects=False)
        print(f"Authenticated   {r:22} -> Status: {res.status_code} Content: {res.headers.get('content-type')}")
        assert res.status_code == 200
        assert "text/html" in res.headers.get('content-type', '')

    print("\nALL 8 FRONTEND NAVIGATION ROUTES VERIFIED SUCCESSFULLY!")

    # Security verification
    print("\n=== Additional Security Verification ===")
    # 1. Meta POST Webhook signature verification
    import hmac, hashlib, json
    from app.core.config import get_settings
    settings = get_settings()
    app_secret = settings.META_APP_SECRET
    webhook_body = json.dumps({"object": "whatsapp_business_account", "entry": []}).encode("utf-8")
    sig = hmac.new(app_secret.encode("utf-8"), webhook_body, hashlib.sha256).hexdigest()
    wh_res = client.post("/api/whatsapp/webhook", content=webhook_body, headers={"X-Hub-Signature-256": f"sha256={sig}"})
    print(f"Meta POST Webhook status: {wh_res.status_code} ({wh_res.json()['status']})")
    assert wh_res.status_code == 200

    # 2. Browser login and dashboard redirect verification
    print(f"Browser login status: {login_res.status_code} (User: {login_res.json()['username']})")
    idx_res = client.get("/")
    print(f"Dashboard load status: {idx_res.status_code} ({idx_res.headers.get('content-type')})")
    assert idx_res.status_code == 200

    # 3. Logout and browser redirect verification
    csrf_token = login_res.cookies.get("travel_crm_csrf")
    logout_res = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token})
    print(f"Logout status: {logout_res.status_code} ({logout_res.json()['message']})")
    assert logout_res.status_code == 200

    post_logout_res = client.get("/api/dashboard/stats")
    print(f"Post-logout /api/dashboard/stats: {post_logout_res.status_code} (Access blocked)")
    assert post_logout_res.status_code == 401

    print("\nALL SECURITY VERIFICATIONS COMPLETED SUCCESSFULLY!")

if __name__ == '__main__':
    main()
