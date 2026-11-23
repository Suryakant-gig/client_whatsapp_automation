"""WhatsApp Cloud API integration package."""

from app.integrations.whatsapp.client import WhatsAppCloudClient
from app.integrations.whatsapp.exceptions import (
    TemplateNotApprovedError,
    TemplateValidationError,
    WhatsAppAPIError,
    WhatsAppAuthError,
    WhatsAppConfigError,
    WhatsAppConnectionError,
    WhatsAppConsentError,
    WhatsAppError,
    WhatsAppRateLimitError,
    WhatsAppServerError,
    WhatsAppTimeoutError,
)

__all__ = [
    "WhatsAppCloudClient",
    "WhatsAppError",
    "WhatsAppConfigError",
    "WhatsAppAuthError",
    "WhatsAppRateLimitError",
    "WhatsAppAPIError",
    "WhatsAppServerError",
    "WhatsAppTimeoutError",
    "WhatsAppConnectionError",
    "WhatsAppConsentError",
    "TemplateNotApprovedError",
    "TemplateValidationError",
]
