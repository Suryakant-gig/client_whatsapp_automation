"""API routes for application settings and diagnostics."""

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db

router = APIRouter(prefix="/api/settings", tags=["Settings"])


@router.get(
    "/diagnostics",
    status_code=status.HTTP_200_OK,
    summary="Retrieve system diagnostics and integration health matrix",
)
def get_settings_diagnostics(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return health metrics, database connectivity status, and WhatsApp integration mode."""
    settings = get_settings()
    db_status = "Connected"
    db_version = "PostgreSQL"
    try:
        ver = db.execute(text("SELECT version();")).scalar()
        if ver:
            db_version = str(ver).split(",")[0].strip()
    except Exception as e:
        db_status = f"Error: {str(e)}"

    return {
        "status": "healthy" if db_status == "Connected" else "degraded",
        "database": {
            "engine": "Neon PostgreSQL (psycopg 3)",
            "status": db_status,
            "version": db_version,
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
        },
        "dispatch_engine": {
            "type": "Immediate & Manual Dispatch",
            "scheduler_enabled": False,
            "status": "Active",
        },
        "whatsapp": {
            "enabled": settings.WHATSAPP_ENABLED,
            "mode": "Live Broadcast" if settings.WHATSAPP_ENABLED else "Mock Sandbox (Outbound Disabled)",
            "phone_number": settings.WHATSAPP_PHONE_NUMBER or "Not Configured",
            "phone_number_id_configured": bool(settings.WHATSAPP_PHONE_NUMBER_ID),
            "waba_id_configured": bool(settings.WHATSAPP_BUSINESS_ACCOUNT_ID),
        },
        "server_time": datetime.now(timezone.utc).isoformat(),
    }
