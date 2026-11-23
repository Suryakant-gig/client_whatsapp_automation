"""Authentication service implementing business logic for users, sessions, and initial setup."""

from datetime import datetime, timezone, timedelta
import hmac
import logging
from typing import Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    validate_password_strength,
    verify_password,
)
from app.db.models.user import User
from app.db.models.user_session import UserSession

logger = logging.getLogger("app.auth")


class AuthService:
    """Service providing core authentication, authorization, and session tracking operations."""

    @staticmethod
    def is_initialized(db: Session) -> bool:
        """Check whether the system has already been initialized with an administrator account."""
        count = db.scalar(select(func.count(User.id))) or 0
        return count > 0

    @staticmethod
    def get_user_by_username(db: Session, username: str) -> Optional[User]:
        """Retrieve user by unique username (case-insensitive search)."""
        clean_user = username.strip().lower()
        stmt = select(User).where(func.lower(User.username) == clean_user)
        return db.scalar(stmt)

    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
        """Retrieve user by primary key ID."""
        return db.get(User, user_id)

    @staticmethod
    def initialize_admin(
        db: Session,
        username: str,
        password: str,
        setup_secret: str,
    ) -> User:
        """Bootstrap the primary administrator account during one-time initial setup.

        Enforces:
        - Must not already have any users.
        - Must match configured SETUP_SECRET.
        - Must pass password complexity rules.
        """
        settings = get_settings()

        if AuthService.is_initialized(db):
            raise ValueError("Application is already initialized. New admin accounts cannot be created via setup.")

        # If a setup secret is configured in the environment, enforce constant-time match
        configured_secret = (settings.SETUP_SECRET or "").strip()
        if not configured_secret:
            raise ValueError("Initial setup is disabled because SETUP_SECRET is not configured in environment.")

        if not setup_secret or not hmac.compare_digest(setup_secret.strip(), configured_secret):
            raise ValueError("Invalid setup secret. Authorization denied.")

        clean_username = username.strip()
        if len(clean_username) < 3:
            raise ValueError("Username must be at least 3 characters long.")

        validate_password_strength(password)
        hashed = hash_password(password)

        admin_user = User(
            username=clean_username,
            password_hash=hashed,
            role="admin",
            is_active=True,
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        logger.info("Primary administrator account '%s' initialized successfully.", clean_username)
        return admin_user

    @staticmethod
    def reset_admin_password(
        db: Session,
        username: str,
        new_password: str,
        setup_secret: Optional[str] = None,
    ) -> User:
        """Securely reset an administrator password with SETUP_SECRET verification.

        Enforces:
        - Must match configured SETUP_SECRET using constant-time comparison if provided.
        - Target user must exist and have role == 'admin'.
        - New password must pass password strength and length validation.
        - Revokes all existing active sessions for this user.
        - Updates password_hash with new PBKDF2-HMAC-SHA256 hash.
        """
        settings = get_settings()

        if setup_secret is not None:
            configured_secret = (settings.SETUP_SECRET or "").strip()
            if not configured_secret:
                raise ValueError("Password reset is disabled because SETUP_SECRET is not configured in environment.")

            if not setup_secret or not hmac.compare_digest(setup_secret.strip(), configured_secret):
                raise ValueError("Invalid setup secret. Authorization denied.")

        user = AuthService.get_user_by_username(db, username)
        if not user:
            raise ValueError(f"User '{username}' does not exist.")

        if user.role != "admin":
            raise ValueError(f"User '{username}' is not an administrator.")

        validate_password_strength(new_password)
        hashed = hash_password(new_password)

        now = datetime.now(timezone.utc)
        user.password_hash = hashed
        user.updated_at = now

        # Revoke all active sessions for this user for security
        active_sessions = db.scalars(
            select(UserSession).where(
                UserSession.user_id == user.id,
                UserSession.revoked_at.is_(None),
            )
        ).all()
        for session in active_sessions:
            session.revoked_at = now

        db.commit()
        db.refresh(user)
        logger.info("Password for administrator '%s' was reset successfully.", user.username)
        return user

    @staticmethod
    def authenticate_user(
        db: Session,
        username: str,
        password: str,
    ) -> Optional[User]:
        """Verify user credentials and active status."""
        user = AuthService.get_user_by_username(db, username)
        if not user:
            return None

        if not verify_password(password, user.password_hash):
            return None

        return user

    @staticmethod
    def create_session(
        db: Session,
        user: User,
        max_age_seconds: int = 86400,
    ) -> Tuple[UserSession, str]:
        """Create a new authenticated user session.

        Stores only the SHA-256 hash of the session token in the database.
        Returns (UserSession, raw_session_token).
        """
        raw_token = generate_session_token()
        token_hash = hash_session_token(raw_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=max_age_seconds)

        session_record = UserSession(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            created_at=now,
            revoked_at=None,
        )
        db.add(session_record)
        db.commit()
        db.refresh(session_record)
        return session_record, raw_token

    @staticmethod
    def validate_session(
        db: Session,
        raw_token: str,
    ) -> Optional[User]:
        """Validate session token and return the associated active user.

        Verifies:
        - Token hash exists in database.
        - Session is not revoked (revoked_at is None).
        - Session has not expired (expires_at > current UTC time).
        - User account is active (is_active is True).
        """
        if not raw_token or not isinstance(raw_token, str):
            return None

        token_hash = hash_session_token(raw_token)
        now = datetime.now(timezone.utc)

        stmt = (
            select(UserSession)
            .join(User)
            .where(
                UserSession.token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
                User.is_active.is_(True),
            )
        )
        session_record = db.scalar(stmt)
        if not session_record:
            return None

        return session_record.user

    @staticmethod
    def revoke_session(
        db: Session,
        raw_token: str,
    ) -> bool:
        """Revoke a session by setting revoked_at timestamp upon logout."""
        if not raw_token:
            return False

        token_hash = hash_session_token(raw_token)
        stmt = select(UserSession).where(
            UserSession.token_hash == token_hash,
            UserSession.revoked_at.is_(None),
        )
        session_record = db.scalar(stmt)
        if not session_record:
            return False

        session_record.revoked_at = datetime.now(timezone.utc)
        db.commit()
        return True
