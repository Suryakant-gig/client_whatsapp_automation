"""API routes for CRM Dashboard statistics and activity."""

from typing import List

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.dashboard_schemas import (
    ActivityItemResponse,
    DashboardOverviewResponse,
    DashboardStatsResponse,
)
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get(
    "/stats",
    response_model=DashboardStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve aggregated database statistics for CRM dashboard",
)
def get_dashboard_stats(
    db: Session = Depends(get_db),
) -> DashboardStatsResponse:
    """Return aggregated counts for leads, campaigns, messages, and schedules computed directly in SQLite."""
    return DashboardService.get_stats(db)


@router.get(
    "/recent-activity",
    response_model=List[ActivityItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve chronological timeline of recent CRM events",
)
def get_recent_activity(
    limit: int = Query(default=10, ge=1, le=50, description="Maximum number of activity events to return"),
    db: Session = Depends(get_db),
) -> List[ActivityItemResponse]:
    """Return combined recent activity across message logs, inbound messages, and sync operations."""
    return DashboardService.get_recent_activity(db, limit=limit)


@router.get(
    "/overview",
    response_model=DashboardOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve combined dashboard metrics, recent activity, and system status",
)
def get_dashboard_overview(
    db: Session = Depends(get_db),
) -> DashboardOverviewResponse:
    """Return comprehensive dashboard data payload for the single-page overview."""
    return DashboardService.get_overview(db)
