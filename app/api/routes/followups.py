"""API routes for Follow-up Schedule management."""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.followup_schemas import (
    FollowUpCreate,
    FollowUpListResponse,
    FollowUpResponse,
    FollowUpUpdate,
)
from app.services.followup_service import (
    FollowUpAlreadyProcessedError,
    FollowUpLimitReachedError,
    FollowUpNotFoundError,
    FollowUpService,
    FollowUpValidationError,
)

router = APIRouter(prefix="/api/followups", tags=["Follow-up Schedules"])


@router.post(
    "",
    response_model=FollowUpResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new follow-up schedule",
)
def create_followup(
    payload: FollowUpCreate,
    db: Session = Depends(get_db),
) -> FollowUpResponse:
    """Schedule a new customer follow-up."""
    try:
        schedule = FollowUpService.create_followup(db, payload)
        return FollowUpResponse.model_validate(schedule)
    except FollowUpValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
    except FollowUpLimitReachedError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create follow-up: {str(e)}",
        ) from e


@router.get(
    "",
    response_model=FollowUpListResponse,
    status_code=status.HTTP_200_OK,
    summary="List follow-up schedules with filters and pagination",
)
def list_followups(
    lead_id: Optional[int] = Query(default=None, description="Filter by customer Lead ID"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status (Scheduled, Approved, Sent, Skipped, Failed, Cancelled)"),
    start_date: Optional[datetime] = Query(default=None, description="Filter schedules on or after this timestamp"),
    end_date: Optional[datetime] = Query(default=None, description="Filter schedules on or before this timestamp"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=100, description="Page size"),
    db: Session = Depends(get_db),
) -> FollowUpListResponse:
    """Retrieve list of scheduled follow-ups."""
    return FollowUpService.list_followups(
        db=db,
        lead_id=lead_id,
        status=status_filter,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/process-due",
    status_code=status.HTTP_200_OK,
    summary="Trigger immediate processing of all due follow-ups",
)
def process_due_followups(
    db: Session = Depends(get_db),
) -> dict:
    """Manually invoke the follow-up dispatcher to process pending due schedules immediately."""
    sent, skipped, failed = FollowUpService.process_due_schedules(db=db)
    return {
        "status": "ok",
        "sent_count": sent,
        "skipped_count": skipped,
        "failed_count": failed,
        "message": f"Processed due follow-ups: {sent} sent, {skipped} skipped, {failed} failed.",
    }


@router.get(
    "/{followup_id}",
    response_model=FollowUpResponse,
    status_code=status.HTTP_200_OK,
    summary="Get single follow-up schedule by ID",
)
def get_followup(
    followup_id: int,
    db: Session = Depends(get_db),
) -> FollowUpResponse:
    """Retrieve details for a single follow-up schedule."""
    try:
        schedule = FollowUpService.get_followup_by_id(db, followup_id)
        return FollowUpResponse.model_validate(schedule)
    except FollowUpNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.patch(
    "/{followup_id}",
    response_model=FollowUpResponse,
    status_code=status.HTTP_200_OK,
    summary="Update scheduled time for an unprocessed follow-up",
)
def update_followup(
    followup_id: int,
    payload: FollowUpUpdate,
    db: Session = Depends(get_db),
) -> FollowUpResponse:
    """Modify scheduled time. Only allowed for unprocessed items (Scheduled or Approved)."""
    try:
        schedule = FollowUpService.update_followup(db, followup_id, payload)
        return FollowUpResponse.model_validate(schedule)
    except FollowUpNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except FollowUpAlreadyProcessedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.post(
    "/{followup_id}/cancel",
    response_model=FollowUpResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a scheduled follow-up",
)
def cancel_followup(
    followup_id: int,
    db: Session = Depends(get_db),
) -> FollowUpResponse:
    """Cancel a pending follow-up. Already sent follow-ups cannot be cancelled."""
    try:
        schedule = FollowUpService.cancel_followup(db, followup_id)
        return FollowUpResponse.model_validate(schedule)
    except FollowUpNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except FollowUpAlreadyProcessedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
