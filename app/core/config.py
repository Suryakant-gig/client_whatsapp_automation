"""Application configuration management using Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application Information
    APP_NAME: str = Field(
        default="travel-agency-automation",
        description="Name of the application",
    )
    APP_ENV: Literal["development", "testing", "production"] = Field(
        default="development",
        description="Deployment environment",
    )
    DEBUG: bool = Field(
        default=False,
        description="Debug mode toggle",
    )

    # Server Bind Configuration
    HOST: str = Field(
        default="127.0.0.1",
        description="Host interface to bind the application server",
    )
    PORT: int = Field(
        default=8000,
        description="Port to bind the application server",
    )

    # Logging Configuration
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Standard logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    # Database Configuration
    DATABASE_URL: str = Field(
        default="sqlite:///./travel_agency.db",
        description="SQLAlchemy database connection string",
    )

    # Excel Integration Configuration
    MAX_UPLOAD_SIZE_BYTES: int = Field(
        default=10 * 1024 * 1024,  # 10 MB
        description="Maximum allowed file upload size in bytes",
    )
    AUTHORIZED_EXCEL_PATH: str = Field(
        default="./data/leads.xlsx",
        description="Authorized path to the synchronized Excel/CSV workbook",
    )
    BACKUP_DIR: str = Field(
        default="./data/backups",
        description="Directory where timestamped workbook backups are stored",
    )
    DEFAULT_FOLLOW_UP_LIMIT: int = Field(
        default=5,
        description="Default number of follow-ups allowed per lead",
    )

    # Scheduler Configuration (Phase 5)
    ENABLE_SCHEDULER: bool = Field(
        default=True,
        description="Toggle background APScheduler execution",
    )
    SCHEDULER_TIMEZONE: str = Field(
        default="Asia/Kolkata",
        description="Timezone used for local business scheduling and evaluation",
    )
    SCHEDULER_POLL_INTERVAL_SECONDS: int = Field(
        default=60,
        description="Interval in seconds between scheduler polling cycles",
    )

    # Meta WhatsApp Cloud API Configuration (Phase 6 & 7)
    WHATSAPP_ENABLED: bool = Field(
        default=False,
        description="Master toggle enabling outbound Meta WhatsApp Cloud API calls",
    )
    WHATSAPP_PHONE_NUMBER: str = Field(
        default="",
        description="Sender WhatsApp Business display phone number (e.g. +919853763511)",
    )
    WHATSAPP_PHONE_NUMBER_ID: str = Field(
        default="",
        description="WhatsApp Business Account Phone Number ID",
    )
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = Field(
        default="",
        description="WhatsApp Business Account ID (WABA ID)",
    )
    META_APP_ID: str = Field(
        default="",
        description="Meta Application ID",
    )
    META_APP_SECRET: str = Field(
        default="",
        description="Meta Application Secret for webhook signature verification",
    )
    WHATSAPP_ACCESS_TOKEN: str = Field(
        default="",
        description="Permanent System User Access Token for Meta Graph API",
    )
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = Field(
        default="",
        description="Verification token for Meta Webhook challenges",
    )
    WHATSAPP_API_VERSION: str = Field(
        default="v21.0",
        description="Meta Graph API version",
    )
    WHATSAPP_API_BASE_URL: str = Field(
        default="https://graph.facebook.com",
        description="Base URL for Meta Graph API calls",
    )
    WHATSAPP_REQUEST_TIMEOUT_SECONDS: float = Field(
        default=15.0,
        description="HTTP request timeout in seconds for WhatsApp Cloud API calls",
    )

    # Authentication & Session Security (Phase 9.2)
    SESSION_COOKIE_NAME: str = Field(
        default="travel_crm_session",
        description="Name of the HTTP-only session cookie",
    )
    SESSION_MAX_AGE_SECONDS: int = Field(
        default=86400,  # 24 hours
        description="Session duration in seconds before expiration",
    )
    SESSION_COOKIE_SECURE: bool = Field(
        default=False,
        description="Enforce Secure flag on cookies (set to True when deployed with HTTPS)",
    )
    SESSION_COOKIE_SAMESITE: str = Field(
        default="lax",
        description="SameSite cookie policy (lax or strict)",
    )
    CSRF_COOKIE_NAME: str = Field(
        default="travel_crm_csrf",
        description="Name of the double-submit CSRF cookie",
    )
    SETUP_SECRET: str = Field(
        default="N5Gknjmd398RggNcdQIj9O5AcMsPgznrdWZH_vo4CfU",
        description="Secret key required for initial administrator bootstrapping",
    )

    @property
    def is_whatsapp_configured(self) -> bool:
        """Validate if required WhatsApp Cloud API credentials are fully configured."""
        return bool(
            self.WHATSAPP_ENABLED
            and self.WHATSAPP_ACCESS_TOKEN.strip()
            and self.WHATSAPP_PHONE_NUMBER_ID.strip()
        )


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings."""
    return Settings()
