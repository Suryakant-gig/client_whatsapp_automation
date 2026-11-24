"""API routes for Respondent management, classification, and manual contact."""

from typing import Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.respondent_schemas import (
    ManualContactRequest,
    ManualContactResponse,
    RespondentClassificationUpdate,
    RespondentDetailResponse,
    RespondentListResponse,
    RespondentNotesUpdate,
    RespondentResponse,
)
from app.services.respondent_service import RespondentService

router = APIRouter(prefix="/api/respondents", tags=["Respondents"])


@router.get(
    "",
    response_model=RespondentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List respondents with classification filter and pagination",
)
def list_respondents(
    classification: Optional[str] = Query(
        default=None,
        description="Filter by classification (UNCLASSIFIED, INTERESTED, NOT_INTERESTED, OTHER)",
    ),
    search: Optional[str] = Query(
        default=None,
        description="Search by name, phone number, or notes",
    ),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=20, ge=1, le=100, description="Page size"),
    db: Session = Depends(get_db),
) -> RespondentListResponse:
    """Retrieve list of customer WhatsApp respondents with classification filtering."""
    return RespondentService.list_respondents(
        db=db,
        classification=classification,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/stats",
    response_model=Dict[str, int],
    status_code=status.HTTP_200_OK,
    summary="Get count summary of respondents by classification",
)
def get_respondent_stats(
    db: Session = Depends(get_db),
) -> Dict[str, int]:
    """Retrieve summary counts of respondents across all classifications."""
    return RespondentService.get_respondent_stats(db=db)


@router.get(
    "/{respondent_id}",
    response_model=RespondentDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get respondent details and conversation history",
)
def get_respondent(
    respondent_id: int,
    db: Session = Depends(get_db),
) -> RespondentDetailResponse:
    """Retrieve respondent details along with full chronological message history."""
    try:
        r = RespondentService.get_respondent(db=db, respondent_id=respondent_id)
        history = RespondentService.get_conversation_history(db=db, respondent_id=respondent_id)
        return RespondentDetailResponse(
            respondent=RespondentService._to_response_item(r),
            conversation_history=history,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch(
    "/{respondent_id}/classification",
    response_model=RespondentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update respondent classification",
)
def update_classification(
    respondent_id: int,
    payload: RespondentClassificationUpdate,
    db: Session = Depends(get_db),
) -> RespondentResponse:
    """Manually update the classification for a respondent (UNCLASSIFIED, INTERESTED, NOT_INTERESTED, OTHER)."""
    try:
        return RespondentService.update_classification(
            db=db,
            respondent_id=respondent_id,
            new_classification=payload.classification,
        )
    except ValueError as exc:
        err = str(exc)
        if "not exist" in err.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err) from exc


@router.patch(
    "/{respondent_id}/notes",
    response_model=RespondentResponse,
    status_code=status.HTTP_200_OK,
    summary="Update internal notes on respondent",
)
def update_notes(
    respondent_id: int,
    payload: RespondentNotesUpdate,
    db: Session = Depends(get_db),
) -> RespondentResponse:
    """Save or update internal travel agency notes for a respondent."""
    try:
        return RespondentService.update_notes(
            db=db,
            respondent_id=respondent_id,
            internal_notes=payload.internal_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{respondent_id}/contact",
    response_model=ManualContactResponse,
    status_code=status.HTTP_200_OK,
    summary="Manually send a WhatsApp message to an interested respondent",
)
def manual_contact(
    respondent_id: int,
    payload: ManualContactRequest,
    db: Session = Depends(get_db),
) -> ManualContactResponse:
    """Send an immediate manual WhatsApp message to a respondent.
    
    Adheres strictly to Meta's messaging rules:
    - Freeform text permitted within 24-hour window from customer's last reply.
    - Approved template mandatory outside the 24-hour window.
    - Opt-out restriction enforced (cannot contact opted-out contacts).
    - Immediate dispatch only; never creates future scheduling jobs.
    """
    try:
        return RespondentService.manual_contact(
            db=db,
            respondent_id=respondent_id,
            payload=payload,
        )
    except ValueError as exc:
        err = str(exc)
        if "not exist" in err.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to dispatch manual contact: {str(exc)}",
        ) from exc
