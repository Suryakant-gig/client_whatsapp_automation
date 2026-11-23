"""Schemas for Campaign Management, Batch Approval, and Sending (Phase 8)."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class CampaignCreate(BaseModel):
    """Payload for creating a new marketing/follow-up broadcast campaign."""

    campaign_name: str = Field(..., min_length=1, max_length=255, description="Unique campaign name")
    template_name: str = Field(..., description="Name of the Meta-approved WhatsApp template")
    template_language: str = Field(default="en", max_length=10, description="Template language code (e.g. 'en')")
    lead_ids: Optional[List[int]] = Field(
        default=None,
        description="Optional explicit list of lead IDs. If omitted, all eligible opted-in leads are evaluated.",
    )
    batch_size: int = Field(
        default=50,
        ge=1,
        le=50,
        description="Configurable recipient batch size (1-50, default 50).",
    )
    auto_generate_batches: bool = Field(
        default=True,
        description="Automatically partition eligible leads into batches upon campaign creation.",
    )
    max_recipients: Optional[int] = Field(
        default=None,
        ge=1,
        description="Optional cap on total candidate recipients to partition.",
    )
    carry_forward_interval_hours: Optional[int] = Field(
        default=0,
        ge=0,
        description="Optional hours interval between batch carry-forward dispatch (0 = send all at once).",
    )
    scheduled_at: Optional[datetime] = Field(
        default=None,
        description="Optional scheduled dispatch datetime in UTC.",
    )
    carry_forward_interval_hours: Optional[int] = Field(
        default=0,
        ge=0,
        description="Optional hours interval between batch carry-forward dispatch (0 = send all at once).",
    )


class CampaignUpdate(BaseModel):
    """Payload for updating an existing campaign."""

    campaign_name: Optional[str] = Field(default=None, min_length=1, max_length=255, description="Updated campaign name")
    template_name: Optional[str] = Field(default=None, min_length=1, description="Updated WhatsApp template name")
    template_language: Optional[str] = Field(default=None, max_length=10, description="Updated template language code")
    scheduled_at: Optional[datetime] = Field(default=None, description="Updated scheduled dispatch datetime")


class CampaignResponse(BaseModel):
    """Campaign summary representation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_name: str
    template_name: Optional[str] = None
    template_language: str
    status: str
    total_leads_selected: int
    total_leads_eligible: int
    total_leads_excluded: int
    batch_count: int = 0
    scheduled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CampaignListResponse(BaseModel):
    """Paginated list of campaigns."""

    items: List[CampaignResponse]
    total: int
    page: int
    page_size: int
    pages: int


class BatchGenerateRequest(BaseModel):
    """Payload for generating batches for an existing campaign."""

    lead_ids: Optional[List[int]] = Field(
        default=None,
        description="Optional list of lead IDs to partition. If omitted, all eligible opted-in leads not already in this campaign are added.",
    )
    batch_size: int = Field(
        default=50,
        ge=1,
        le=50,
        description="Configurable batch size (1-50, default 50).",
    )
    max_recipients: Optional[int] = Field(
        default=None,
        ge=1,
        description="Optional cap on total candidate recipients to partition.",
    )
    carry_forward_interval_hours: Optional[int] = Field(
        default=0,
        ge=0,
        description="Optional hours interval between batch carry-forward dispatch (0 = send all at once).",
    )


class EligibleLeadItem(BaseModel):
    """Candidate lead eligible for broadcast campaign targeting."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_name: str
    phone_number: str
    opt_in_status: str
    status: str
    destination: Optional[str] = None
    created_at: Optional[datetime] = None


class BatchRecipientResponse(BaseModel):
    """Recipient representation within a campaign batch."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    lead_id: int
    customer_name: Optional[str] = None
    phone_number: Optional[str] = None
    send_status: str
    message_log_id: Optional[int] = None
    delivery_status: Optional[str] = None
    sent_at: Optional[datetime] = None
    error_details: Optional[str] = None


class BatchResponse(BaseModel):
    """Campaign batch details and status representation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    batch_number: int
    batch_size: int
    approval_status: str
    approved_at: Optional[datetime] = None
    send_status: str
    sent_at: Optional[datetime] = None
    scheduled_at: Optional[datetime] = None
    total_messages_count: int
    sent_messages_count: int
    failed_messages_count: int
    created_at: datetime
    recipients: Optional[List[BatchRecipientResponse]] = None


class BatchListResponse(BaseModel):
    """List of batches for a campaign."""

    items: List[BatchResponse]
    total: int


class BatchApprovalResponse(BaseModel):
    """Result of an individual batch approval action."""

    batch_id: int
    campaign_id: int
    batch_number: int
    approval_status: str
    approved_at: datetime
    message: str


class BatchRejectResponse(BaseModel):
    """Result of an individual batch rejection action."""

    batch_id: int
    campaign_id: int
    batch_number: int
    approval_status: str
    rejected_at: datetime
    message: str


class GlobalBatchResponse(BaseModel):
    """Batch representation with associated campaign metadata for cross-campaign views."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    campaign_name: str
    template_name: Optional[str] = None
    batch_number: int
    batch_size: int
    approval_status: str
    approved_at: Optional[datetime] = None
    send_status: str
    sent_at: Optional[datetime] = None
    scheduled_at: Optional[datetime] = None
    total_messages_count: int
    sent_messages_count: int
    failed_messages_count: int
    created_at: datetime


class GlobalBatchListResponse(BaseModel):
    """Paginated list of batches across campaigns."""

    items: List[GlobalBatchResponse]
    total: int
    page: int
    page_size: int
    pages: int


class EligibleLeadsSummaryResponse(BaseModel):
    """Summary counts of candidate recipients for campaign broadcast."""

    total_leads: int
    eligible_leads_count: int
    excluded_leads_count: int


class BatchSendResponse(BaseModel):
    """Result of an explicit batch sending operation."""

    batch_id: int
    campaign_id: int
    batch_number: int
    total_recipients: int
    sent_count: int
    failed_count: int
    skipped_count: int
    send_status: str


class FailedRecipientResponse(BaseModel):
    """Detailed information on a recipient message that failed to dispatch."""

    recipient_id: Optional[int] = None
    batch_id: Optional[int] = None
    batch_number: Optional[int] = None
    lead_id: Optional[int] = None
    customer_name: Optional[str] = None
    lead_name: Optional[str] = None
    phone_number: str
    send_status: str = "Failed"
    error_details: Optional[str] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    attempted_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None


class CampaignReportResponse(BaseModel):
    """Comprehensive campaign summary report covering consent, batches, and webhook delivery status."""

    campaign_id: int
    campaign_name: str
    name: Optional[str] = None
    template_name: Optional[str] = None
    template_language: str
    status: str
    total_selected_leads: int
    eligible_leads: int
    excluded_leads: int
    number_of_batches: int
    total_batches: Optional[int] = None
    total_partitioned_recipients: Optional[int] = None
    total_recipients: Optional[int] = None
    pending_approvals: int
    approved_batches: int
    batches_total: Optional[int] = None
    batches_pending: Optional[int] = None
    batches_approved: Optional[int] = None
    batches_sent: Optional[int] = None
    batches_rejected: Optional[int] = None
    accepted_messages: int
    sent_messages: int
    delivered_messages: int
    read_messages: int
    failed_messages: int
    sent_count: Optional[int] = None
    delivered_count: Optional[int] = None
    read_count: Optional[int] = None
    failed_count: Optional[int] = None
    delivery_rate: Optional[float] = None
    created_at: datetime
    exclusion_details: Optional[List[Dict[str, Any]]] = None
