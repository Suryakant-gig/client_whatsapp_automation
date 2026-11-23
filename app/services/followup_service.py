"""Follow-up schedule domain service and execution logic."""

import logging
from datetime import datetime, timezone
from math import ceil
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import FollowUpSchedule, Lead, MessageLog
from app.schemas.followup_schemas import (
    FollowUpCreate,
    FollowUpListResponse,
    FollowUpResponse,
    FollowUpUpdate,
)
from app.services.sender_boundary import DefaultMessageSender, MessageSenderBoundary

logger = logging.getLogger("app.services.followup")


class FollowUpNotFoundError(Exception):
    """Raised when a follow-up schedule ID is not found."""
    pass


class FollowUpLimitReachedError(Exception):
    """Raised when a lead has already reached their maximum follow-up attempt limit."""
    pass


class FollowUpAlreadyProcessedError(Exception):
    """Raised when attempting to modify or cancel a schedule that has already been processed."""
    pass


class FollowUpValidationError(Exception):
    """Raised when schedule parameters fail validation."""
    pass


class FollowUpService:
    """Service handling follow-up creation, lifecycle, and execution."""

    @staticmethod
    def get_sent_count(db: Session, lead_id: int) -> int:
        """Count successfully sent follow-ups for a lead."""
        count = db.scalar(
            select(func.count(FollowUpSchedule.id)).where(
                FollowUpSchedule.lead_id == lead_id,
                FollowUpSchedule.status == "Sent",
            )
        )
        return count or 0

    @classmethod
    def create_followup(cls, db: Session, payload: FollowUpCreate) -> FollowUpSchedule:
        """Create a new follow-up schedule enforcing customer limit and lead state."""
        lead = db.get(Lead, payload.lead_id)
        if not lead or lead.is_deleted:
            raise FollowUpValidationError(f"Lead with ID {payload.lead_id} does not exist")

        if lead.status == "Not Interested":
            raise FollowUpValidationError("Cannot schedule follow-up: lead is marked 'Not Interested'")

        # Ensure scheduled time is valid and timezone-aware
        scheduled_dt = payload.scheduled_at
        if scheduled_dt.tzinfo is None:
            # Assume UTC if naive
            scheduled_dt = scheduled_dt.replace(tzinfo=timezone.utc)
        else:
            scheduled_dt = scheduled_dt.astimezone(timezone.utc)

        # Check maximum follow-up limit
        sent_count = cls.get_sent_count(db, lead.id)
        if sent_count >= lead.max_follow_up_limit:
            raise FollowUpLimitReachedError(
                f"Customer {lead.customer_name} has reached the maximum follow-up limit ({sent_count}/{lead.max_follow_up_limit})"
            )

        # Calculate next sequence number for this lead
        max_seq = db.scalar(
            select(func.max(FollowUpSchedule.sequence_number)).where(
                FollowUpSchedule.lead_id == lead.id
            )
        )
        next_seq = (max_seq or 0) + 1

        schedule = FollowUpSchedule(
            lead_id=lead.id,
            sequence_number=next_seq,
            scheduled_at=scheduled_dt,
            status="Scheduled",
            attempt_number=payload.attempt_number or next_seq,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        db.add(schedule)
        db.commit()
        db.refresh(schedule)

        return schedule

    @staticmethod
    def list_followups(
        db: Session,
        lead_id: Optional[int] = None,
        status: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> FollowUpListResponse:
        """Query paginated follow-up schedules with filters."""
        page = max(1, page)
        page_size = max(1, min(page_size, 100))

        stmt = select(FollowUpSchedule)
        count_stmt = select(func.count(FollowUpSchedule.id))

        if lead_id is not None:
            stmt = stmt.where(FollowUpSchedule.lead_id == lead_id)
            count_stmt = count_stmt.where(FollowUpSchedule.lead_id == lead_id)

        if status:
            stmt = stmt.where(FollowUpSchedule.status == status)
            count_stmt = count_stmt.where(FollowUpSchedule.status == status)

        if start_date:
            start_utc = start_date if start_date.tzinfo else start_date.replace(tzinfo=timezone.utc)
            stmt = stmt.where(FollowUpSchedule.scheduled_at >= start_utc)
            count_stmt = count_stmt.where(FollowUpSchedule.scheduled_at >= start_utc)

        if end_date:
            end_utc = end_date if end_date.tzinfo else end_date.replace(tzinfo=timezone.utc)
            stmt = stmt.where(FollowUpSchedule.scheduled_at <= end_utc)
            count_stmt = count_stmt.where(FollowUpSchedule.scheduled_at <= end_utc)

        stmt = stmt.order_by(FollowUpSchedule.scheduled_at.asc())

        total = db.scalar(count_stmt) or 0
        total_pages = ceil(total / page_size) if total > 0 else 0
        offset = (page - 1) * page_size

        schedules = db.scalars(stmt.offset(offset).limit(page_size)).all()

        return FollowUpListResponse(
            items=[FollowUpResponse.model_validate(s) for s in schedules],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    @staticmethod
    def get_followup_by_id(db: Session, followup_id: int) -> FollowUpSchedule:
        """Retrieve a single schedule by ID."""
        sched = db.get(FollowUpSchedule, followup_id)
        if not sched:
            raise FollowUpNotFoundError(f"Follow-up schedule with ID {followup_id} not found")
        return sched

    @classmethod
    def update_followup(cls, db: Session, followup_id: int, payload: FollowUpUpdate) -> FollowUpSchedule:
        """Update scheduled time of an unprocessed follow-up."""
        sched = cls.get_followup_by_id(db, followup_id)

        # Allow changing scheduled time only if not yet processed
        if sched.status not in ("Scheduled", "Approved"):
            raise FollowUpAlreadyProcessedError(
                f"Cannot modify schedule with status '{sched.status}'. Only Scheduled or Approved items can be edited."
            )

        new_dt = payload.scheduled_at
        if new_dt.tzinfo is None:
            new_dt = new_dt.replace(tzinfo=timezone.utc)
        else:
            new_dt = new_dt.astimezone(timezone.utc)

        sched.scheduled_at = new_dt
        sched.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(sched)
        return sched

    @classmethod
    def cancel_followup(cls, db: Session, followup_id: int) -> FollowUpSchedule:
        """Cancel a pending follow-up. Already sent follow-ups cannot be cancelled."""
        sched = cls.get_followup_by_id(db, followup_id)

        if sched.status == "Sent":
            raise FollowUpAlreadyProcessedError("Cannot cancel a follow-up that has already been sent")

        sched.status = "Cancelled"
        sched.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(sched)
        return sched

    @classmethod
    def check_eligibility(cls, db: Session, lead: Lead, schedule: FollowUpSchedule) -> Tuple[bool, Optional[str]]:
        """Evaluate if a lead and schedule are eligible for follow-up message dispatch."""
        if lead.is_deleted:
            return False, "lead_deleted"

        if lead.status == "Not Interested":
            return False, "lead_not_interested"

        if lead.follow_up_paused:
            return False, "lead_follow_up_paused"

        if lead.opt_in_status == "OPTED_OUT":
            return False, "lead_opted_out"

        if schedule.status not in ("Scheduled", "Approved"):
            return False, f"schedule_status_is_{schedule.status.lower()}"

        sent_count = cls.get_sent_count(db, lead.id)
        if sent_count >= lead.max_follow_up_limit:
            return False, "max_follow_up_limit_reached"

        return True, None

    @classmethod
    def reconcile_offline_missed_schedules(
        cls,
        db: Session,
        as_of_time: Optional[datetime] = None,
    ) -> int:
        """CRITICAL: Reconcile overdue follow-ups missed while application was offline.

        Must be executed on application startup.
        Mark all overdue unprocessed schedules as Skipped with reason 'missed_while_application_offline'.
        Missed messages must NOT be sent automatically upon restart.
        """
        reconciliation_time = as_of_time or datetime.now(timezone.utc)
        if reconciliation_time.tzinfo is None:
            reconciliation_time = reconciliation_time.replace(tzinfo=timezone.utc)

        stmt = select(FollowUpSchedule).where(
            FollowUpSchedule.scheduled_at < reconciliation_time,
            FollowUpSchedule.status.in_(["Scheduled", "Approved"]),
        )
        overdue_schedules = db.scalars(stmt).all()

        if not overdue_schedules:
            return 0

        skipped_count = 0
        now_utc = datetime.now(timezone.utc)

        for sched in overdue_schedules:
            sched.status = "Skipped"
            sched.skip_reason = "missed_while_application_offline"
            sched.processed_at = now_utc
            sched.updated_at = now_utc
            skipped_count += 1

        db.commit()
        logger.info(
            "Offline reconciliation complete: Marked %d overdue schedules as Skipped",
            skipped_count,
        )
        return skipped_count

    @classmethod
    def process_due_schedules(
        cls,
        db: Session,
        sender: Optional[MessageSenderBoundary] = None,
        as_of_time: Optional[datetime] = None,
    ) -> Tuple[int, int, int]:
        """Process all due follow-up schedules.

        Returns: (sent_count, skipped_count, failed_count)
        """
        from app.services.sender_boundary import WhatsAppMessageSender

        if sender is not None:
            sender_boundary = sender
        else:
            settings = get_settings()
            if settings.is_whatsapp_configured:
                sender_boundary = WhatsAppMessageSender()
            else:
                sender_boundary = DefaultMessageSender()
        eval_time = as_of_time or datetime.now(timezone.utc)
        if eval_time.tzinfo is None:
            eval_time = eval_time.replace(tzinfo=timezone.utc)

        stmt = (
            select(FollowUpSchedule)
            .where(
                FollowUpSchedule.scheduled_at <= eval_time,
                FollowUpSchedule.status.in_(["Scheduled", "Approved"]),
            )
            .order_by(FollowUpSchedule.scheduled_at.asc())
        )
        due_schedules = db.scalars(stmt).all()

        sent_count = 0
        skipped_count = 0
        failed_count = 0

        now_utc = datetime.now(timezone.utc)

        for schedule in due_schedules:
            lead = db.get(Lead, schedule.lead_id)
            if not lead:
                schedule.status = "Skipped"
                schedule.skip_reason = "lead_not_found"
                schedule.processed_at = now_utc
                schedule.updated_at = now_utc
                skipped_count += 1
                db.commit()
                continue

            is_eligible, reason = cls.check_eligibility(db, lead, schedule)

            # If sending via WhatsApp, verify documented opt-in consent
            if is_eligible and isinstance(sender_boundary, WhatsAppMessageSender) and lead.opt_in_status != "OPTED_IN":
                is_eligible = False
                reason = "missing_consent"

            if not is_eligible:
                schedule.status = "Skipped"
                schedule.skip_reason = reason
                schedule.processed_at = now_utc
                schedule.updated_at = now_utc
                skipped_count += 1
                db.commit()
                continue

            # Eligible: Dispatch message via sender boundary
            try:
                result = sender_boundary.send_follow_up_message(lead, schedule)

                if result.success:
                    schedule.status = "Sent"
                    schedule.processed_at = result.timestamp or now_utc
                    schedule.updated_at = now_utc

                    # Record outbound message log if not already created by sender
                    existing_log = None
                    if result.whatsapp_message_id:
                        existing_log = db.scalar(
                            select(MessageLog).where(
                                MessageLog.whatsapp_message_id == result.whatsapp_message_id
                            )
                        )
                    if not existing_log:
                        msg_log = MessageLog(
                            lead_id=lead.id,
                            message_type="follow_up",
                            template_name=f"followup_attempt_{schedule.attempt_number}",
                            whatsapp_message_id=result.whatsapp_message_id,
                            delivery_status="Sent",
                            api_status="ACCEPTED",
                            sent_at=result.timestamp or now_utc,
                            created_at=now_utc,
                        )
                        db.add(msg_log)
                    sent_count += 1
                else:
                    schedule.status = "Failed"
                    schedule.skip_reason = result.error_message or "dispatch_failed"
                    schedule.processed_at = result.timestamp or now_utc
                    schedule.updated_at = now_utc
                    failed_count += 1

                db.commit()

            except Exception as e:
                db.rollback()
                logger.error("Error dispatching follow-up schedule %d: %s", schedule.id, str(e))
                schedule.status = "Failed"
                schedule.skip_reason = str(e)
                schedule.processed_at = datetime.now(timezone.utc)
                schedule.updated_at = datetime.now(timezone.utc)
                db.add(schedule)
                db.commit()
                failed_count += 1

        return sent_count, skipped_count, failed_count
