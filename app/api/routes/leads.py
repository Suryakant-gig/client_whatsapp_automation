"""API routes for Lead Management."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.lead_schemas import (
    LeadConsentUpdate,
    LeadCreate,
    LeadDetailResponse,
    LeadListResponse,
    LeadResponse,
    LeadUpdate,
    MarkFollowedUpRequest,
)
from app.services.lead_service import (
    LeadDuplicateError,
    LeadNotFoundError,
    LeadService,
    LeadValidationError,
)

router = APIRouter(prefix="/api/leads", tags=["Lead Management"])


@router.get(
    "",
    response_model=LeadListResponse,
    status_code=status.HTTP_200_OK,
    summary="List leads with search, filtering, and pagination",
)
def list_leads(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=50, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(default=None, description="Search term for name, phone, or serial number"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status (Pending, Replied, Not Interested, Interested)"),
    opt_in_status: Optional[str] = Query(default=None, description="Filter by consent status (OPTED_IN, NOT_OPTED_IN, OPTED_OUT)"),
    follow_up_paused: Optional[bool] = Query(default=None, description="Filter by follow-up paused status"),
    needs_manual_followup: Optional[bool] = Query(default=None, description="Filter by manual phone call needed flag"),
    sort_by: str = Query(default="created_at", description="Field to sort by (created_at, customer_name, id, last_replied_at)"),
    sort_order: str = Query(default="desc", description="Sorting order (asc or desc)"),
    db: Session = Depends(get_db),
) -> LeadListResponse:
    """Retrieve paginated leads with flexible filtering and sorting."""
    return LeadService.list_leads(
        db=db,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        opt_in_status=opt_in_status,
        follow_up_paused=follow_up_paused,
        needs_manual_followup=needs_manual_followup,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/{lead_id}",
    response_model=LeadResponse,
    status_code=status.HTTP_200_OK,
    summary="Get lead details by ID",
)
def get_lead(
    lead_id: int,
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Retrieve full details for a single lead."""
    try:
        lead = LeadService.get_lead_by_id(db, lead_id)
        return LeadResponse.model_validate(lead)
    except LeadNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.get(
    "/{lead_id}/detail",
    response_model=LeadDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get lead details with follow-ups and interaction history",
)
def get_lead_detail(
    lead_id: int,
    db: Session = Depends(get_db),
) -> LeadDetailResponse:
    """Retrieve full details for a single lead including follow-up schedules and message interaction history."""
    try:
        return LeadService.get_lead_details(db, lead_id)
    except LeadNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e


@router.post(
    "",
    response_model=LeadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new lead manually",
)
def create_lead(
    payload: LeadCreate,
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Create a new customer lead record."""
    try:
        lead = LeadService.create_lead(db, payload)
        return LeadResponse.model_validate(lead)
    except LeadDuplicateError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except (LeadValidationError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


@router.patch(
    "/{lead_id}",
    response_model=LeadResponse,
    status_code=status.HTTP_200_OK,
    summary="Update lead details",
)
def update_lead(
    lead_id: int,
    payload: LeadUpdate,
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Update lead attributes with business validation."""
    try:
        lead = LeadService.update_lead(db, lead_id, payload)
        return LeadResponse.model_validate(lead)
    except LeadNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except LeadDuplicateError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except (LeadValidationError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


@router.post(
    "/{lead_id}/pause-followups",
    response_model=LeadResponse,
    status_code=status.HTTP_200_OK,
    summary="Pause automated follow-ups for lead",
)
def pause_lead_followups(
    lead_id: int,
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Explicitly pause follow-up schedules for the specified lead."""
    try:
        lead = LeadService.pause_follow_ups(db, lead_id)
        return LeadResponse.model_validate(lead)
    except LeadNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except (LeadValidationError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


@router.post(
    "/{lead_id}/resume-followups",
    response_model=LeadResponse,
    status_code=status.HTTP_200_OK,
    summary="Resume automated follow-ups for lead",
)
def resume_lead_followups(
    lead_id: int,
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Explicitly resume follow-up schedules for the specified lead."""
    try:
        lead = LeadService.resume_follow_ups(db, lead_id)
        return LeadResponse.model_validate(lead)
    except LeadNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except (LeadValidationError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


@router.post(
    "/{lead_id}/mark-followed-up",
    response_model=LeadResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark an interested lead as followed up via phone call",
)
def mark_lead_followed_up(
    lead_id: int,
    payload: Optional[MarkFollowedUpRequest] = None,
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Mark lead as contacted, clear needs_manual_followup flag, and record call notes."""
    notes = payload.notes if payload else None
    try:
        lead = LeadService.mark_followed_up(db=db, lead_id=lead_id, notes=notes)
        return LeadResponse.model_validate(lead)
    except LeadNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except (LeadValidationError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


@router.post(
    "/{lead_id}/consent",
    response_model=LeadResponse,
    status_code=status.HTTP_200_OK,
    summary="Update WhatsApp messaging opt-in consent status",
)
def update_lead_consent(
    lead_id: int,
    payload: LeadConsentUpdate,
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Document recipient's opt-in consent or opt-out suppression for WhatsApp communication."""
    try:
        lead = LeadService.update_consent(
            db=db,
            lead_id=lead_id,
            opt_in_status=payload.opt_in_status,
            opt_in_source=payload.opt_in_source,
        )
        return LeadResponse.model_validate(lead)
    except LeadNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except (LeadValidationError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e


@router.delete(
    "/{lead_id}",
    response_model=LeadResponse,
    status_code=status.HTTP_200_OK,
    summary="Soft-delete lead and cancel pending follow-ups",
)
def delete_lead(
    lead_id: int,
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Soft delete lead, cancel pending follow-ups, and preserve communications history."""
    try:
        lead = LeadService.delete_lead(db, lead_id)
        return LeadResponse.model_validate(lead)
    except LeadNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except (LeadValidationError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e
