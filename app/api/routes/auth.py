"""API routes for Authentication, Session Management, and One-Time Setup."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_optional_user
from app.core.config import get_settings
from app.core.rate_limiter import login_rate_limiter
from app.core.security import generate_csrf_token
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.auth_schemas import (
    AuthStatusResponse,
    ChangePasswordRequest,
    LoginRequest,
    LogoutResponse,
    SetupRequest,
    UserResponse,
)
from app.services.auth_service import AuthService

logger = logging.getLogger("app.api.auth")

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.get(
    "/status",
    response_model=AuthStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Check system initialization and current authentication status",
)
def get_auth_status(
    db: Session = Depends(get_db),
    optional_user: Optional[User] = Depends(get_optional_user),
) -> AuthStatusResponse:
    """Public status endpoint to inform frontend routing if admin setup or login is needed."""
    initialized = AuthService.is_initialized(db)
    authenticated = optional_user is not None
    user_response = None
    if optional_user:
        user_response = UserResponse(
            id=optional_user.id,
            username=optional_user.username,
            role=optional_user.role,
            is_active=optional_user.is_active,
            created_at=optional_user.created_at,
        )

    return AuthStatusResponse(
        initialized=initialized,
        authenticated=authenticated,
        user=user_response,
    )


@router.post(
    "/setup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="One-time administrator account bootstrap",
)
def setup_initial_admin(
    payload: SetupRequest,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Bootstrap the primary administrator account if no users exist."""
    try:
        user = AuthService.initialize_admin(
            db=db,
            username=payload.username,
            password=payload.password,
            setup_secret=payload.setup_secret,
        )
        return UserResponse(
            id=user.id,
            username=user.username,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        )
    except ValueError as exc:
        err_msg = str(exc)
        if "already initialized" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=err_msg,
            ) from exc
        if "Invalid setup secret" in err_msg or "disabled" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=err_msg,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        ) from exc


@router.post(
    "/login",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user and establish secure session",
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserResponse:
    """Authenticate credentials, establish session, and issue HttpOnly cookie & CSRF cookie."""
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"

    # 1. Check brute-force rate limit
    is_limited, retry_after = login_rate_limiter.is_rate_limited(client_ip, payload.username)
    if is_limited:
        logger.warning("Brute-force login blocked for IP %s / user %s", client_ip, payload.username)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Please wait {retry_after} seconds before retrying.",
            headers={"Retry-After": str(retry_after)},
        )

    # 2. Verify credentials
    user = AuthService.authenticate_user(db, payload.username, payload.password)
    if not user:
        login_rate_limiter.record_failure(client_ip, payload.username)
        logger.warning("Failed login attempt for user '%s' from IP %s", payload.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    # 3. Check account active status
    if not user.is_active:
        logger.warning("Attempted login to inactive user '%s' from IP %s", payload.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Please contact an administrator.",
        )

    # 4. Clear rate-limit counters on success
    login_rate_limiter.record_success(client_ip, payload.username)

    # 5. Create session (stores SHA-256 hash in SQLite)
    _, raw_token = AuthService.create_session(
        db=db,
        user=user,
        max_age_seconds=settings.SESSION_MAX_AGE_SECONDS,
    )

    # 6. Generate CSRF token
    csrf_token = generate_csrf_token()

    # 7. Set secure HttpOnly session cookie
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=settings.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        path="/",
    )

    # 8. Set companion CSRF cookie (readable by JS to include in X-CSRF-Token header)
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=settings.SESSION_MAX_AGE_SECONDS,
        httponly=False,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        path="/",
    )

    logger.info("User '%s' logged in successfully from %s", user.username, client_ip)

    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        csrf_token=csrf_token,
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke active user session and clear cookies",
)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> LogoutResponse:
    """Revoke session token in database and clear client cookies."""
    settings = get_settings()

    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not raw_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            raw_token = auth_header[7:].strip()

    if raw_token:
        AuthService.revoke_session(db, raw_token)

    response.delete_cookie(key=settings.SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(key=settings.CSRF_COOKIE_NAME, path="/")

    return LogoutResponse(message="Logged out successfully")


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve profile and session status for currently authenticated user",
)
def get_me(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """Return currently authenticated user information and active CSRF token."""
    settings = get_settings()
    csrf_token = request.cookies.get(settings.CSRF_COOKIE_NAME)

    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
        csrf_token=csrf_token,
    )


@router.post(
    "/change-password",
    status_code=status.HTTP_200_OK,
    summary="Change password for authenticated user",
)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Verify current password and update to new password."""
    from app.core.security import verify_password
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password verification failed. Please check your existing password.",
        )
    try:
        AuthService.reset_admin_password(db, current_user.username, payload.new_password)
        return {
            "status": "ok",
            "message": "Password updated successfully. Active sessions have been invalidated.",
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
