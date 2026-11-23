"""Pydantic schemas for lead management operations."""

from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


ALLOWED_LEAD_STATUSES = ("Pending", "Replied", "Not Interested", "Interested")
ALLOWED_OPT_IN_STATUSES = ("OPTED_IN", "NOT_OPTED_IN", "OPTED_OUT")


class LeadBase(BaseModel):
    """Shared lead attributes."""

    customer_name: str = Field(..., min_length=1, description="Full name of the customer")
    phone_number: str = Field(..., min_length=7, description="Phone number preserving country code")
    serial_number: Optional[str] = Field(default=None, description="Optional lead reference or serial number")


class LeadConsentUpdate(BaseModel):
    """Payload for updating WhatsApp messaging consent / opt-in status."""

    opt_in_status: Literal["OPTED_IN", "NOT_OPTED_IN", "OPTED_OUT"] = Field(
        ...,
        description="Updated consent status: OPTED_IN, NOT_OPTED_IN, OPTED_OUT",
    )
    opt_in_source: Optional[str] = Field(
        default=None,
        description="Source documenting consent (e.g. 'web_form', 'verbal_inquiry', 'written_consent')",
    )


class MarkFollowedUpRequest(BaseModel):
    """Payload for marking an interested lead as followed up."""

    notes: Optional[str] = Field(default=None, description="Optional call notes entered by agent")


class LeadCreate(LeadBase):
    """Payload for manual lead creation."""

    status: Optional[Literal["Pending", "Replied", "Not Interested", "Interested"]] = Field(
        default="Pending",
        description="Initial lead status",
    )
    follow_up_paused: Optional[bool] = Field(
        default=False,
        description="Whether follow-ups are initially paused",
    )
    opt_in_status: Optional[Literal["OPTED_IN", "NOT_OPTED_IN", "OPTED_OUT"]] = Field(
        default="NOT_OPTED_IN",
        description="Initial consent status",
    )
    opt_in_source: Optional[str] = Field(
        default=None,
        description="Source documenting consent",
    )

    @field_validator("customer_name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Customer name cannot be empty or whitespace only")
        return stripped

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Phone number cannot be empty")
        return stripped


class LeadUpdate(BaseModel):
    """Payload for updating lead attributes."""

    customer_name: Optional[str] = Field(default=None, description="Updated customer name")
    phone_number: Optional[str] = Field(default=None, description="Updated phone number")
    serial_number: Optional[str] = Field(default=None, description="Updated serial number")
    status: Optional[str] = Field(default=None, description="Updated status (Pending, Replied, Not Interested)")
    follow_up_paused: Optional[bool] = Field(default=None, description="Explicit follow-up pause flag")
    opt_in_status: Optional[str] = Field(default=None, description="Consent status: OPTED_IN, NOT_OPTED_IN, OPTED_OUT")
    opt_in_source: Optional[str] = Field(default=None, description="Source documenting consent")

    @field_validator("customer_name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            stripped = v.strip()
            if not stripped:
                raise ValueError("Customer name cannot be empty")
            return stripped
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if v not in ALLOWED_LEAD_STATUSES:
                raise ValueError(
                    f"Invalid lead status '{v}'. Allowed statuses are: {', '.join(ALLOWED_LEAD_STATUSES)}"
                )
        return v


class LeadResponse(BaseModel):
    """Lead detail representation."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Unique lead ID")
    serial_number: Optional[str] = Field(default=None, description="Serial number")
    customer_name: str = Field(description="Customer name")
    phone_number: str = Field(description="Phone number")
    status: str = Field(description="Current lead status")
    follow_up_paused: bool = Field(description="Whether follow-ups are paused")
    opt_in_status: str = Field(default="NOT_OPTED_IN", description="Consent status")
    opt_in_source: Optional[str] = Field(default=None, description="Consent source")
    opt_in_timestamp: Optional[datetime] = Field(default=None, description="Timestamp consent was granted")
    opt_out_timestamp: Optional[datetime] = Field(default=None, description="Timestamp opt-out was recorded")
    last_reply_text: Optional[str] = Field(default=None, description="Latest WhatsApp reply message")
    last_replied_at: Optional[datetime] = Field(default=None, description="UTC timestamp of the latest inbound reply")
    needs_manual_followup: bool = Field(default=False, description="Whether lead requires a manual telephone follow-up")
    followed_up_at: Optional[datetime] = Field(default=None, description="UTC timestamp when agent marked lead as called/followed up")
    followup_notes: Optional[str] = Field(default=None, description="Call notes entered by agent")
    is_deleted: bool = Field(description="Soft deletion flag")
    created_at: datetime = Field(description="Record creation timestamp (UTC)")
    updated_at: datetime = Field(description="Last update timestamp (UTC)")


class LeadListResponse(BaseModel):
    """Paginated list of lead records."""

    items: List[LeadResponse] = Field(description="List of matching lead records")
    total: int = Field(description="Total count of matching leads")
    page: int = Field(description="Current page number (1-based)")
    page_size: int = Field(description="Number of items per page")
    total_pages: int = Field(description="Total number of available pages")


class FollowUpScheduleSummary(BaseModel):
    """Follow-up schedule entry summary."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Schedule ID")
    lead_id: int = Field(description="Lead ID")
    sequence_number: int = Field(description="Sequence number")
    scheduled_at: datetime = Field(description="Scheduled time (UTC)")
    status: str = Field(description="Schedule status")
    attempt_number: int = Field(description="Attempt number")
    skip_reason: Optional[str] = Field(default=None, description="Skip reason")
    processed_at: Optional[datetime] = Field(default=None, description="Processed timestamp")
    created_at: datetime = Field(description="Created timestamp")
    updated_at: datetime = Field(description="Updated timestamp")


