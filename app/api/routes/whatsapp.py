"""API endpoints for Meta WhatsApp Cloud API messaging."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.integrations.whatsapp.exceptions import (
    TemplateNotApprovedError,
    TemplateValidationError,
    WhatsAppAPIError,
    WhatsAppAuthError,
    WhatsAppConfigError,
    WhatsAppConnectionError,
    WhatsAppConsentError,
    WhatsAppRateLimitError,
    WhatsAppServerError,
    WhatsAppTimeoutError,
)
from app.services.whatsapp_service import WhatsAppService

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])


class SendTemplateRequest(BaseModel):
    """Payload for dispatching an approved WhatsApp template message."""

    lead_id: int = Field(..., description="Target lead ID")
    template_name: str = Field(..., description="Meta template identifier")
    language: str = Field(default="en", description="Template language code (e.g. 'en')")
    parameters: Optional[Union[Dict[str, Any], List[Any]]] = Field(
        default=None,
        description="Body parameters as ordered list or dictionary",
    )
    header_parameters: Optional[List[str]] = Field(
        default=None,
        description="Optional list of header parameters",
    )
    message_type: str = Field(
        default="template",
        description="Communication category ('template', 'follow_up', 'campaign')",
    )


class SendTemplateResponse(BaseModel):
    """Response returned upon successful Meta API acceptance."""

    success: bool
    message_log_id: int
    whatsapp_message_id: str
    delivery_status: str
    api_status: str
    sent_at: datetime


@router.post(
    "/send-template",
    response_model=SendTemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Send an approved WhatsApp template message",
)
async def send_template_message(
    payload: SendTemplateRequest,
    db: Session = Depends(get_db),
) -> SendTemplateResponse:
    """Validate compliance, dispatch via Meta Cloud API, and log the accepted message."""
    try:
        msg_log = await WhatsAppService.send_template_message(
            db=db,
            lead_id=payload.lead_id,
            template_name=payload.template_name,
            language=payload.language,
            parameters=payload.parameters,
            header_parameters=payload.header_parameters,
            message_type=payload.message_type,
        )

        return SendTemplateResponse(
            success=True,
            message_log_id=msg_log.id,
            whatsapp_message_id=msg_log.whatsapp_message_id or "",
            delivery_status=msg_log.delivery_status,
            api_status=msg_log.api_status or "ACCEPTED",
            sent_at=msg_log.sent_at or datetime.utcnow(),
        )

    except WhatsAppConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except WhatsAppConsentError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except TemplateNotApprovedError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except TemplateValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except WhatsAppAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Meta WhatsApp API authentication failed",
        ) from exc
    except WhatsAppRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except WhatsAppTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Meta WhatsApp API request timed out",
        ) from exc
    except (WhatsAppServerError, WhatsAppConnectionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Error communicating with Meta WhatsApp Cloud API",
        ) from exc
    except WhatsAppAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        err_msg = str(exc)
        if "does not exist" in err_msg or "not found" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=err_msg,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        ) from exc
