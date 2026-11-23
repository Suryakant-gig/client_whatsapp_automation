"""Service orchestrating WhatsApp message validation, compliance, sending, and logging."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.lead import Lead
from app.db.models.message import MessageLog
from app.db.models.template import Template
from app.integrations.whatsapp.client import WhatsAppCloudClient, get_whatsapp_client
from app.integrations.whatsapp.exceptions import (
    TemplateNotApprovedError,
    TemplateValidationError,
    WhatsAppAPIError,
    WhatsAppConsentError,
    WhatsAppError,
)
from app.services.excel_service import ExcelService
from app.services.template_service import TemplateService

logger = logging.getLogger("app.services.whatsapp")


class WhatsAppService:
    """Core domain service for Meta WhatsApp Cloud API messaging and audit logging."""

    @staticmethod
    def validate_lead_eligibility(lead: Lead) -> None:
        """Validate all business, status, and compliance criteria before sending a WhatsApp message.

        Raises:
            ValueError: If lead is deleted or missing.
            WhatsAppConsentError: If lead is not opted-in or has opted out.
            WhatsAppAPIError: If lead is Not Interested or paused.
        """
        if lead.is_deleted:
            raise ValueError(f"Cannot message deleted lead (ID {lead.id})")

        if lead.status == "Not Interested":
            raise WhatsAppAPIError("Cannot send message: Customer has expressed 'Not Interested'")

        if lead.follow_up_paused:
            raise WhatsAppAPIError("Cannot send message: Follow-ups are paused for this customer")

        # Consent and Opt-in compliance check
        if lead.opt_in_status == "OPTED_OUT":
            raise WhatsAppConsentError("Cannot send message: Recipient has opted out of WhatsApp communication")

        if lead.opt_in_status != "OPTED_IN":
            raise WhatsAppConsentError(
                f"Cannot send message: Recipient has not provided documented opt-in consent (status: {lead.opt_in_status})"
            )

    @classmethod
    async def send_template_message(
        cls,
        db: Session,
        lead_id: int,
        template_name: str,
        language: str = "en",
        parameters: Optional[Union[Dict[str, Any], List[Any]]] = None,
        header_parameters: Optional[List[str]] = None,
        message_type: str = "template",
        client: Optional[WhatsAppCloudClient] = None,
        campaign_id: Optional[int] = None,
        batch_id: Optional[int] = None,
    ) -> MessageLog:
        """Validate, dispatch, and log a Meta-approved template message for a customer.

        Args:
            db: Active SQLAlchemy database session.
            lead_id: Target Lead primary key ID.
            template_name: Meta template name.
            language: Template language code (default 'en').
            parameters: Body parameters (ordered list or dict of named variables).
            header_parameters: Optional header parameters.
            message_type: Communication type category ('template', 'follow_up', 'campaign').
            client: Optional WhatsAppCloudClient instance for dependency injection.

        Returns:
            Created MessageLog audit record.
        """
        # 1. Validate Lead existence
        lead = db.get(Lead, lead_id)
        if not lead:
            raise ValueError(f"Lead with ID {lead_id} does not exist")

        # 2. Validate Lead eligibility & consent compliance
        cls.validate_lead_eligibility(lead)

        # 3. Validate & normalize recipient phone number
        clean_phone, phone_err = ExcelService.normalize_phone_number(lead.phone_number)
        if phone_err or not clean_phone:
            raise ValueError(f"Lead has invalid phone number: {phone_err or 'Invalid format'}")

        # 4. Validate template existence & approval status
        template = TemplateService.get_template_by_name(db, template_name, language)
        if not template:
            raise ValueError(
                f"Template '{template_name}' with language '{language}' is not registered in local database"
            )

        # 5. Build and validate template parameters & components
        components = TemplateService.build_components(
            template=template,
            parameters=parameters,
            header_parameters=header_parameters,
        )

        # 6. Dispatch message via WhatsApp HTTP client
        wa_client = client or get_whatsapp_client()
        result = await wa_client.send_template_message(
            to=clean_phone,
            template_name=template_name,
            language_code=language,
            components=components,
        )

        wa_message_id = result.get("whatsapp_message_id")
        now_utc = datetime.now(timezone.utc)

        # 7. Duplicate prevention: Check if message ID already recorded
        existing_log = db.scalar(
            select(MessageLog).where(MessageLog.whatsapp_message_id == wa_message_id)
        )
        if existing_log:
            logger.warning("MessageLog already exists for wa_message_id=%s; returning existing record", wa_message_id)
            return existing_log

        # 8. Record audit log
        # IMPORTANT: Delivery status is 'Accepted' (API acceptance only, NOT Delivered)
        msg_log = MessageLog(
            lead_id=lead.id,
            campaign_id=campaign_id,
            batch_id=batch_id,
            message_type=message_type,
            template_name=template_name,
            whatsapp_message_id=wa_message_id,
            api_status="ACCEPTED",
            delivery_status="Accepted",
            sent_at=now_utc,
            created_at=now_utc,
        )
        db.add(msg_log)
        db.commit()
        db.refresh(msg_log)

        logger.info(
            "Logged outbound WhatsApp message [log_id=%d, lead_id=%d, wa_id=%s, status=Accepted]",
            msg_log.id,
            lead.id,
            wa_message_id,
        )
        return msg_log

    @classmethod
    def send_template_message_sync(
        cls,
        db: Session,
        lead_id: int,
        template_name: str,
        language: str = "en",
        parameters: Optional[Union[Dict[str, Any], List[Any]]] = None,
        header_parameters: Optional[List[str]] = None,
        message_type: str = "template",
        client: Optional[WhatsAppCloudClient] = None,
        campaign_id: Optional[int] = None,
        batch_id: Optional[int] = None,
    ) -> MessageLog:
        """Synchronous wrapper for executing template send in thread worker contexts."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            # In a running loop (e.g. main thread async context)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    cls.send_template_message(
                        db=db,
                        lead_id=lead_id,
                        template_name=template_name,
                        language=language,
                        parameters=parameters,
                        header_parameters=header_parameters,
                        message_type=message_type,
                        client=client,
                        campaign_id=campaign_id,
                        batch_id=batch_id,
                    ),
                )
                return future.result()
        else:
            return loop.run_until_complete(
                cls.send_template_message(
                    db=db,
                    lead_id=lead_id,
                    template_name=template_name,
                    language=language,
                    parameters=parameters,
                    header_parameters=header_parameters,
                    message_type=message_type,
                    client=client,
                    campaign_id=campaign_id,
                    batch_id=batch_id,
                )
            )
