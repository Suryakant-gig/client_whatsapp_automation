"""Lead management business logic service."""

import logging
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import FollowUpSchedule, IncomingMessage, Lead, MessageLog
from app.schemas.lead_schemas import (
    FollowUpScheduleSummary,
    IncomingMessageSummary,
    LeadCreate,
    LeadDetailResponse,
    LeadListResponse,
    LeadResponse,
    LeadUpdate,
    MessageLogSummary,
)
from app.services.excel_service import ExcelService

logger = logging.getLogger("app.services.lead")


class LeadNotFoundError(Exception):
    """Raised when the specified lead is not found."""
    pass


class LeadDuplicateError(Exception):
    """Raised when an operation would produce a duplicate lead phone number."""
    pass


class LeadValidationError(Exception):
    """Raised when lead input fails business rule validation."""
    pass


class LeadService:
    """Service encapsulating all Lead domain operations."""

    @staticmethod
    def list_leads(
        db: Session,
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
        status: Optional[str] = None,
        opt_in_status: Optional[str] = None,
        follow_up_paused: Optional[bool] = None,
        needs_manual_followup: Optional[bool] = None,
        include_deleted: bool = False,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> LeadListResponse:
        """Query paginated leads with filtering, search, and sorting."""
        page = max(1, page)
        page_size = max(1, min(page_size, 100))

        # Base query
        stmt = select(Lead)
        count_stmt = select(func.count(Lead.id))

        if not include_deleted:
            stmt = stmt.where(Lead.is_deleted.is_(False))
            count_stmt = count_stmt.where(Lead.is_deleted.is_(False))

        # Filter by status
        if status:
            stmt = stmt.where(Lead.status == status)
            count_stmt = count_stmt.where(Lead.status == status)

        # Filter by consent / opt-in status
        if opt_in_status:
            stmt = stmt.where(Lead.opt_in_status == opt_in_status)
            count_stmt = count_stmt.where(Lead.opt_in_status == opt_in_status)

        # Filter by follow-up paused
        if follow_up_paused is not None:
            stmt = stmt.where(Lead.follow_up_paused.is_(follow_up_paused))
            count_stmt = count_stmt.where(Lead.follow_up_paused.is_(follow_up_paused))

        # Filter by needs manual follow-up
        if needs_manual_followup is not None:
            stmt = stmt.where(Lead.needs_manual_followup.is_(needs_manual_followup))
            count_stmt = count_stmt.where(Lead.needs_manual_followup.is_(needs_manual_followup))

        # Search across customer name or phone number
        if search:
            search_pattern = f"%{search.strip()}%"
            search_clause = or_(
                Lead.customer_name.ilike(search_pattern),
                Lead.phone_number.ilike(search_pattern),
                Lead.serial_number.ilike(search_pattern),
            )
            stmt = stmt.where(search_clause)
            count_stmt = count_stmt.where(search_clause)

        # Sorting: if filtering by needs_manual_followup and default sort, prioritize newest reply
        if needs_manual_followup is True and sort_by == "created_at":
            sort_by = "last_replied_at"

        sort_column = getattr(Lead, sort_by, Lead.created_at)
        if sort_order.lower() == "asc":
            stmt = stmt.order_by(sort_column.asc().nullslast())
        else:
            stmt = stmt.order_by(sort_column.desc().nullslast())

        # Pagination calculation
        total = db.scalar(count_stmt) or 0
        total_pages = ceil(total / page_size) if total > 0 else 0
        offset = (page - 1) * page_size

        leads = db.scalars(stmt.offset(offset).limit(page_size)).all()

        return LeadListResponse(
            items=[LeadResponse.model_validate(lead) for lead in leads],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    @staticmethod
    def get_lead_by_id(
        db: Session,
        lead_id: int,
        include_deleted: bool = False,
    ) -> Lead:
        """Retrieve a single lead by ID or raise LeadNotFoundError."""
        lead = db.get(Lead, lead_id)
        if not lead or (lead.is_deleted and not include_deleted):
            raise LeadNotFoundError(f"Lead with ID {lead_id} does not exist")
        return lead

    @classmethod
    def get_lead_details(
        cls,
        db: Session,
        lead_id: int,
        include_deleted: bool = False,
    ) -> LeadDetailResponse:
        """Retrieve full details of a lead with follow-up schedules and message interaction history."""
        lead = cls.get_lead_by_id(db, lead_id, include_deleted=include_deleted)

        schedules = db.scalars(
            select(FollowUpSchedule)
            .where(FollowUpSchedule.lead_id == lead.id)
            .order_by(FollowUpSchedule.sequence_number.asc(), FollowUpSchedule.scheduled_at.asc())
        ).all()

        logs = db.scalars(
            select(MessageLog)
            .where(MessageLog.lead_id == lead.id)
            .order_by(MessageLog.created_at.desc())
        ).all()

        incoming = db.scalars(
            select(IncomingMessage)
            .where(IncomingMessage.lead_id == lead.id)
            .order_by(IncomingMessage.received_at.desc())
        ).all()

        return LeadDetailResponse(
            id=lead.id,
            serial_number=lead.serial_number,
            customer_name=lead.customer_name,
            phone_number=lead.phone_number,
            status=lead.status,
            follow_up_paused=lead.follow_up_paused,
            opt_in_status=lead.opt_in_status,
            opt_in_source=lead.opt_in_source,
            opt_in_timestamp=lead.opt_in_timestamp,
            opt_out_timestamp=lead.opt_out_timestamp,
            is_deleted=lead.is_deleted,
            created_at=lead.created_at,
            updated_at=lead.updated_at,
            follow_up_schedules=[FollowUpScheduleSummary.model_validate(s) for s in schedules],
            message_logs=[MessageLogSummary.model_validate(m) for m in logs],
            incoming_messages=[IncomingMessageSummary.model_validate(i) for i in incoming],
        )

    @classmethod
    def create_lead(cls, db: Session, payload: LeadCreate) -> Lead:
        """Create a new lead with duplicate checking and phone validation."""
        # Validate and clean phone number using agreed normalization
        clean_phone, phone_err = ExcelService.normalize_phone_number(payload.phone_number)
        if phone_err or not clean_phone:
            raise LeadValidationError(phone_err or "Invalid phone number")

        # Check for duplicate phone number
        existing = db.scalar(
            select(Lead).where(Lead.phone_number == clean_phone, Lead.is_deleted.is_(False))
        )
        if existing:
            raise LeadDuplicateError(
                f"A lead with phone number '{clean_phone}' already exists (ID: {existing.id})"
            )

        # Consent verification rule: OPTED_IN requires verifiable source
        initial_opt_in = payload.opt_in_status or "NOT_OPTED_IN"
        if initial_opt_in == "OPTED_IN":
            if not payload.opt_in_source or not payload.opt_in_source.strip():
                raise LeadValidationError(
                    "An explicit, verifiable opt_in_source is required when creating a lead with OPTED_IN consent"
                )

        lead = Lead(
            serial_number=payload.serial_number.strip() if payload.serial_number else None,
            customer_name=payload.customer_name.strip(),
            phone_number=clean_phone,
            status=payload.status or "Pending",
            follow_up_paused=bool(payload.follow_up_paused),
            opt_in_status=initial_opt_in,
            opt_in_source=payload.opt_in_source.strip() if payload.opt_in_source else None,
            opt_in_timestamp=datetime.now(timezone.utc) if initial_opt_in == "OPTED_IN" else None,
            is_deleted=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        db.add(lead)
        db.commit()
        db.refresh(lead)

        # Trigger safe background sync if authorized workbook exists
        cls._trigger_excel_sync_safe(db)

        return lead

    @classmethod
    def update_lead(cls, db: Session, lead_id: int, payload: LeadUpdate) -> Lead:
        """Update lead details with business rules enforcement."""
        lead = cls.get_lead_by_id(db, lead_id)

        # 1. Update Customer Name
        if payload.customer_name is not None:
            name_stripped = payload.customer_name.strip()
            if not name_stripped:
                raise LeadValidationError("Customer name cannot be empty")
            lead.customer_name = name_stripped

        # 2. Update Phone Number with duplicate check
        if payload.phone_number is not None:
            clean_phone, phone_err = ExcelService.normalize_phone_number(payload.phone_number)
            if phone_err or not clean_phone:
                raise LeadValidationError(phone_err or "Invalid phone number")

            # Check if another active lead uses this phone number
            conflict = db.scalar(
                select(Lead).where(
                    Lead.phone_number == clean_phone,
                    Lead.id != lead_id,
                    Lead.is_deleted.is_(False),
                )
            )
            if conflict:
                raise LeadDuplicateError(
                    f"Phone number '{clean_phone}' is already assigned to another lead (ID: {conflict.id})"
                )
            lead.phone_number = clean_phone

        # 3. Update Serial Number
        if payload.serial_number is not None:
            lead.serial_number = payload.serial_number.strip() or None

        # 4. Update Status with business rule enforcement
        if payload.status is not None:
            new_status = payload.status
            if new_status not in ("Pending", "Replied", "Not Interested"):
                raise LeadValidationError(f"Invalid lead status '{new_status}'")

            # Business Rule: "Changing status to Not Interested must cancel or prevent future scheduled follow-ups"
            if new_status == "Not Interested":
                future_schedules = db.scalars(
                    select(FollowUpSchedule).where(
                        FollowUpSchedule.lead_id == lead.id,
                        FollowUpSchedule.status.in_(["Scheduled", "Approved"]),
                    )
                ).all()
                for sched in future_schedules:
                    sched.status = "Cancelled"
                    sched.updated_at = datetime.now(timezone.utc)

            # Business Rule: "Changing status to Replied must NOT automatically pause follow-ups"
            # Explicitly do NOT change lead.follow_up_paused here
            lead.status = new_status

        # 5. Update follow_up_paused flag
        if payload.follow_up_paused is not None:
            # Business Rule: "Only an explicit pause action or flag should pause follow-ups"
            lead.follow_up_paused = payload.follow_up_paused

        # 6. Update consent / opt-in status
        if payload.opt_in_status is not None:
            if payload.opt_in_status not in ("OPTED_IN", "NOT_OPTED_IN", "OPTED_OUT"):
                raise LeadValidationError(f"Invalid opt_in_status '{payload.opt_in_status}'")

            now_utc = datetime.now(timezone.utc)
            if payload.opt_in_status == "OPTED_IN":
                source = payload.opt_in_source or lead.opt_in_source
                if not source or not source.strip():
                    raise LeadValidationError(
                        "An explicit, verifiable opt_in_source is required when setting consent to OPTED_IN"
                    )
                lead.opt_in_source = source.strip()
                lead.opt_in_timestamp = now_utc
            elif payload.opt_in_status == "OPTED_OUT":
                lead.opt_out_timestamp = now_utc
                if payload.opt_in_source is not None:
                    lead.opt_in_source = payload.opt_in_source.strip() or None
            elif payload.opt_in_status == "NOT_OPTED_IN":
                lead.opt_in_timestamp = None
                lead.opt_out_timestamp = None
                if payload.opt_in_source is not None:
                    lead.opt_in_source = payload.opt_in_source.strip() or None
            lead.opt_in_status = payload.opt_in_status
        elif payload.opt_in_source is not None:
            lead.opt_in_source = payload.opt_in_source.strip() or None

        lead.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(lead)

        cls._trigger_excel_sync_safe(db)

        return lead

    @classmethod
    def pause_follow_ups(cls, db: Session, lead_id: int) -> Lead:
        """Explicitly pause automated follow-ups for a lead."""
        lead = cls.get_lead_by_id(db, lead_id)
        lead.follow_up_paused = True
        lead.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(lead)

        cls._trigger_excel_sync_safe(db)
        return lead

    @classmethod
    def resume_follow_ups(cls, db: Session, lead_id: int) -> Lead:
        """Explicitly resume automated follow-ups for a lead."""
        lead = cls.get_lead_by_id(db, lead_id)
        lead.follow_up_paused = False
        lead.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(lead)

        cls._trigger_excel_sync_safe(db)
        return lead

    @classmethod
    def update_consent(
        cls,
        db: Session,
        lead_id: int,
        opt_in_status: str,
        opt_in_source: Optional[str] = None,
    ) -> Lead:
        """Update WhatsApp messaging consent / opt-in status."""
        lead = cls.get_lead_by_id(db, lead_id)
        if opt_in_status not in ("OPTED_IN", "NOT_OPTED_IN", "OPTED_OUT"):
            raise LeadValidationError(f"Invalid opt_in_status '{opt_in_status}'")

        now_utc = datetime.now(timezone.utc)
        if opt_in_status == "OPTED_IN":
            if not opt_in_source or not opt_in_source.strip():
                raise LeadValidationError(
                    "An explicit, verifiable opt_in_source is required when setting consent to OPTED_IN"
                )
            lead.opt_in_source = opt_in_source.strip()
            lead.opt_in_timestamp = now_utc
        elif opt_in_status == "OPTED_OUT":
            lead.opt_out_timestamp = now_utc
            if opt_in_source is not None:
                lead.opt_in_source = opt_in_source.strip() or None
        elif opt_in_status == "NOT_OPTED_IN":
            lead.opt_in_timestamp = None
            lead.opt_out_timestamp = None
            if opt_in_source is not None:
                lead.opt_in_source = opt_in_source.strip() or None

        lead.opt_in_status = opt_in_status
        lead.updated_at = now_utc
        db.commit()
        db.refresh(lead)

        cls._trigger_excel_sync_safe(db)
        return lead

    @classmethod
    def mark_followed_up(
        cls,
        db: Session,
        lead_id: int,
        notes: Optional[str] = None,
    ) -> Lead:
        """Mark an interested lead as followed up by agent."""
        lead = cls.get_lead_by_id(db, lead_id)
        now_utc = datetime.now(timezone.utc)
        lead.needs_manual_followup = False
        lead.followed_up_at = now_utc
        if notes:
            lead.followup_notes = notes.strip()
        lead.updated_at = now_utc

        db.commit()
        db.refresh(lead)

        cls._trigger_excel_sync_safe(db)
        return lead

    @classmethod
    def delete_lead(cls, db: Session, lead_id: int) -> Lead:
        """Safely soft-delete lead to preserve communication and follow-up audit trail.

        Policy:
        - Sets is_deleted = True.
        - Sets follow_up_paused = True.
        - Cancels any active scheduled follow-ups.
        - Preserves all incoming messages, message logs, and past history.
        - Foreign-key constraints remain 100% active.
        """
        lead = cls.get_lead_by_id(db, lead_id)

        # Cancel pending follow-ups
        pending_schedules = db.scalars(
            select(FollowUpSchedule).where(
                FollowUpSchedule.lead_id == lead.id,
                FollowUpSchedule.status.in_(["Scheduled", "Approved"]),
            )
        ).all()
        for sched in pending_schedules:
            sched.status = "Cancelled"
            sched.updated_at = datetime.now(timezone.utc)

        lead.is_deleted = True
        lead.follow_up_paused = True
        lead.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(lead)

        cls._trigger_excel_sync_safe(db)
        return lead

    @staticmethod
    def _trigger_excel_sync_safe(db: Session) -> None:
        """Attempt to synchronize state to authorized workbook if it exists, without breaking DB transaction."""
        settings = get_settings()
        workbook_path = Path(settings.AUTHORIZED_EXCEL_PATH)
        if workbook_path.exists():
            try:
                ExcelService.sync_to_workbook(target_path=str(workbook_path), db=db)
            except Exception as e:
                logger.warning("Post-lead-operation Excel sync was skipped or deferred: %s", str(e))
