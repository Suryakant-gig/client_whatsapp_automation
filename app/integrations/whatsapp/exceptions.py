"""Exceptions for Meta WhatsApp Cloud API integration."""

from typing import Any, Dict, Optional


class WhatsAppError(Exception):
    """Base exception for all WhatsApp integration errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class WhatsAppConfigError(WhatsAppError):
    """Raised when WhatsApp settings or credentials are missing or invalid."""
    pass


class WhatsAppAuthError(WhatsAppError):
    """Raised when Meta API rejects authentication (HTTP 401 / 403)."""

    def __init__(self, message: str = "Meta WhatsApp API authentication failed", error_code: Optional[int] = None):
        super().__init__(message, {"error_code": error_code})
        self.error_code = error_code


class WhatsAppRateLimitError(WhatsAppError):
    """Raised when Meta API rate limits are hit (HTTP 429)."""

    def __init__(self, message: str = "Meta WhatsApp API rate limit exceeded", retry_after: Optional[int] = None):
        super().__init__(message, {"retry_after": retry_after})
        self.retry_after = retry_after


class WhatsAppAPIError(WhatsAppError):
    """Raised when Meta API returns a client error response (HTTP 400)."""

    def __init__(
        self,
        message: str,
        error_code: Optional[int] = None,
        error_subcode: Optional[int] = None,
        fbtrace_id: Optional[str] = None,
    ):
        super().__init__(
            message,
            {
                "error_code": error_code,
                "error_subcode": error_subcode,
                "fbtrace_id": fbtrace_id,
            },
        )
        self.error_code = error_code
        self.error_subcode = error_subcode
        self.fbtrace_id = fbtrace_id


class WhatsAppServerError(WhatsAppError):
    """Raised when Meta API experiences internal server errors (HTTP 500+)."""

    def __init__(self, message: str = "Meta WhatsApp API server error", status_code: int = 500):
        super().__init__(message, {"status_code": status_code})
        self.status_code = status_code


class WhatsAppTimeoutError(WhatsAppError):
    """Raised when an API request to Meta times out."""

    def __init__(self, message: str = "Meta WhatsApp API request timed out"):
        super().__init__(message)


class WhatsAppConnectionError(WhatsAppError):
    """Raised on network or connection errors communicating with Meta."""

    def __init__(self, message: str = "Failed to connect to Meta WhatsApp API"):
        super().__init__(message)


class WhatsAppConsentError(WhatsAppError):
    """Raised when recipient has not consented (opted-in) or has opted out."""

    def __init__(self, message: str = "Lead has not provided opt-in consent for WhatsApp messaging"):
        super().__init__(message)


class TemplateNotApprovedError(WhatsAppError):
    """Raised when attempting to send an unapproved or rejected template."""

    def __init__(self, template_name: str, status: str):
        super().__init__(
            f"Template '{template_name}' cannot be sent because its status is '{status}'. Only APPROVED templates are permitted."
        )
        self.template_name = template_name
        self.status = status


class TemplateValidationError(WhatsAppError):
    """Raised when template parameters do not match expected schema."""
    pass
