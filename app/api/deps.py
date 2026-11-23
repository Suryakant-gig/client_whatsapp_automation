"""Authentication and security dependencies for FastAPI routes."""

import hmac
from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.user import User
from app.db.session import get_db
from app.services.auth_service import AuthService


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Dependency that extracts and validates user session from cookie or Authorization header.

    Raises:
        HTTPException 401: If unauthenticated, expired, revoked, or user account inactive.
    """
    settings = get_settings()

    # 1. Attempt extracting raw session token from HttpOnly cookie
    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)

    # 2. Fall back to Authorization: Bearer header
    if not raw_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            raw_token = auth_header[7:].strip()

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Validate session in database
    user = AuthService.validate_session(db, raw_token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked session",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Dependency that returns active User if valid session exists, or None without raising 401."""
    settings = get_settings()
    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not raw_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            raw_token = auth_header[7:].strip()

    if not raw_token:
        return None

    return AuthService.validate_session(db, raw_token)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency enforcing administrator role authorization."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required",
        )
    return current_user


def verify_csrf(request: Request) -> bool:
    """Dependency enforcing CSRF protection on state-modifying requests using session cookies.

    Exemptions:
    - Safe methods (GET, HEAD, OPTIONS).
    - Public webhook endpoints (/api/whatsapp/webhook).
    - Authentication entry endpoints (/api/auth/login, /api/auth/setup).
    - Programmatic API requests not using browser session cookies.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True

    path = request.url.path
    if path in ("/api/whatsapp/webhook", "/api/auth/login", "/api/auth/setup"):
        return True

    settings = get_settings()
    session_cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)

    # Only enforce CSRF when browser session cookie is present
    if session_cookie:
        csrf_cookie = request.cookies.get(settings.CSRF_COOKIE_NAME)
        csrf_header = request.headers.get("X-CSRF-Token")

        if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF verification failed: missing or invalid CSRF token",
            )

    return True
