"""In-memory rate limiter for brute-force prevention on authentication endpoints."""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple
import threading


class LoginRateLimiter:
    """Thread-safe sliding-window rate limiter for failed login attempts."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._attempts: Dict[str, List[datetime]] = {}

    def _get_key(self, ip_address: str, username: str) -> str:
        """Create a composite tracking key."""
        clean_ip = (ip_address or "unknown").strip().lower()
        clean_user = (username or "anonymous").strip().lower()
        return f"{clean_ip}:{clean_user}"

    def is_rate_limited(self, ip_address: str, username: str) -> Tuple[bool, int]:
        """Check if client IP / username is currently rate-limited.

        Returns (is_limited: bool, retry_after_seconds: int).
        """
        key = self._get_key(ip_address, username)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=self.window_seconds)

        with self._lock:
            timestamps = self._attempts.get(key, [])
            # Filter timestamps within active window
            recent = [ts for ts in timestamps if ts > cutoff]
            self._attempts[key] = recent

            if len(recent) >= self.max_attempts:
                oldest_in_window = recent[0]
                remaining = int((oldest_in_window + timedelta(seconds=self.window_seconds) - now).total_seconds())
                return True, max(remaining, 1)

            return False, 0

    def record_failure(self, ip_address: str, username: str) -> None:
        """Record a failed login attempt."""
        key = self._get_key(ip_address, username)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=self.window_seconds)

        with self._lock:
            timestamps = self._attempts.get(key, [])
            recent = [ts for ts in timestamps if ts > cutoff]
            recent.append(now)
            self._attempts[key] = recent

    def record_success(self, ip_address: str, username: str) -> None:
        """Clear failed attempts upon successful login."""
        key = self._get_key(ip_address, username)
        with self._lock:
            self._attempts.pop(key, None)

    def reset(self) -> None:
        """Reset all rate limiter state (useful in test teardown)."""
        with self._lock:
            self._attempts.clear()


# Global rate limiter instance
login_rate_limiter = LoginRateLimiter(max_attempts=5, window_seconds=300)
