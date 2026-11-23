"""Pydantic schemas for Follow-up Schedule management."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class FollowUpBase(BaseModel):
    """Shared attributes for a follow-up schedule."""

    scheduled_at: datetime = Field(description="Scheduled execution timestamp (UTC)")


class FollowUpCreate(FollowUpBase):
    """Payload to schedule a new customer follow-up."""

    lead_id: int = Field(description="Lead ID to schedule follow-up for")
    attempt_number: Optional[int] = Field(default=1, ge=1, description="Target attempt number")


class FollowUpUpdate(BaseModel):
    """Payload to modify an un-processed scheduled follow-up."""

    scheduled_at: datetime = Field(description="Updated execution timestamp (UTC)")


class FollowUpResponse(BaseModel):
    """Full follow-up schedule response model."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Unique follow-up schedule ID")
    lead_id: int = Field(description="Lead foreign key ID")
    sequence_number: int = Field(description="Follow-up sequence order for the lead")
    scheduled_at: datetime = Field(description="Scheduled time (UTC)")
    status: str = Field(description="Schedule status (Scheduled, Approved, Sent, Skipped, Failed, Cancelled)")
    attempt_number: int = Field(description="Attempt number")
    skip_reason: Optional[str] = Field(default=None, description="Reason if marked Skipped")
    processed_at: Optional[datetime] = Field(default=None, description="Time when schedule was executed/processed")
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: datetime = Field(description="Last update timestamp")


class FollowUpListResponse(BaseModel):
    """Paginated list of follow-up schedules."""

    items: List[FollowUpResponse] = Field(description="Matching follow-up schedules")
    total: int = Field(description="Total matching count")
    page: int = Field(description="Current page number")
    page_size: int = Field(description="Page size")
    total_pages: int = Field(description="Total pages")
