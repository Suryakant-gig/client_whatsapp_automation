"""Service handling WhatsApp respondent management, classification, and manual messaging."""

from datetime import datetime, timezone
import logging
import math
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.campaign import Campaign
from app.db.models.lead import Lead
from app.db.models.message import IncomingMessage, MessageLog
from app.db.models.respondent import ALLOWED_CLASSIFICATIONS, Respondent
from app.integrations.whatsapp.client import get_whatsapp_client
from app.schemas.respondent_schemas import (
    ManualContactRequest,
    ManualContactResponse,
    RespondentHistoryItem,
    RespondentListResponse,
    RespondentResponse,
)
from app.services.excel_service import ExcelService
from app.services.template_service import TemplateService

logger = logging.getLogger("app.services.respondent")


class RespondentService:
    """Core domain service for respondent lifecycle, classification, and manual contact."""

    @staticmethod
    def _to_response_item(r: Respondent) -> RespondentResponse:
        """Convert Respondent ORM entity to RespondentResponse schema with calculated 24h window."""
        now = datetime.now(timezone.utc)
        last_dt = r.last_reply_at
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        hours_elapsed = (now - last_dt).total_seconds() / 3600.0
        within_24h = hours_elapsed <= 24.0

        is_opted_out = False
        opt_in_status = None
        if r.lead:
            opt_in_status = r.lead.opt_in_status
            is_opted_out = (r.lead.opt_in_status == "OPTED_OUT")

        camp_name = r.original_campaign.campaign_name if r.original_campaign else None

        return RespondentResponse(
            id=r.id,
            lead_id=r.lead_id,
            phone_number=r.phone_number,
            name=r.name or (r.lead.customer_name if r.lead else None),
            classification=r.classification,
            first_reply_at=r.first_reply_at,
            last_reply_at=r.last_reply_at,
            original_campaign_id=r.original_campaign_id,
            original_campaign_name=camp_name,
            internal_notes=r.internal_notes,
            opt_in_status=opt_in_status,
            is_opted_out=is_opted_out,
            within_24h_window=within_24h,
            hours_since_last_reply=round(hours_elapsed, 1),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )

    @classmethod
    def get_respondent_stats(cls, db: Session) -> Dict[str, int]:
        """Calculate counts of respondents grouped by classification in a single SQL query."""
        stmt = select(
            func.count(Respondent.id).label("total"),
            func.count(Respondent.id).filter(Respondent.classification == "UNCLASSIFIED").label("unclassified"),
            func.count(Respondent.id).filter(Respondent.classification == "INTERESTED").label("interested"),
            func.count(Respondent.id).filter(Respondent.classification == "NOT_INTERESTED").label("not_interested"),
            func.count(Respondent.id).filter(Respondent.classification == "OTHER").label("other"),
        )
        row = db.execute(stmt).first()
        if not row:
            return {"TOTAL": 0, "UNCLASSIFIED": 0, "INTERESTED": 0, "NOT_INTERESTED": 0, "OTHER": 0}
        return {
            "TOTAL": row.total or 0,
            "UNCLASSIFIED": row.unclassified or 0,
            "INTERESTED": row.interested or 0,
            "NOT_INTERESTED": row.not_interested or 0,
            "OTHER": row.other or 0,
        }

    @classmethod
    def list_respondents(
        cls,
        db: Session,
        classification: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> RespondentListResponse:
        """Retrieve paginated list of respondents with classification and search filtering."""
        query = select(Respondent)

        if classification:
            norm_class = classification.strip().upper()
            if norm_class in ALLOWED_CLASSIFICATIONS:
                query = query.where(Respondent.classification == norm_class)

        if search:
            s = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Respondent.name.ilike(s),
                    Respondent.phone_number.ilike(s),
                    Respondent.internal_notes.ilike(s),
                )
            )

        # Count filtered total
        count_stmt = select(func.count()).select_from(query.subquery())
        total = db.scalar(count_stmt) or 0

        # Order and paginate
        query = query.order_by(Respondent.last_reply_at.desc())
        offset = (page - 1) * page_size
        items = db.scalars(query.offset(offset).limit(page_size)).all()

        pages = math.ceil(total / page_size) if total > 0 else 1
        counts = cls.get_respondent_stats(db)

        return RespondentListResponse(
            items=[cls._to_response_item(r) for r in items],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
            counts=counts,
        )

    @classmethod
    def get_respondent(cls, db: Session, respondent_id: int) -> Respondent:
        """Fetch respondent by primary key ID or raise ValueError."""
        r = db.get(Respondent, respondent_id)
        if not r:
            raise ValueError(f"Respondent with ID {respondent_id} does not exist")
        return r

    @classmethod
    def update_classification(
        cls,
        db: Session,
        respondent_id: int,
        new_classification: str,
    ) -> RespondentResponse:
        """Update respondent classification manually.
        
        Allowed: UNCLASSIFIED, INTERESTED, NOT_INTERESTED, OTHER.
        """
        r = cls.get_respondent(db, respondent_id)
        norm_class = new_classification.strip().upper()
        if norm_class not in ALLOWED_CLASSIFICATIONS:
            raise ValueError(
                f"Invalid classification '{new_classification}'. Allowed: {', '.join(sorted(ALLOWED_CLASSIFICATIONS))}"
            )

        r.classification = norm_class
        r.updated_at = datetime.now(timezone.utc)

        # Sync lead business status if associated
        if r.lead:
            if norm_class == "INTERESTED":
                r.lead.status = "Interested"
                r.lead.needs_manual_followup = True
            elif norm_class == "NOT_INTERESTED":
                r.lead.status = "Not Interested"
                r.lead.needs_manual_followup = False

        db.commit()
        db.refresh(r)
        logger.info("Respondent %d classification updated to %s", r.id, norm_class)
        return cls._to_response_item(r)

    @classmethod
    def update_notes(
        cls,
        db: Session,
        respondent_id: int,
        internal_notes: Optional[str],
    ) -> RespondentResponse:
        """Update internal agent notes for a respondent."""
        r = cls.get_respondent(db, respondent_id)
        r.internal_notes = internal_notes.strip() if internal_notes else None
        r.updated_at = datetime.now(timezone.utc)

        # Sync to lead followup notes if linked
        if r.lead and internal_notes:
            r.lead.followup_notes = internal_notes.strip()

        db.commit()
        db.refresh(r)
        logger.info("Respondent %d notes updated", r.id)
        return cls._to_response_item(r)

    @classmethod
    def get_conversation_history(
        cls,
        db: Session,
        respondent_id: int,
    ) -> List[RespondentHistoryItem]:
        """Fetch combined chronological message timeline (inbound customer replies and outbound messages)."""
        r = cls.get_respondent(db, respondent_id)

        history: List[RespondentHistoryItem] = []

        # 1. Inbound messages
        inbound_stmt = select(IncomingMessage)
        if r.lead_id:
            inbound_stmt = inbound_stmt.where(
                or_(
                    IncomingMessage.lead_id == r.lead_id,
                    IncomingMessage.sender_phone == r.phone_number,
                )
            )
        else:
            inbound_stmt = inbound_stmt.where(IncomingMessage.sender_phone == r.phone_number)

        for inc in db.scalars(inbound_stmt).all():
            history.append(
                RespondentHistoryItem(
                    id=f"inc_{inc.id}",
                    direction="inbound",
                    message_text=inc.message_text,
                    template_name=None,
                    delivery_status="Received",
                    timestamp=inc.received_at,
                    whatsapp_message_id=inc.whatsapp_message_id,
                )
            )

        # 2. Outbound message logs
        outbound_stmt = select(MessageLog)
        if r.lead_id:
            outbound_stmt = outbound_stmt.where(MessageLog.lead_id == r.lead_id)
            for log in db.scalars(outbound_stmt).all():
                history.append(
                    RespondentHistoryItem(
                        id=f"out_{log.id}",
                        direction="outbound",
                        message_text=log.error_details if not log.template_name else f"Template: {log.template_name}",
                        template_name=log.template_name,
                        delivery_status=log.delivery_status,
                        timestamp=log.sent_at or log.created_at,
                        whatsapp_message_id=log.whatsapp_message_id,
                    )
                )

        # Sort combined history chronologically ascending
        history.sort(key=lambda x: x.timestamp)
        return history

    @classmethod
    def manual_contact(
        cls,
        db: Session,
        respondent_id: int,
        payload: ManualContactRequest,
    ) -> ManualContactResponse:
        """Manually contact an interested respondent via WhatsApp immediately.
        
        Enforces:
        - Never creates future follow-ups.
        - Strict opt-out check: Cannot contact if lead has opted out.
        - Meta 24-hr customer service window:
          * If last customer reply <= 24 hours: Freeform custom text or approved template.
          * If last customer reply > 24 hours: Approved template mandatory.
        - Dispatches immediately (mocked if WHATSAPP_ENABLED=False).
        - Records outbound MessageLog.
        """
        r = cls.get_respondent(db, respondent_id)
        settings = get_settings()

        # 1. Opt-out check
        if r.lead and (r.lead.opt_in_status == "OPTED_OUT" or r.lead.status == "Not Interested" and r.classification == "NOT_INTERESTED"):
            raise ValueError("Cannot send WhatsApp message: Recipient has opted out of WhatsApp communications")

        # 2. 24-hour customer service window evaluation
        now = datetime.now(timezone.utc)
        last_dt = r.last_reply_at
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        hours_since_reply = (now - last_dt).total_seconds() / 3600.0
        within_24h = hours_since_reply <= 24.0

        template_name = payload.template_name.strip() if payload.template_name else None
        custom_text = payload.message_text.strip() if payload.message_text else None

        if not within_24h and not template_name:
            raise ValueError(
                f"Customer service window expired ({hours_since_reply:.1f} hours since customer's last reply). "
                f"Meta requires using an approved WhatsApp template to contact customers outside the 24-hour window."
            )

        if not template_name and not custom_text:
            raise ValueError("Either message_text or template_name must be provided")

        # 3. Message dispatch
        clean_phone, phone_err = ExcelService.normalize_phone_number(r.phone_number)
        if phone_err or not clean_phone:
            clean_phone = r.phone_number

        wa_message_id = None
        message_type = "manual_freeform" if custom_text and not template_name else "manual_template"

        if not settings.WHATSAPP_ENABLED:
            # Mock mode: Simulate dispatch safely without real network calls
            wa_message_id = f"wamid.mock.manual.{uuid4().hex[:16]}"
            logger.info("Mock mode: Simulated manual WhatsApp message to %s [wa_id=%s]", clean_phone, wa_message_id)
        else:
            # Live Meta API dispatch
            import asyncio
            wa_client = get_whatsapp_client()
            if template_name:
                # Approved template
                template = TemplateService.get_template_by_name(db, template_name, payload.template_language)
                if not template:
                    raise ValueError(f"Template '{template_name}' not found in database")
                components = TemplateService.build_components(template, payload.parameters)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                res = loop.run_until_complete(
                    wa_client.send_template_message(
                        to=clean_phone,
                        template_name=template_name,
                        language_code=payload.template_language,
                        components=components,
                    )
                )
                wa_message_id = res.get("whatsapp_message_id")
            else:
                # Freeform session text
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                res = loop.run_until_complete(
                    wa_client.send_text_message(
                        to=clean_phone,
                        text=custom_text,
                    )
                )
                wa_message_id = res.get("whatsapp_message_id")

        # 4. Record audit log in MessageLog
        msg_log = MessageLog(
            lead_id=r.lead_id,
            message_type=message_type,
            template_name=template_name,
            whatsapp_message_id=wa_message_id,
            api_status="ACCEPTED",
            delivery_status="Accepted",
            error_details=f"Manual message: {custom_text[:200]}" if custom_text else f"Manual template: {template_name}",
            sent_at=now,
            created_at=now,
        )
        db.add(msg_log)

        # Update respondent notes or followed_up_at if lead is attached
        if r.lead:
            r.lead.followed_up_at = now
            r.lead.needs_manual_followup = False

        r.updated_at = now
        db.commit()

        logger.info(
            "Manual contact sent to respondent %d (%s) [type=%s, wa_id=%s]",
            r.id,
            clean_phone,
            message_type,
            wa_message_id,
        )

        return ManualContactResponse(
            success=True,
            respondent_id=r.id,
            phone_number=r.phone_number,
            delivery_status="Accepted",
            message_type=message_type,
            whatsapp_message_id=wa_message_id,
            detail=f"Message dispatched immediately ({'Simulated Mock' if not settings.WHATSAPP_ENABLED else 'Meta Cloud API'}).",
            dispatched_at=now,
        )