class MessageLogSummary(BaseModel):
    """Outbound message audit log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Log ID")
    lead_id: Optional[int] = Field(default=None, description="Lead ID")
    campaign_id: Optional[int] = Field(default=None, description="Campaign ID")
    batch_id: Optional[int] = Field(default=None, description="Batch ID")
    message_type: str = Field(description="Message type")
    template_name: Optional[str] = Field(default=None, description="Template name")
    whatsapp_message_id: Optional[str] = Field(default=None, description="WhatsApp message ID (WAMID)")
    delivery_status: str = Field(description="Delivery status")
    api_status: Optional[str] = Field(default=None, description="Meta API status")
    error_details: Optional[str] = Field(default=None, description="Error details")
    sent_at: Optional[datetime] = Field(default=None, description="Sent timestamp")
    delivered_at: Optional[datetime] = Field(default=None, description="Delivered timestamp")
    read_at: Optional[datetime] = Field(default=None, description="Read timestamp")
    failed_at: Optional[datetime] = Field(default=None, description="Failed timestamp")
    created_at: datetime = Field(description="Created timestamp")


class IncomingMessageSummary(BaseModel):
    """Inbound customer webhook message entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Incoming message ID")
    lead_id: Optional[int] = Field(default=None, description="Associated lead ID")
    whatsapp_message_id: str = Field(description="WhatsApp message ID (WAMID)")
    sender_phone: str = Field(description="Sender phone number")
    message_text: Optional[str] = Field(default=None, description="Message text")
    message_type: str = Field(description="Message type")
    received_at: datetime = Field(description="Received timestamp")
    processing_status: str = Field(description="Processing status")
    created_at: datetime = Field(description="Created timestamp")


class LeadDetailResponse(LeadResponse):
    """Detailed lead model including schedules and message interaction history."""

    follow_up_schedules: List[FollowUpScheduleSummary] = Field(
        default_factory=list,
        description="List of individual follow-up schedules",
    )
    message_logs: List[MessageLogSummary] = Field(
        default_factory=list,
        description="Outbound message logs",
    )
    incoming_messages: List[IncomingMessageSummary] = Field(
        default_factory=list,
        description="Inbound received messages",
    )
