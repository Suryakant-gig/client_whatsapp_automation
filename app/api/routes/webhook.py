"""API endpoints for Meta WhatsApp Webhook verification and event handling."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.webhook_schemas import WebhookStatusResponse
from app.services.webhook_service import WebhookService

logger = logging.getLogger("app.api.webhook")

router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp Webhook"])


@router.get(
    "/webhook",
    summary="Meta WhatsApp Webhook Verification Challenge",
    response_class=PlainTextResponse,
    status_code=status.HTTP_200_OK,
)
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
) -> Response:
    """Handle Meta's GET verification challenge for webhook subscription.
    
    Meta sends:
        hub.mode = "subscribe"
        hub.verify_token = <WHATSAPP_WEBHOOK_VERIFY_TOKEN>
        hub.challenge = <random challenge string>
        
    If valid, returns the hub.challenge string verbatim with HTTP 200.
    Otherwise, returns HTTP 403 Forbidden.
    """
    challenge = WebhookService.verify_hub_challenge(
        mode=hub_mode,
        token=hub_verify_token,
        challenge=hub_challenge,
    )

    if challenge is not None:
        return PlainTextResponse(content=challenge, status_code=status.HTTP_200_OK)

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Webhook verification failed: invalid token or mode",
    )


@router.post(
    "/webhook",
    response_model=WebhookStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Meta WhatsApp Cloud API Webhook Event Receiver",
)
async def receive_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    db: Session = Depends(get_db),
) -> WebhookStatusResponse:
    """Receive and process real-time events from Meta WhatsApp Cloud API.
    
    Validates X-Hub-Signature-256 HMAC-SHA256 signature using META_APP_SECRET.
    Processes:
    - Delivery status updates (sent, delivered, read, failed).
    - Incoming customer messages (text, image, audio, interactive, etc.).
    """
    raw_body = await request.body()

    # 1. Cryptographic signature verification
    if not WebhookService.verify_hub_signature(raw_body, x_hub_signature_256):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Hub-Signature-256 signature",
        )

    # 2. Parse JSON payload
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        logger.warning("Received invalid JSON in webhook payload")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON payload",
        ) from exc

    # 3. Process events inside database transaction
    try:
        result = WebhookService.process_webhook_payload(db=db, payload=payload)
        return WebhookStatusResponse(
            status=result["status"],
            processed_messages=result["processed_messages"],
            processed_statuses=result["processed_statuses"],
        )
    except Exception as exc:
        db.rollback()
        logger.exception("Error processing webhook events")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing webhook events",
        ) from exc
