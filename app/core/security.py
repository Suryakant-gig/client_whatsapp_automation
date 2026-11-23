"""Cryptographic security utilities for password hashing and session tokens."""

import hashlib
import hmac
import secrets
from typing import Tuple

PBKDF2_ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000
SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


class PasswordValidationError(ValueError):
    """Raised when password fails complexity or length rules."""
    pass


def validate_password_strength(password: str) -> None:
    """Validate password input length and reject empty or invalid values."""
    if not password or not isinstance(password, str):
        raise PasswordValidationError("Password must be a non-empty string")
    
    # Strip check - password should not consist solely of whitespace
    if len(password.strip()) == 0:
        raise PasswordValidationError("Password cannot be only whitespace")

    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
        )

    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordValidationError(
            f"Password must not exceed {MAX_PASSWORD_LENGTH} characters"
        )


def hash_password(password: str, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with unique random salt.

    Returns versioned format: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
    """
    validate_password_strength(password)
    salt_hex = secrets.token_hex(SALT_BYTES)
    derived_bytes = hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=password.encode("utf-8"),
        salt=salt_hex.encode("utf-8"),
        iterations=iterations,
    )
    hash_hex = derived_bytes.hex()
    return f"{PBKDF2_ALGORITHM}${iterations}${salt_hex}${hash_hex}"


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify password against versioned PBKDF2-HMAC-SHA256 hash using constant-time comparison."""
    if not plain_password or not password_hash:
        return False

    parts = password_hash.split("$")
    if len(parts) != 4:
        return False

    algorithm, iterations_str, salt_hex, expected_hash_hex = parts
    if algorithm != PBKDF2_ALGORITHM:
        return False

    try:
        iterations = int(iterations_str)
        if iterations <= 0:
            return False
    except ValueError:
        return False

    derived_bytes = hashlib.pbkdf2_hmac(
        hash_name="sha256",
        password=plain_password.encode("utf-8"),
        salt=salt_hex.encode("utf-8"),
        iterations=iterations,
    )
    computed_hash_hex = derived_bytes.hex()
    return hmac.compare_digest(computed_hash_hex, expected_hash_hex)


def generate_session_token() -> str:
    """Generate high-entropy cryptographically secure raw session token."""
    return secrets.token_urlsafe(32)


def hash_session_token(raw_token: str) -> str:
    """Compute SHA-256 hex digest of raw session token for database persistence."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_csrf_token() -> str:
    """Generate cryptographically secure CSRF token."""
    return secrets.token_urlsafe(32)
