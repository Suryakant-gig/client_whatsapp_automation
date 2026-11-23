"""API endpoints for Campaign Management, Batch Approval, and Sending (Phase 8)."""

from datetime import datetime, timezone
import math
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.models.campaign import Campaign, CampaignBatch
from app.db.session import get_db
from app.schemas.campaign_schemas import (
    BatchApprovalResponse,
    BatchGenerateRequest,
    BatchListResponse,
    BatchRecipientResponse,
    BatchRejectResponse,
    BatchResponse,
    BatchSendResponse,
    CampaignCreate,
    CampaignListResponse,
    CampaignReportResponse,
    CampaignResponse,
    CampaignUpdate,
    EligibleLeadItem,
    EligibleLeadsSummaryResponse,
    FailedRecipientResponse,
    GlobalBatchListResponse,
    GlobalBatchResponse,
)
from app.services.campaign_service import CampaignService

router = APIRouter(prefix="/api/campaigns", tags=["Campaigns"])


def format_batch_response(batch: CampaignBatch, include_recipients: bool = False) -> BatchResponse:
    """Format CampaignBatch entity into BatchResponse schema with normalized approval status."""
    approval_display = "PENDING_APPROVAL" if batch.approval_status == "Pending" else batch.approval_status

    recipients_list = None
    if include_recipients and batch.recipients:
        recipients_list = [
            BatchRecipientResponse(
                id=r.id,
                batch_id=r.batch_id,
                lead_id=r.lead_id,
                customer_name=r.lead.customer_name if r.lead else None,
                phone_number=r.lead.phone_number if r.lead else None,
                send_status=r.send_status,
                message_log_id=r.message_log_id,
                sent_at=r.sent_at,
                error_details=r.error_details,
            )
            for r in batch.recipients
        ]

    return BatchResponse(
        id=batch.id,
        campaign_id=batch.campaign_id,
        batch_number=batch.batch_number,
        batch_size=batch.batch_size,
        approval_status=approval_display,
        approved_at=batch.approved_at,
        send_status=batch.send_status,
        sent_at=batch.sent_at,
        scheduled_at=batch.scheduled_at,
        total_messages_count=batch.total_messages_count,
        sent_messages_count=batch.sent_messages_count,
        failed_messages_count=batch.failed_messages_count,
        created_at=batch.created_at,
        recipients=recipients_list,
    )


def format_campaign_response(campaign: Campaign) -> CampaignResponse:
    """Format Campaign model to CampaignResponse."""
    return CampaignResponse(
        id=campaign.id,
        campaign_name=campaign.campaign_name,
        template_name=campaign.template_name,
        template_language=campaign.template_language,
        status=campaign.status,
        total_leads_selected=campaign.total_leads_selected,
        total_leads_eligible=campaign.total_leads_eligible,
        total_leads_excluded=campaign.total_leads_excluded,
        batch_count=len(campaign.batches) if campaign.batches else 0,
        scheduled_at=campaign.scheduled_at,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
    )


