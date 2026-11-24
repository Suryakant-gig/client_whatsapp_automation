"""Automated test suite for Phase 9.2 Authentication, Sessions, CSRF, and Security."""

from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limiter import login_rate_limiter
from app.core.security import (
    DEFAULT_ITERATIONS,
    PBKDF2_ALGORITHM,
    PasswordValidationError,
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_session_token,
    validate_password_strength,
    verify_password,
)
from app.db.models.user import User
from app.db.models.user_session import UserSession
from app.services.auth_service import AuthService
from app.services.webhook_service import WebhookService


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset in-memory rate limiter state before each test."""
    login_rate_limiter.reset()
    yield
    login_rate_limiter.reset()


# ==============================================================================
# 1. Password Security & Cryptography Tests
# ==============================================================================

def test_password_hash_structure() -> None:
    """Password hash must use pbkdf2_sha256 format with configured iterations and unique salt."""
    raw = "MySecurePassword123!"
    h = hash_password(raw, iterations=10_000)  # low iterations for unit test speed

    parts = h.split("$")
    assert len(parts) == 4
    algo, iters, salt, digest = parts
    assert algo == PBKDF2_ALGORITHM
    assert int(iters) == 10_000
    assert len(salt) == 32  # 16 bytes = 32 hex chars
    assert len(digest) == 64  # SHA-256 = 64 hex chars
    assert raw not in h


def test_unique_salts_for_identical_passwords() -> None:
    """Hashing the same password twice must produce different salts and different digests."""
    raw = "IdenticalPassword123!"
    h1 = hash_password(raw, iterations=5_000)
    h2 = hash_password(raw, iterations=5_000)

    assert h1 != h2
    assert h1.split("$")[2] != h2.split("$")[2]  # different salts


def test_password_verification() -> None:
    """Correct password must verify; wrong password must fail."""
    raw = "CorrectHorseBatteryStaple!"
    h = hash_password(raw, iterations=5_000)

    assert verify_password(raw, h) is True
    assert verify_password("WrongPassword123!", h) is False
    assert verify_password("", h) is False
    assert verify_password(raw, "") is False
    assert verify_password(raw, "malformed$hash") is False


def test_password_validation_rules() -> None:
    """Password length limits and empty passwords must be strictly validated."""
    # Empty or whitespace
    with pytest.raises(PasswordValidationError):
        validate_password_strength("")
    with pytest.raises(PasswordValidationError):
        validate_password_strength("     ")

    # Less than 8 characters
    with pytest.raises(PasswordValidationError):
        validate_password_strength("short7!")

    # Exceeding 128 characters
    with pytest.raises(PasswordValidationError):
        validate_password_strength("A" * 129)

    # Valid
    validate_password_strength("ValidP@ssword123")


# ==============================================================================
# 2. Account Initialization Tests
# ==============================================================================

def test_first_administrator_initialization(db_session: Session, unauthenticated_client: TestClient) -> None:
    """First-time setup succeeds when no administrator exists."""
    settings = get_settings()

    payload = {
        "username": "superadmin",
        "password": "StrongAdminPassword2026!",
        "setup_secret": settings.SETUP_SECRET or "travel_agency_setup_secret_key_2026_secure",
    }
    response = unauthenticated_client.post("/api/auth/setup", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "superadmin"
    assert data["role"] == "admin"
    assert data["is_active"] is True
    assert "password" not in data
    assert "password_hash" not in data


def test_repeated_initialization_rejected(db_session: Session, unauthenticated_client: TestClient) -> None:
    """Once an administrator is created, subsequent setup requests must be rejected with 403 Forbidden."""
    settings = get_settings()
    secret = settings.SETUP_SECRET or "travel_agency_setup_secret_key_2026_secure"

    # Create first admin
    admin = User(
        username="existing_admin",
        password_hash=hash_password("ExistingPassword123!", iterations=5_000),
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()

    # Attempt second setup
    payload = {
        "username": "second_admin",
        "password": "SecondPassword2026!",
        "setup_secret": secret,
    }
    response = unauthenticated_client.post("/api/auth/setup", json=payload)
    assert response.status_code == 403
    assert "already initialized" in response.json()["detail"].lower()


def test_initialization_invalid_secret_rejected(db_session: Session, unauthenticated_client: TestClient) -> None:
    """Setup attempt with incorrect secret key must be rejected with 403 Forbidden."""
    payload = {
        "username": "attacker",
        "password": "AttackerPassword2026!",
        "setup_secret": "wrong_secret_guess",
    }
    response = unauthenticated_client.post("/api/auth/setup", json=payload)
    assert response.status_code == 403


# ==============================================================================
# 3. Login & Rate Limiting Tests
# ==============================================================================

def test_successful_login(db_session: Session, unauthenticated_client: TestClient) -> None:
    """Login with valid credentials sets HttpOnly session and CSRF cookies."""
    password = "CorrectLoginPassword123!"
    user = User(
        username="travel_agent",
        password_hash=hash_password(password, iterations=5_000),
        role="staff",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "travel_agent", "password": password},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "travel_agent"
    assert data["role"] == "staff"
    assert "csrf_token" in data

    # Check session cookie
    settings = get_settings()
    session_cookie = response.cookies.get(settings.SESSION_COOKIE_NAME)
    assert session_cookie is not None
    assert len(session_cookie) >= 32

    # Check CSRF cookie
    csrf_cookie = response.cookies.get(settings.CSRF_COOKIE_NAME)
    assert csrf_cookie is not None


def test_login_invalid_password(db_session: Session, unauthenticated_client: TestClient) -> None:
    """Login with incorrect password returns 401 Unauthorized."""
    user = User(
        username="agent_smith",
        password_hash=hash_password("AgentSmithPass123!", iterations=5_000),
        role="staff",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "agent_smith", "password": "WrongPassword999!"},
    )
    assert response.status_code == 401
    assert "invalid username or password" in response.json()["detail"].lower()


def test_login_unknown_username(unauthenticated_client: TestClient) -> None:
    """Login with non-existent username returns 401 Unauthorized."""
    response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "non_existent_user", "password": "AnyPassword123!"},
    )
    assert response.status_code == 401


def test_login_deactivated_user(db_session: Session, unauthenticated_client: TestClient) -> None:
    """Login with deactivated account returns 403 Forbidden."""
    password = "DeactivatedUserPass123!"
    user = User(
        username="inactive_agent",
        password_hash=hash_password(password, iterations=5_000),
        role="staff",
        is_active=False,
    )
    db_session.add(user)
    db_session.commit()

    response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "inactive_agent", "password": password},
    )
    assert response.status_code == 403
    assert "deactivated" in response.json()["detail"].lower()


def test_login_rate_limiting(db_session: Session, unauthenticated_client: TestClient) -> None:
    """5 consecutive failed attempts trigger HTTP 429 Too Many Requests."""
    for i in range(5):
        resp = unauthenticated_client.post(
            "/api/auth/login",
            json={"username": "target_user", "password": f"wrong_{i}"},
        )
        assert resp.status_code == 401

    # 6th attempt should be blocked by rate limiter
    resp6 = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "target_user", "password": "another_wrong"},
    )
    assert resp6.status_code == 429
    assert "too many failed login attempts" in resp6.json()["detail"].lower()
    assert "Retry-After" in resp6.headers


# ==============================================================================
# 4. Session Security & Hashing Tests
# ==============================================================================

def test_raw_token_not_stored_in_database(db_session: Session, unauthenticated_client: TestClient) -> None:
    """SQLite database must store SHA-256 hash of session token, NEVER the raw token."""
    password = "DatabaseCheckPassword123!"
    user = User(
        username="db_inspector",
        password_hash=hash_password(password, iterations=5_000),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    response = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "db_inspector", "password": password},
    )
    assert response.status_code == 200
    settings = get_settings()
    raw_cookie_token = response.cookies.get(settings.SESSION_COOKIE_NAME)
    assert raw_cookie_token is not None

    # Inspect SQLite table directly
    sessions = db_session.scalars(select(UserSession).where(UserSession.user_id == user.id)).all()
    assert len(sessions) == 1
    stored_hash = sessions[0].token_hash

    # Raw token must NOT equal stored hash
    assert raw_cookie_token != stored_hash
    # Stored hash must equal SHA-256(raw_cookie_token)
    assert stored_hash == hashlib.sha256(raw_cookie_token.encode("utf-8")).hexdigest()


def test_expired_session_rejected(db_session: Session, unauthenticated_client: TestClient) -> None:
    """Session past its expires_at timestamp must return 401 Unauthorized."""
    user = User(
        username="expired_user",
        password_hash=hash_password("Pass12345!", iterations=5_000),
        role="staff",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    raw_token = generate_session_token()
    past_time = datetime.now(timezone.utc) - timedelta(hours=2)
    session_rec = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        expires_at=past_time,
        created_at=past_time - timedelta(days=1),
    )
    db_session.add(session_rec)
    db_session.commit()

    settings = get_settings()
    unauthenticated_client.cookies.set(settings.SESSION_COOKIE_NAME, raw_token)

    response = unauthenticated_client.get("/api/auth/me")
    assert response.status_code == 401


def test_revoked_session_rejected(db_session: Session, unauthenticated_client: TestClient) -> None:
    """Session with non-null revoked_at must return 401 Unauthorized."""
    user = User(
        username="revoked_user",
        password_hash=hash_password("Pass12345!", iterations=5_000),
        role="staff",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    raw_token = generate_session_token()
    now = datetime.now(timezone.utc)
    session_rec = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        expires_at=now + timedelta(hours=24),
        created_at=now,
        revoked_at=now,  # revoked
    )
    db_session.add(session_rec)
    db_session.commit()

    settings = get_settings()
    unauthenticated_client.cookies.set(settings.SESSION_COOKIE_NAME, raw_token)

    response = unauthenticated_client.get("/api/auth/me")
    assert response.status_code == 401


def test_logout_revokes_session_and_clears_cookie(db_session: Session, unauthenticated_client: TestClient) -> None:
    """Logout endpoint marks session revoked in database and clears cookies."""
    password = "LogoutUserPass123!"
    user = User(
        username="logout_user",
        password_hash=hash_password(password, iterations=5_000),
        role="staff",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    login_resp = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "logout_user", "password": password},
    )
    assert login_resp.status_code == 200
    settings = get_settings()
    raw_token = login_resp.cookies.get(settings.SESSION_COOKIE_NAME)
    csrf_token = login_resp.cookies.get(settings.CSRF_COOKIE_NAME)

    # Perform logout with CSRF header
    headers = {"X-CSRF-Token": csrf_token}
    logout_resp = unauthenticated_client.post("/api/auth/logout", headers=headers)
    assert logout_resp.status_code == 200

    # Verify session record in SQLite is revoked
    token_hash = hash_session_token(raw_token)
    session_rec = db_session.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
    assert session_rec is not None
    assert session_rec.revoked_at is not None

    # Subsequent /api/auth/me should return 401
    me_resp = unauthenticated_client.get("/api/auth/me")
    assert me_resp.status_code == 401


# ==============================================================================
# 5. Endpoint Authorization & Route Protection Tests
# ==============================================================================

def test_unauthenticated_request_to_leads_rejected(unauthenticated_client: TestClient) -> None:
    """Accessing GET /api/leads without authentication must return 401 Unauthorized."""
    response = unauthenticated_client.get("/api/leads")
    assert response.status_code == 401


def test_unauthenticated_request_to_campaigns_rejected(unauthenticated_client: TestClient) -> None:
    """Accessing GET /api/campaigns without authentication must return 401 Unauthorized."""
    response = unauthenticated_client.get("/api/campaigns")
    assert response.status_code == 401


def test_authenticated_access_to_leads(db_session: Session, unauthenticated_client: TestClient) -> None:
    """Authenticated user with valid session cookie can successfully access GET /api/leads."""
    password = "ValidAuthLeadsPass123!"
    user = User(
        username="leads_viewer",
        password_hash=hash_password(password, iterations=5_000),
        role="staff",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    # Log in
    login_resp = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "leads_viewer", "password": password},
    )
    assert login_resp.status_code == 200

    # Access leads
    leads_resp = unauthenticated_client.get("/api/leads")
    assert leads_resp.status_code == 200
    assert "items" in leads_resp.json()


# ==============================================================================
# 6. CSRF Protection Tests
# ==============================================================================

def test_csrf_missing_header_rejected(db_session: Session, unauthenticated_client: TestClient) -> None:
    """Mutating request with session cookie but missing X-CSRF-Token must return 403 Forbidden."""
    password = "CsrfTestPassword123!"
    user = User(
        username="csrf_victim",
        password_hash=hash_password(password, iterations=5_000),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    login_resp = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "csrf_victim", "password": password},
    )
    assert login_resp.status_code == 200

    # Attempt POST /api/leads without X-CSRF-Token header
    lead_payload = {
        "customer_name": "CSRF Attack Lead",
        "phone_number": "+919999988888",
    }
    resp = unauthenticated_client.post("/api/leads", json=lead_payload)
    assert resp.status_code == 403
    assert "csrf" in resp.json()["detail"].lower()


def test_csrf_valid_header_accepted(db_session: Session, unauthenticated_client: TestClient) -> None:
    """Mutating request with session cookie and valid X-CSRF-Token header succeeds."""
    password = "CsrfTestPassword456!"
    user = User(
        username="csrf_safe_user",
        password_hash=hash_password(password, iterations=5_000),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    login_resp = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "csrf_safe_user", "password": password},
    )
    assert login_resp.status_code == 200
    settings = get_settings()
    csrf_token = login_resp.cookies.get(settings.CSRF_COOKIE_NAME)

    # Perform POST /api/leads WITH X-CSRF-Token header
    lead_payload = {
        "customer_name": "Safe Authorized Lead",
        "phone_number": "+919999977777",
    }
    headers = {"X-CSRF-Token": csrf_token}
    resp = unauthenticated_client.post("/api/leads", json=lead_payload, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["customer_name"] == "Safe Authorized Lead"


# ==============================================================================
# 7. Public & Webhook Compatibility Tests
# ==============================================================================

def test_health_endpoint_remains_public(unauthenticated_client: TestClient) -> None:
    """GET /health must remain accessible without authentication."""
    response = unauthenticated_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_meta_webhook_challenge_remains_public(unauthenticated_client: TestClient) -> None:
    """GET /api/whatsapp/webhook must verify Meta challenge without authentication cookies."""
    settings = get_settings()
    token = settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN or "travel_agency_webhook_secret_verify_token_2026"

    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": token,
        "hub.challenge": "challenge_token_12345",
    }
    response = unauthenticated_client.get("/api/whatsapp/webhook", params=params)
    assert response.status_code == 200
    assert response.text == "challenge_token_12345"


def test_meta_webhook_event_receiver_remains_public(unauthenticated_client: TestClient) -> None:
    """POST /api/whatsapp/webhook processes signed Meta events without user login cookies."""
    settings = get_settings()
    app_secret = settings.META_APP_SECRET or "e0ca9ebb5e5d5d0781f387473a7515f2"

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "1000",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "123", "phone_number_id": "456"},
                    "statuses": [{
                        "id": "wamid.HBgLTEST123",
                        "status": "delivered",
                        "timestamp": "1700000000",
                        "recipient_id": "919876543210"
                    }]
                },
                "field": "messages"
            }]
        }]
    }
    raw_body = json.dumps(payload).encode("utf-8")
    signature = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    headers = {
        "X-Hub-Signature-256": f"sha256={signature}",
        "Content-Type": "application/json",
    }

    # Must NOT require session cookie or CSRF token
    response = unauthenticated_client.post("/api/whatsapp/webhook", content=raw_body, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ==============================================================================
# 8. Admin Password Reset Procedure Tests
# ==============================================================================

def test_admin_password_reset_success(db_session: Session, unauthenticated_client: TestClient) -> None:
    """Administrator password reset with correct SETUP_SECRET updates password and allows login."""
    settings = get_settings()
    secret = settings.SETUP_SECRET or "travel_agency_setup_secret_key_2026_secure"

    # 1. Initialize admin
    initial_user = AuthService.initialize_admin(
        db=db_session,
        username="superadmin",
        password="OriginalPassword123!",
        setup_secret=secret,
    )

    # 2. Reset password
    updated_user = AuthService.reset_admin_password(
        db=db_session,
        username="superadmin",
        new_password="NewSecurePassword2026!",
        setup_secret=secret,
    )
    assert updated_user.id == initial_user.id

    # 3. Old password must fail
    res_old = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "superadmin", "password": "OriginalPassword123!"},
    )
    assert res_old.status_code == 401

    # 4. New password must authenticate successfully
    res_new = unauthenticated_client.post(
        "/api/auth/login",
        json={"username": "superadmin", "password": "NewSecurePassword2026!"},
    )
    assert res_new.status_code == 200
    assert res_new.json()["username"] == "superadmin"


def test_admin_password_reset_invalid_secret_rejected(db_session: Session) -> None:
    """Password reset with incorrect SETUP_SECRET must be rejected."""
    settings = get_settings()
    secret = settings.SETUP_SECRET or "travel_agency_setup_secret_key_2026_secure"

    AuthService.initialize_admin(
        db=db_session,
        username="admin_sec_test",
        password="OriginalPassword123!",
        setup_secret=secret,
    )

    with pytest.raises(ValueError, match="Invalid setup secret"):
        AuthService.reset_admin_password(
            db=db_session,
            username="admin_sec_test",
            new_password="NewPassword123!",
            setup_secret="wrong_secret_key",
        )


def test_admin_password_reset_unknown_user_rejected(db_session: Session) -> None:
    """Password reset for nonexistent username must be rejected."""
    settings = get_settings()
    secret = settings.SETUP_SECRET or "travel_agency_setup_secret_key_2026_secure"

    with pytest.raises(ValueError, match="does not exist"):
        AuthService.reset_admin_password(
            db=db_session,
            username="nonexistent_user",
            new_password="NewPassword123!",
            setup_secret=secret,
        )


def test_admin_password_reset_weak_password_rejected(db_session: Session) -> None:
    """Password reset with short or empty password must fail strength validation."""
    settings = get_settings()
    secret = settings.SETUP_SECRET or "travel_agency_setup_secret_key_2026_secure"

    AuthService.initialize_admin(
        db=db_session,
        username="admin_weak_test",
        password="OriginalPassword123!",
        setup_secret=secret,
    )

    with pytest.raises(PasswordValidationError):
        AuthService.reset_admin_password(
            db=db_session,
            username="admin_weak_test",
            new_password="short",
            setup_secret=secret,
        )


def test_admin_password_reset_revokes_existing_sessions(db_session: Session) -> None:
    """Resetting admin password must revoke all currently active sessions for that user."""
    settings = get_settings()
    secret = settings.SETUP_SECRET or "travel_agency_setup_secret_key_2026_secure"

    user = AuthService.initialize_admin(
        db=db_session,
        username="admin_session_test",
        password="OriginalPassword123!",
        setup_secret=secret,
    )

    # Create active session
    session_rec, raw_token = AuthService.create_session(db_session, user)
    assert AuthService.validate_session(db_session, raw_token) is not None

    # Reset password
    AuthService.reset_admin_password(
        db=db_session,
        username="admin_session_test",
        new_password="BrandNewPassword2026!",
        setup_secret=secret,
    )

    # Previously active session must now be invalid/revoked
    assert AuthService.validate_session(db_session, raw_token) is None
