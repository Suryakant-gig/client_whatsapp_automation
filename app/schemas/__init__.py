"""Schemas package exports."""

from app.schemas.auth_schemas import (
    AuthStatusResponse,
    LoginRequest,
    LogoutResponse,
    SetupRequest,
    UserResponse,
)
from app.schemas.dashboard_schemas import (
    ActivityItemResponse,
    DashboardOverviewResponse,
    DashboardStatsResponse,
)
from app.schemas.followup_schemas import (
    FollowUpCreate,
    FollowUpListResponse,
    FollowUpResponse,
    FollowUpUpdate,
)
from app.schemas.import_schemas import (
    EligibleRecord,
    ImportConfirmRequest,
    ImportConfirmResponse,
    ImportPreviewResponse,
    RowValidationError,
)
from app.schemas.lead_schemas import (
    LeadConsentUpdate,
    LeadCreate,
    LeadDetailResponse,
    LeadListResponse,
    LeadResponse,
    LeadUpdate,
)
from app.schemas.sync_schemas import ExcelSyncRequest, ExcelSyncResponse
from app.schemas.template_schemas import (
    TemplateCreate,
    TemplateListResponse,
    TemplateResponse,
    TemplateUpdate,
)

__all__ = [
    "EligibleRecord",
    "ImportConfirmRequest",
    "ImportConfirmResponse",
    "ImportPreviewResponse",
    "RowValidationError",
    "ExcelSyncRequest",
    "ExcelSyncResponse",
    "LeadConsentUpdate",
    "LeadCreate",
    "LeadUpdate",
    "LeadResponse",
    "LeadDetailResponse",
    "LeadListResponse",
    "FollowUpCreate",
    "FollowUpUpdate",
    "FollowUpResponse",
    "FollowUpListResponse",
    "TemplateCreate",
    "TemplateUpdate",
    "TemplateResponse",
    "TemplateListResponse",
]
