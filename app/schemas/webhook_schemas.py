"""Schemas for Meta WhatsApp Webhook verification and event handling."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class WebhookStatusResponse(BaseModel):
    """Standard response model for webhook events."""

    status: str = Field(default="ok", description="Status indicator")
    processed_messages: int = Field(default=0, description="Count of incoming messages processed")
    processed_statuses: int = Field(default=0, description="Count of delivery statuses processed")


class WebhookVerificationResponse(BaseModel):
    """Response returned upon webhook verification."""

    challenge: str