@router.post(
    "",
    response_model=CampaignResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new marketing/follow-up broadcast campaign",
)
def create_campaign(
    payload: CampaignCreate,
    db: Session = Depends(get_db),
) -> CampaignResponse:
    """Create a campaign with an approved WhatsApp template and partition eligible opted-in leads."""
    try:
        campaign, _, _ = CampaignService.create_campaign(db=db, payload=payload)
        return format_campaign_response(campaign)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "",
    response_model=CampaignListResponse,
    status_code=status.HTTP_200_OK,
    summary="List broadcast campaigns with pagination",
)
def list_campaigns(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    campaign_status: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> CampaignListResponse:
    """Retrieve paginated list of campaigns with optional status filtering."""
    items, total = CampaignService.list_campaigns(
        db=db, page=page, page_size=page_size, status=campaign_status
    )
    pages = math.ceil(total / page_size) if total > 0 else 1
    return CampaignListResponse(
        items=[format_campaign_response(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get(
    "/batches/all",
    response_model=GlobalBatchListResponse,
    status_code=status.HTTP_200_OK,
    summary="List batches across all campaigns with filtering and pagination",
)
def list_all_batches(
    approval_status: Optional[str] = Query(default=None, description="Filter by approval status (Pending, Approved, Rejected, All)"),
    send_status: Optional[str] = Query(default=None, description="Filter by send status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> GlobalBatchListResponse:
    """Retrieve batches across all campaigns for the Batch Approvals interface."""
    items, total = CampaignService.list_all_batches(
        db=db,
        approval_status=approval_status,
        send_status=send_status,
        page=page,
        page_size=page_size,
    )
    pages = math.ceil(total / page_size) if total > 0 else 1
    return GlobalBatchListResponse(
        items=[GlobalBatchResponse(**b) for b in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get(
    "/batches/pending",
    response_model=GlobalBatchListResponse,
    status_code=status.HTTP_200_OK,
    summary="Convenience endpoint to list all batches pending administrator approval",
)
def list_pending_batches(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> GlobalBatchListResponse:
    """Retrieve all batches pending approval across all campaigns."""
    items, total = CampaignService.list_all_batches(
        db=db,
        approval_status="Pending",
        page=page,
        page_size=page_size,
    )
    pages = math.ceil(total / page_size) if total > 0 else 1
    return GlobalBatchListResponse(
        items=[GlobalBatchResponse(**b) for b in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get(
    "/eligible-summary",
    response_model=EligibleLeadsSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Summary count of leads currently eligible for campaign broadcast",
)
def get_eligible_summary(
    db: Session = Depends(get_db),
) -> EligibleLeadsSummaryResponse:
    """Retrieve candidate recipient eligibility counts for campaign creation."""
    counts = CampaignService.get_eligible_summary(db=db)
    return EligibleLeadsSummaryResponse(**counts)


@router.get(
    "/eligible-leads",
    response_model=List[EligibleLeadItem],
    status_code=status.HTTP_200_OK,
    summary="List candidate leads eligible for broadcast targeting",
)
def get_eligible_leads(
    db: Session = Depends(get_db),
) -> List[EligibleLeadItem]:
    """Retrieve list of candidate leads eligible for targeted broadcast campaign creation."""
    return [EligibleLeadItem(**item) for item in CampaignService.get_eligible_leads_list(db)]


@router.get(
    "/{campaign_id}",
    response_model=CampaignResponse,
    status_code=status.HTTP_200_OK,
    summary="Get campaign details by ID",
)
def get_campaign(
    campaign_id: int,
    db: Session = Depends(get_db),
) -> CampaignResponse:
    """Retrieve campaign metadata and batch counts."""
    try:
        campaign = CampaignService.get_campaign(db=db, campaign_id=campaign_id)
        return format_campaign_response(campaign)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch(
    "/{campaign_id}",
    response_model=CampaignResponse,
    status_code=status.HTTP_200_OK,
    summary="Update campaign details (Draft/Scheduled only)",
)
def update_campaign(
    campaign_id: int,
    payload: CampaignUpdate,
    db: Session = Depends(get_db),
) -> CampaignResponse:
    """Update campaign metadata when in Draft or Scheduled status."""
    try:
        campaign = CampaignService.update_campaign(
            db=db, campaign_id=campaign_id, payload=payload
        )
        return format_campaign_response(campaign)
    except ValueError as exc:
        err = str(exc)
        if "not exist" in err.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err) from exc


@router.post(
    "/{campaign_id}/generate-batches",
    response_model=BatchListResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Partition eligible campaign leads into configurable batches",
)
def generate_batches(
    campaign_id: int,
    payload: BatchGenerateRequest,
    db: Session = Depends(get_db),
) -> BatchListResponse:
    """Generate sequential batches for an existing campaign."""
    try:
        batches, _ = CampaignService.generate_batches(
            db=db,
            campaign_id=campaign_id,
            lead_ids=payload.lead_ids,
            batch_size=payload.batch_size,
            max_recipients=payload.max_recipients,
            carry_forward_interval_hours=payload.carry_forward_interval_hours,
        )
        return BatchListResponse(
            items=[format_batch_response(b) for b in batches],
            total=len(batches),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/{campaign_id}/batches",
    response_model=BatchListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all batches for a campaign",
)
def list_batches(
    campaign_id: int,
    db: Session = Depends(get_db),
) -> BatchListResponse:
    """Retrieve all recipient batches associated with the specified campaign."""
    try:
        batches = CampaignService.list_batches(db=db, campaign_id=campaign_id)
        return BatchListResponse(
            items=[format_batch_response(b) for b in batches],
            total=len(batches),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{campaign_id}/batches/{batch_id}",
    response_model=BatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Get batch details and recipient list",
)
def get_batch(
    campaign_id: int,
    batch_id: int,
    db: Session = Depends(get_db),
) -> BatchResponse:
    """Retrieve specific batch status with full recipient list."""
    try:
        batch = CampaignService.get_batch(db=db, campaign_id=campaign_id, batch_id=batch_id)
        return format_batch_response(batch, include_recipients=True)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{campaign_id}/batches/{batch_id}/approve",
    response_model=BatchApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Mandatory individual batch approval",
)
def approve_batch(
    campaign_id: int,
    batch_id: int,
    db: Session = Depends(get_db),
) -> BatchApprovalResponse:
    """Perform mandatory human approval for an individual batch before message sending."""
    try:
        batch = CampaignService.approve_batch(db=db, campaign_id=campaign_id, batch_id=batch_id)
        return BatchApprovalResponse(
            batch_id=batch.id,
            campaign_id=batch.campaign_id,
            batch_number=batch.batch_number,
            approval_status=batch.approval_status,
            approved_at=batch.approved_at,
            message=f"Batch {batch.batch_number} has been approved for sending",
        )
    except ValueError as exc:
        err = str(exc)
        if "not found" in err.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err) from exc


@router.post(
    "/{campaign_id}/batches/{batch_id}/reject",
    response_model=BatchRejectResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject an individual batch",
)
def reject_batch(
    campaign_id: int,
    batch_id: int,
    db: Session = Depends(get_db),
) -> BatchRejectResponse:
    """Perform human rejection for an individual batch before message sending."""
    try:
        batch = CampaignService.reject_batch(db=db, campaign_id=campaign_id, batch_id=batch_id)
        return BatchRejectResponse(
            batch_id=batch.id,
            campaign_id=batch.campaign_id,
            batch_number=batch.batch_number,
            approval_status=batch.approval_status,
            rejected_at=datetime.now(timezone.utc),
            message=f"Batch {batch.batch_number} has been rejected",
        )
    except ValueError as exc:
        err = str(exc)
        if "not found" in err.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err) from exc


@router.post(
    "/{campaign_id}/batches/{batch_id}/send",
    response_model=BatchSendResponse,
    status_code=status.HTTP_200_OK,
    summary="Explicitly initiate message dispatch for an approved batch",
)
def send_batch(
    campaign_id: int,
    batch_id: int,
    db: Session = Depends(get_db),
) -> BatchSendResponse:
    """Dispatch messages for an approved batch after revalidating consent immediately prior to send."""
    try:
        result = CampaignService.send_batch(db=db, campaign_id=campaign_id, batch_id=batch_id)
        return BatchSendResponse(**result)
    except ValueError as exc:
        err = str(exc)
        if "not found" in err.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=err) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err) from exc


@router.get(
    "/{campaign_id}/report",
    response_model=CampaignReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Get campaign performance report and delivery counts",
)
def get_campaign_report(
    campaign_id: int,
    db: Session = Depends(get_db),
) -> CampaignReportResponse:
    """Retrieve comprehensive campaign metrics including opt-in eligibility and delivery status."""
    try:
        report = CampaignService.get_campaign_report(db=db, campaign_id=campaign_id)
        return CampaignReportResponse(**report)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{campaign_id}/failed-recipients",
    response_model=List[FailedRecipientResponse],
    status_code=status.HTTP_200_OK,
    summary="List failed recipients in a campaign for manual review",
)
def get_failed_recipients(
    campaign_id: int,
    db: Session = Depends(get_db),
) -> List[FailedRecipientResponse]:
    """Retrieve all failed recipients in a campaign with failure error details."""
    try:
        results = CampaignService.get_failed_recipients(db=db, campaign_id=campaign_id)
        return [FailedRecipientResponse(**r) for r in results]
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
