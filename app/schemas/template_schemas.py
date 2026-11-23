"""Pydantic schemas for WhatsApp template management."""

import json
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TemplateCreate(BaseModel):
    """Schema for registering local template metadata."""

    template_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Meta-registered template name identifier (lowercase with underscores)",
    )
    language: str = Field(
        default="en",
        min_length=2,
        max_length=10,
        description="Language code (e.g. 'en', 'en_US', 'hi')",
    )
    category: str = Field(
        default="MARKETING",
        max_length=50,
        description="Template category: MARKETING, UTILITY, AUTHENTICATION",
    )
    approval_status: str = Field(
        default="PENDING",
        description="Approval status on Meta platform: APPROVED, PENDING, REJECTED",
    )
    body_text: Optional[str] = Field(
        default=None,
        description="Sample or body text of the template with {{1}}, {{2}} placeholders",
    )
    expected_parameters: Optional[List[str]] = Field(
        default=None,
        description="List of expected body parameter names in order",
    )
    header_type: Optional[str] = Field(
        default=None,
        description="Header type: TEXT, IMAGE, DOCUMENT, VIDEO, or None",
    )
    header_text: Optional[str] = Field(
        default=None,
        description="Static or sample header text",
    )
    header_image_path: Optional[str] = Field(
        default=None,
        description="Path to uploaded image for IMAGE header type",
    )

    @field_validator("approval_status")
    @classmethod
    def validate_approval_status(cls, v: str) -> str:
        status_upper = v.strip().upper()
        allowed = {"APPROVED", "PENDING", "REJECTED", "PAUSED", "DISABLED"}
        if status_upper not in allowed:
            raise ValueError(f"Invalid approval status '{v}'. Allowed: {', '.join(sorted(allowed))}")
        return status_upper


class TemplateUpdate(BaseModel):
    """Schema for updating local template metadata or approval status."""

    category: Optional[str] = Field(default=None, max_length=50)
    approval_status: Optional[str] = Field(default=None)
    body_text: Optional[str] = Field(default=None)
    expected_parameters: Optional[List[str]] = Field(default=None)
    header_type: Optional[str] = Field(default=None)
    header_text: Optional[str] = Field(default=None)
    header_image_path: Optional[str] = Field(default=None)

    @field_validator("approval_status")
    @classmethod
    def validate_approval_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        status_upper = v.strip().upper()
        allowed = {"APPROVED", "PENDING", "REJECTED", "PAUSED", "DISABLED"}
        if status_upper not in allowed:
            raise ValueError(f"Invalid approval status '{v}'. Allowed: {', '.join(sorted(allowed))}")
        return status_upper


class TemplateResponse(BaseModel):
    """Schema representing template details."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    template_name: str
    language: str
    category: str
    approval_status: str
    body_text: Optional[str] = None
    expected_parameters: Optional[List[str]] = None
    header_type: Optional[str] = None
    header_text: Optional[str] = None
    header_image_path: Optional[str] = None
    header_image_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def compute_header_image_url(self) -> "TemplateResponse":
        if self.header_image_path and not self.header_image_url:
            p = self.header_image_path.replace("\\", "/")
            if "data/uploads/" in p:
                self.header_image_url = "/" + p[p.index("data/uploads/") + len("data/"):]
            elif not p.startswith("/"):
                self.header_image_url = "/" + p
            else:
                self.header_image_url = p
        return self

    @field_validator("expected_parameters", mode="before")
    @classmethod
    def parse_expected_parameters(cls, v: Any) -> Optional[List[str]]:
        if v is None or isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                return [p.strip() for p in v.split(",") if p.strip()]
        return None


class TemplateListResponse(BaseModel):
    """Schema for paginated or filtered list of templates."""

    items: List[TemplateResponse]
    total: int
