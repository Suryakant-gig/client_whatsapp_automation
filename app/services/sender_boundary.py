"""Sender boundary interface for outbound follow-up message dispatch."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, Union

from app.db.models import FollowUpSchedule, Lead

logger = logging.getLogger("app.services.sender_boundary")


@dataclass
class SendResult:
    """Outcome representation of a message dispatch attempt."""

    success: bool
    whatsapp_message_id: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: datetime = datetime.now(timezone.utc)


class MessageSenderBoundary(Protocol):
    """Protocol defining the interface for WhatsApp follow-up sending (Phase 6 boundary)."""

    def send_follow_up_message(self, lead: Lead, schedule: FollowUpSchedule) -> SendResult:
        """Dispatch a follow-up message to the customer."""
        ...


class DefaultMessageSender:
    """Phase 5 reference implementation of the sender boundary."""

    def send_follow_up_message(self, lead: Lead, schedule: FollowUpSchedule) -> SendResult:
        """Reference implementation returning ready-state response without real network traffic."""
        # Simulated send boundary for Phase 5 integration testing
        return SendResult(
            success=True,
            whatsapp_message_id=f"wamid.SIMULATED.{schedule.id}.{int(datetime.now(timezone.utc).timestamp())}",
            timestamp=datetime.now(timezone.utc),
        )


class WhatsAppMessageSender:
    """Phase 6 production implementation of MessageSenderBoundary using Meta WhatsApp Cloud API."""

    def __init__(
        self,
        client: Optional[Any] = None,
        template_name: str = "follow_up_general",
        language: str = "en",
    ):
        self._client = client
        self.template_name = template_name
        self.language = language

    def send_follow_up_message(self, lead: Lead, schedule: FollowUpSchedule) -> SendResult:
        """Dispatch an approved WhatsApp template message via Meta Cloud API."""
        from sqlalchemy.orm import object_session
        from app.db.session import SessionLocal
        from app.services.whatsapp_service import WhatsAppService

        params = {"customer_name": lead.customer_name}

        session = object_session(lead)
        managed_session = False
        if session is None:
            db = SessionLocal()
            managed_session = True
        else:
            db = session

        try:
            msg_log = WhatsAppService.send_template_message_sync(
                db=db,
                lead_id=lead.id,
                template_name=self.template_name,
                language=self.language,
                parameters=params,
                message_type="follow_up",
                client=self._client,
            )
            return SendResult(
                success=True,
                whatsapp_message_id=msg_log.whatsapp_message_id,
                timestamp=msg_log.sent_at or datetime.now(timezone.utc),
            )
        except Exception as exc:
            logger.warning(
                "WhatsApp dispatch failed for schedule %d (lead %d): %s",
                schedule.id,
                lead.id,
                str(exc),
            )
            return SendResult(
                success=False,
                error_message=str(exc),
                timestamp=datetime.now(timezone.utc),
            )
        finally:
            if managed_session:
                db.close()
