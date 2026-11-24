"""Pydantic schemas for Respondent management and manual WhatsApp contact."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class RespondentResponse(BaseModel):
    """Schema representing a single WhatsApp respondent."""

    id: int
    lead_id: Optional[int] = None
    phone_number: str
    name: Optional[str] = None
    classification: str
    first_reply_at: datetime
    last_reply_at: datetime
    original_campaign_id: Optional[int] = None
    original_campaign_name: Optional[str] = None
    internal_notes: Optional[str] = None
    opt_in_status: Optional[str] = None
    is_opted_out: bool = False
    within_24h_window: bool = False
    hours_since_last_reply: float = 0.0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RespondentListResponse(BaseModel):
    """Paginated list of respondents with summary counts."""

    items: List[RespondentResponse]
    total: int
    page: int
    page_size: int
    pages: int
    counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Counts per classification (TOTAL, INTERESTED, UNCLASSIFIED, NOT_INTERESTED, OTHER)",
    )


class RespondentClassificationUpdate(BaseModel):
    """Payload for updating respondent classification."""

    classification: str = Field(
        ...,
        description="New classification: UNCLASSIFIED, INTERESTED, NOT_INTERESTED, OTHER",
    )


class RespondentNotesUpdate(BaseModel):
    """Payload for updating internal notes on a respondent."""

    internal_notes: Optional[str] = Field(
        default=None,
        description="Internal travel agent notes",
    )


class ManualContactRequest(BaseModel):
    """Payload for initiating a manual WhatsApp message to a respondent."""

    message_text: Optional[str] = Field(
        default=None,
        description="Custom message text (allowed within 24h customer service window)",
    )
    template_name: Optional[str] = Field(
        default=None,
        description="Approved Meta template name (required outside 24h window or optional within)",
    )
    template_language: str = Field(
        default="en",
        description="Template language code",
    )
    parameters: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional placeholder key-value parameters for template",
    )


class ManualContactResponse(BaseModel):
    """Response returned upon dispatching manual contact message."""

    success: bool
    respondent_id: int
    phone_number: str
    delivery_status: str
    message_type: str
    whatsapp_message_id: Optional[str] = None
    detail: str
    dispatched_at: datetime


class RespondentHistoryItem(BaseModel):
    """Single message event in the respondent conversation timeline."""

    id: str
    direction: str  # "inbound" or "outbound"
    message_text: Optional[str] = None
    template_name: Optional[str] = None
    delivery_status: str
    timestamp: datetime
    whatsapp_message_id: Optional[str] = None


class RespondentDetailResponse(BaseModel):
    """Full detail view for a respondent including conversation history."""

    respondent: RespondentResponse
    conversation_history: List[RespondentHistoryItem] = Field(default_factory=list)
