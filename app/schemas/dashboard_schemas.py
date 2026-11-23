"""Pydantic schemas for CRM Dashboard statistics and activity feed."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.lead_schemas import LeadResponse


class DashboardStatsResponse(BaseModel):
    """Aggregated CRM metrics calculated directly from database records."""

    # Lead metrics
    total_leads: int = Field(default=0, description="Total active (non-deleted) leads")
    pending_leads: int = Field(default=0, description="Leads with Pending follow-up status")
    replied_leads: int = Field(default=0, description="Leads who replied to outreach")
    interested_leads: int = Field(default=0, description="Leads marked Interested")
    interested_pending_call_count: int = Field(default=0, description="Leads marked Interested who still need a call")
    confirmed_leads: int = Field(default=0, description="Confirmed leads / booked inquiries")
    not_interested_leads: int = Field(default=0, description="Leads marked Not Interested")
    opted_in_leads: int = Field(default=0, description="Leads with OPTED_IN consent")
    opted_out_leads: int = Field(default=0, description="Leads with OPTED_OUT status")

    # Campaign metrics
    total_campaigns: int = Field(default=0, description="Total broadcast campaigns created")
    active_campaigns: int = Field(default=0, description="Campaigns in Scheduled or In Progress state")

    # WhatsApp Message metrics
    total_messages_sent: int = Field(default=0, description="Total outbound messages dispatched")
    delivered_messages: int = Field(default=0, description="Messages confirmed Delivered by webhook")
    read_messages: int = Field(default=0, description="Messages confirmed Read by recipient")
    failed_messages: int = Field(default=0, description="Messages that failed delivery")

    # Follow-up automation
    scheduled_follow_ups: int = Field(default=0, description="Active pending follow-up schedules")
    last_sync_timestamp: Optional[datetime] = Field(default=None, description="Timestamp of most recent workbook sync")

    model_config = ConfigDict(from_attributes=True)


class ActivityItemResponse(BaseModel):
    """Normalized activity event for the recent activity timeline."""

    id: str
    category: str  # "message", "incoming", "sync", "lead", "campaign"
    title: str
    description: str
    timestamp: datetime
    status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DashboardOverviewResponse(BaseModel):
    """Combined dashboard response including metrics, activity, and server status."""

    stats: DashboardStatsResponse
    recent_activity: List[ActivityItemResponse]
    interested_pending_call_count: int = Field(default=0, description="Count of leads marked Interested who still need a call")
    latest_interested_leads: List[LeadResponse] = Field(default_factory=list, description="Latest 5 interested leads needing call")
    server_time: datetime
    scheduler_enabled: bool
    whatsapp_enabled: bool
