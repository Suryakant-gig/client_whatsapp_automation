"""Health check endpoint definition."""

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.core.config import get_settings

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    """Schema for health check response."""

    status: str = Field(
        default="healthy",
        description="Current health status of the application",
        examples=["healthy"],
    )
    application: str = Field(
        default="travel-agency-automation",
        description="Application identifier",
        examples=["travel-agency-automation"],
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Application Health Check",
    description="Returns the operational status and application name.",
)
def get_health() -> HealthResponse:
    """Check application health status."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        application=settings.APP_NAME,
    )
