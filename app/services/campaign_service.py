"""Campaign management, batch generation, mandatory approval, and batch sending service (Phase 8)."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.campaign import Campaign, CampaignBatch, CampaignRecipient
from app.db.models.lead import Lead
from app.db.models.message import MessageLog
from app.db.models.template import Template
from app.schemas.campaign_schemas import CampaignCreate, CampaignUpdate
from app.services.excel_service import ExcelService
from app.services.template_service import TemplateService
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger("app.services.campaign")


class CampaignService:
    """Core domain service for campaigns, batch generation, approval, and execution."""

    @staticmethod
    def _normalize_to_utc(dt: Optional[datetime]) -> Optional[datetime]:
        """Normalize datetime to UTC. If naive, assume UTC; if timezone-aware, convert to UTC."""
        if dt is None:
            return None
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc)
        return dt.replace(tzinfo=timezone.utc)

    @staticmethod
    def validate_template(db: Session, template_name: str, language: str = "en") -> Template:
        """Verify that the template exists locally and is approved by Meta."""
        template = TemplateService.get_template_by_name(db, template_name, language)
        if not template:
            raise ValueError(
                f"WhatsApp template '{template_name}' (lang: '{language}') is not registered in the database"
            )

        if template.approval_status.upper() != "APPROVED":
            raise ValueError(
                f"WhatsApp template '{template_name}' is not APPROVED by Meta (current status: '{template.approval_status}'). "
                f"Only approved templates may be used in campaigns."
            )

        return template

    @classmethod
    def evaluate_leads_eligibility(
        cls,
        db: Session,
        lead_ids: Optional[List[int]] = None,
        campaign_id: Optional[int] = None,
    ) -> Tuple[List[Lead], List[Dict[str, Any]]]:
        """Evaluate lead eligibility based on opt-in consent, phone number validity, and business status.
        
        Rules:
        - Only leads with OPTED_IN consent may be included.
        - Valid phone number (preserving country code).
        - Not deleted.
        - Not marked 'Not Interested'.
        - Follow-up not paused.
        - Not already included in the specified campaign.
        
        Returns:
            Tuple of (eligible_leads, excluded_leads_details)
        """
        # Determine existing leads in this campaign to prevent duplicates
        existing_in_campaign: Set[int] = set()
        if campaign_id is not None:
            existing_in_campaign = set(
                db.scalars(
                    select(CampaignRecipient.lead_id)
                    .join(CampaignBatch, CampaignRecipient.batch_id == CampaignBatch.id)
                    .where(CampaignBatch.campaign_id == campaign_id)
                ).all()
            )

        # Retrieve target leads
        if lead_ids is not None:
            if not lead_ids:
                return [], []
            stmt = select(Lead).where(Lead.id.in_(lead_ids)).order_by(Lead.id)
            leads = db.scalars(stmt).all()
            # Check for non-existent lead IDs
            found_ids = {l.id for l in leads}
            missing_ids = set(lead_ids) - found_ids
        else:
            stmt = select(Lead).where(Lead.is_deleted == False).order_by(Lead.id)  # noqa: E712
            leads = db.scalars(stmt).all()
            missing_ids = set()

        eligible_leads: List[Lead] = []
        excluded_details: List[Dict[str, Any]] = []

        # Record missing lead IDs as excluded
        for m_id in sorted(missing_ids):
            excluded_details.append({
                "lead_id": m_id,
                "customer_name": "Unknown",
                "phone_number": "",
                "reason": "Lead ID not found in database",
            })

        for lead in leads:
            reasons = []

            if lead.id in existing_in_campaign:
                reasons.append("Already included in this campaign")

            if lead.is_deleted:
                reasons.append("Lead record is marked deleted")

            # Mandatory opt-in consent check
            if lead.opt_in_status != "OPTED_IN":
                reasons.append(
                    f"Recipient has not provided verified opt-in consent (status: '{lead.opt_in_status}')"
                )

            # Phone number validation
            clean_phone, phone_err = ExcelService.normalize_phone_number(lead.phone_number)
            if phone_err or not clean_phone:
                reasons.append(f"Invalid phone number: {phone_err or 'Invalid format'}")

            # Business status checks
            if lead.status == "Not Interested":
                reasons.append("Lead status is 'Not Interested'")

            if lead.follow_up_paused:
                reasons.append("Follow-ups are paused for this lead")

            if reasons:
                excluded_details.append({
                    "lead_id": lead.id,
                    "customer_name": lead.customer_name,
                    "phone_number": lead.phone_number,
                    "reason": "; ".join(reasons),
                })
            else:
                eligible_leads.append(lead)

        return eligible_leads, excluded_details

    @classmethod
    def create_campaign(
        cls,
        db: Session,
        payload: CampaignCreate,
    ) -> Tuple[Campaign, List[CampaignBatch], List[Dict[str, Any]]]:
        """Create a new campaign with optional automatic batch generation."""
        # 1. Validate template is approved
        cls.validate_template(db, payload.template_name, payload.template_language)

        # 2. Check for duplicate campaign name
        existing_campaign = db.scalar(
            select(Campaign).where(Campaign.campaign_name == payload.campaign_name.strip())
        )
        if existing_campaign:
            raise ValueError(f"Campaign with name '{payload.campaign_name.strip()}' already exists")

        # 3. Instantiate campaign
        scheduled_at = cls._normalize_to_utc(payload.scheduled_at)
        campaign = Campaign(
            campaign_name=payload.campaign_name.strip(),
            template_name=payload.template_name.strip(),
            template_language=payload.template_language.strip(),
            status="Scheduled" if scheduled_at is not None else "Draft",
            scheduled_at=scheduled_at,
            total_leads_selected=0,
            total_leads_eligible=0,
            total_leads_excluded=0,
        )
        db.add(campaign)
        db.flush()

        batches: List[CampaignBatch] = []
        excluded_details: List[Dict[str, Any]] = []

        # 4. Auto-generate batches if requested
        if payload.auto_generate_batches:
            batches, excluded_details = cls.generate_batches(
                db=db,
                campaign_id=campaign.id,
                lead_ids=payload.lead_ids,
                batch_size=payload.batch_size,
                max_recipients=payload.max_recipients,
                carry_forward_interval_hours=payload.carry_forward_interval_hours,
            )

        db.commit()
        db.refresh(campaign)
        return campaign, batches, excluded_details

    @classmethod
    def generate_batches(
        cls,
        db: Session,
        campaign_id: int,
        lead_ids: Optional[List[int]] = None,
        batch_size: int = 50,
        max_recipients: Optional[int] = None,
        carry_forward_interval_hours: Optional[int] = 0,
    ) -> Tuple[List[CampaignBatch], List[Dict[str, Any]]]:
        """Partition eligible campaign leads into sequential batches with individual approval tracking and carry-forward scheduling."""
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            raise ValueError(f"Campaign with ID {campaign_id} does not exist")

        if batch_size <= 0 or batch_size > 50:
            raise ValueError(f"Batch size must be between 1 and 50 recipients (received: {batch_size})")

        # Evaluate eligibility
        eligible_leads, excluded_details = cls.evaluate_leads_eligibility(
            db=db,
            lead_ids=lead_ids,
            campaign_id=campaign.id,
        )

        # Cap eligible leads if max_recipients limit is specified
        if max_recipients is not None and max_recipients > 0 and len(eligible_leads) > max_recipients:
            unselected = eligible_leads[max_recipients:]
            eligible_leads = eligible_leads[:max_recipients]
            for u in unselected:
                excluded_details.append({
                    "lead_id": u.id,
                    "customer_name": u.customer_name,
                    "phone_number": u.phone_number,
                    "reason": f"Excluded by Max Recipients limit ({max_recipients})",
                })

        total_selected = len(eligible_leads) + len(excluded_details)
        campaign.total_leads_selected += total_selected
        campaign.total_leads_eligible += len(eligible_leads)
        campaign.total_leads_excluded += len(excluded_details)

        if not eligible_leads:
            db.commit()
            return [], excluded_details

        # Find current highest batch number for this campaign
        max_batch_no = (
            db.scalar(
                select(func.max(CampaignBatch.batch_number)).where(
                    CampaignBatch.campaign_id == campaign.id
                )
            )
            or 0
        )

        # Determine base scheduled datetime for carry-forward progression (normalized to UTC)
        base_time = cls._normalize_to_utc(campaign.scheduled_at) or datetime.now(timezone.utc)
        if base_time.tzinfo is None:
            base_time = base_time.replace(tzinfo=timezone.utc)
        else:
            base_time = base_time.astimezone(timezone.utc)

        # Partition eligible leads into chunks of batch_size
        batches: List[CampaignBatch] = []
        batch_idx = 0
        for i in range(0, len(eligible_leads), batch_size):
            chunk = eligible_leads[i : i + batch_size]
            max_batch_no += 1

            # Compute carry-forward scheduled time per batch
            if carry_forward_interval_hours and carry_forward_interval_hours > 0:
                batch_scheduled_at = base_time + timedelta(hours=batch_idx * carry_forward_interval_hours)
            else:
                batch_scheduled_at = cls._normalize_to_utc(campaign.scheduled_at)

            batch = CampaignBatch(
                campaign_id=campaign.id,
                batch_number=max_batch_no,
                batch_size=len(chunk),
                approval_status="Pending",  # Represented as PENDING_APPROVAL
                approved_at=None,
                send_status="Pending",
                scheduled_at=batch_scheduled_at,
                total_messages_count=len(chunk),
                sent_messages_count=0,
                failed_messages_count=0,
            )
            db.add(batch)
            db.flush()

            for lead in chunk:
                recipient = CampaignRecipient(
                    batch_id=batch.id,
                    lead_id=lead.id,
                    send_status="Pending",
                )
                db.add(recipient)

            batches.append(batch)
            batch_idx += 1

        if campaign.status == "Draft" and batches:
            campaign.status = "Scheduled"

        db.commit()
        for b in batches:
            db.refresh(b)
        db.refresh(campaign)

        return batches, excluded_details

    @classmethod
    def list_campaigns(
        cls,
        db: Session,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
    ) -> Tuple[List[Campaign], int]:
        """Retrieve paginated list of campaigns with optional status filtering."""
        stmt = select(Campaign)
        if status:
            stmt = stmt.where(Campaign.status == status.strip())

        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        offset = (page - 1) * page_size
        items = db.scalars(stmt.order_by(Campaign.created_at.desc()).offset(offset).limit(page_size)).all()
        return list(items), total

    @classmethod
    def get_campaign(cls, db: Session, campaign_id: int) -> Campaign:
        """Retrieve a single campaign by ID."""
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            raise ValueError(f"Campaign with ID {campaign_id} does not exist")
        return campaign

    @classmethod
    def update_campaign(
        cls,
        db: Session,
        campaign_id: int,
        payload: CampaignUpdate,
    ) -> Campaign:
        """Update editable fields of a campaign if in Draft or Scheduled status."""
        campaign = cls.get_campaign(db, campaign_id)
        if campaign.status not in ("Draft", "Scheduled"):
            raise ValueError(
                f"Campaign in '{campaign.status}' status cannot be modified. Only Draft or Scheduled campaigns may be edited."
            )

        batches = cls.list_batches(db, campaign_id)
        if any(b.send_status in ("In Progress", "Completed", "Partially Failed") for b in batches):
            raise ValueError("Cannot modify campaign: One or more batches have already begun message dispatch.")

        if payload.campaign_name is not None and payload.campaign_name.strip():
            new_name = payload.campaign_name.strip()
            if new_name != campaign.campaign_name:
                existing = db.scalar(
                    select(Campaign).where(Campaign.campaign_name == new_name, Campaign.id != campaign.id)
                )
                if existing:
                    raise ValueError(f"Campaign with name '{new_name}' already exists")
                campaign.campaign_name = new_name

        new_template = payload.template_name.strip() if payload.template_name else campaign.template_name
        new_lang = payload.template_language.strip() if payload.template_language else campaign.template_language

        if payload.template_name is not None or payload.template_language is not None:
            cls.validate_template(db, new_template, new_lang)
            campaign.template_name = new_template
            campaign.template_language = new_lang

        if payload.scheduled_at is not None:
            campaign.scheduled_at = cls._normalize_to_utc(payload.scheduled_at)

        campaign.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(campaign)
        return campaign

    @classmethod
    def list_batches(cls, db: Session, campaign_id: int) -> List[CampaignBatch]:
        """Retrieve all batches for a given campaign."""
        campaign = cls.get_campaign(db, campaign_id)
        stmt = (
            select(CampaignBatch)
            .where(CampaignBatch.campaign_id == campaign.id)
            .order_by(CampaignBatch.batch_number.asc())
        )
        return list(db.scalars(stmt).all())

    @classmethod
    def get_batch(cls, db: Session, campaign_id: int, batch_id: int) -> CampaignBatch:
        """Retrieve a specific batch and ensure it belongs to the specified campaign."""
        batch = db.get(CampaignBatch, batch_id)
        if not batch or batch.campaign_id != campaign_id:
            raise ValueError(f"Batch {batch_id} not found in campaign {campaign_id}")
        return batch

    @classmethod
    def approve_batch(cls, db: Session, campaign_id: int, batch_id: int) -> CampaignBatch:
        """Perform mandatory human approval for an individual batch.
        
        Enforces:
        - Only approves this specific batch (approving one batch does NOT approve another).
        - Idempotent: Repeated approval does not create duplicate actions.
        - Records approved_at timestamp.
        - Does NOT trigger automated message sending.
        """
        batch = cls.get_batch(db, campaign_id, batch_id)

        # Idempotent check
        if batch.approval_status in ("Approved", "APPROVED"):
            logger.info("Batch %d in campaign %d is already approved", batch_id, campaign_id)
            return batch

        if batch.approval_status == "Rejected":
            raise ValueError(f"Batch {batch.batch_number} has been rejected and cannot be approved")

        batch.approval_status = "Approved"
        batch.approved_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(batch)

        logger.info(
            "Batch %d (batch_number=%d) in campaign %d approved at %s",
            batch.id,
            batch.batch_number,
            campaign_id,
            batch.approved_at.isoformat(),
        )
        return batch

    @classmethod
    def reject_batch(cls, db: Session, campaign_id: int, batch_id: int) -> CampaignBatch:
        """Perform mandatory human rejection for an individual batch.
        
        Enforces:
        - Idempotent: Repeated rejection returns the rejected batch safely.
        - An approved batch or sent batch cannot be rejected.
        - Sets approval_status to 'Rejected'.
        """
        batch = cls.get_batch(db, campaign_id, batch_id)

        if batch.approval_status in ("Approved", "APPROVED"):
            raise ValueError(f"Batch {batch.batch_number} has already been approved and cannot be rejected")

        if batch.send_status in ("In Progress", "Completed", "Partially Failed"):
            raise ValueError(f"Batch {batch.batch_number} has already begun dispatch (status: '{batch.send_status}')")

        if batch.approval_status == "Rejected":
            return batch

        batch.approval_status = "Rejected"
        db.commit()
        db.refresh(batch)

        logger.info("Batch %d in campaign %d was rejected by administrator", batch.id, campaign_id)
        return batch

    @classmethod
    def send_batch(
        cls,
        db: Session,
        campaign_id: int,
        batch_id: int,
        client: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Dispatch messages for an approved batch upon explicit user trigger.
        
        Enforces:
        - Revalidates lead consent and eligibility immediately before dispatch.
        - Batch must be approved; unapproved batches are rejected.
        - Prevents duplicate sends.
        - Handles partial failures safely without crashing the batch.
        - Links MessageLog with campaign_id, batch_id, and CampaignRecipient.
        """
        batch = cls.get_batch(db, campaign_id, batch_id)
        campaign = cls.get_campaign(db, campaign_id)

        # 1. Mandatory approval verification
        if batch.approval_status not in ("Approved", "APPROVED"):
            raise ValueError(
                f"Batch {batch.batch_number} cannot be sent: It has not been approved "
                f"(current approval status: '{batch.approval_status}'). Mandatory individual approval is required."
            )

        # 2. Duplicate send prevention
        if batch.send_status in ("Completed", "In Progress"):
            raise ValueError(
                f"Batch {batch.batch_number} has already been initiated or completed (status: '{batch.send_status}'). "
                f"Duplicate send request rejected."
            )

        # 3. Verify template is still approved
        cls.validate_template(db, campaign.template_name, campaign.template_language)

        batch.send_status = "In Progress"
        campaign.status = "In Progress"
        db.commit()

        # 4. Fetch pending recipients for this batch
        recipients = db.scalars(
            select(CampaignRecipient)
            .where(
                CampaignRecipient.batch_id == batch.id,
                CampaignRecipient.send_status == "Pending",
            )
            .order_by(CampaignRecipient.id.asc())
        ).all()

        sent_count = 0
        failed_count = 0
        skipped_count = 0

        for rec in recipients:
            lead = db.get(Lead, rec.lead_id)

            # Revalidate lead consent and state immediately prior to dispatch
            if not lead or lead.is_deleted:
                rec.send_status = "Skipped"
                rec.error_details = "Lead was deleted prior to dispatch"
                skipped_count += 1
                continue

            if lead.opt_in_status != "OPTED_IN":
                rec.send_status = "Skipped"
                rec.error_details = f"Opt-in consent not verified (status: '{lead.opt_in_status}')"
                skipped_count += 1
                continue

            if lead.status == "Not Interested":
                rec.send_status = "Skipped"
                rec.error_details = "Lead marked Not Interested prior to dispatch"
                skipped_count += 1
                continue

            if lead.follow_up_paused:
                rec.send_status = "Skipped"
                rec.error_details = "Lead follow-up paused prior to dispatch"
                skipped_count += 1
                continue

            clean_phone, phone_err = ExcelService.normalize_phone_number(lead.phone_number)
            if phone_err or not clean_phone:
                rec.send_status = "Failed"
                rec.error_details = f"Invalid phone number: {phone_err}"
                failed_count += 1
                continue

            # Dispatch approved template
            params = {"customer_name": lead.customer_name}
            try:
                msg_log = WhatsAppService.send_template_message_sync(
                    db=db,
                    lead_id=lead.id,
                    template_name=campaign.template_name,
                    language=campaign.template_language,
                    parameters=params,
                    message_type="campaign",
                    client=client,
                    campaign_id=campaign.id,
                    batch_id=batch.id,
                )
                rec.send_status = "Sent"
                rec.sent_at = datetime.now(timezone.utc)
                rec.message_log_id = msg_log.id
                sent_count += 1

            except Exception as exc:
                logger.warning(
                    "Campaign message dispatch failed for recipient %d (lead %d): %s",
                    rec.id,
                    lead.id,
                    str(exc),
                )
                rec.send_status = "Failed"
                rec.error_details = str(exc)
                failed_count += 1

        # 5. Update batch outcome metrics
        batch.sent_messages_count = sent_count
        batch.failed_messages_count = failed_count
        batch.sent_at = datetime.now(timezone.utc)

        if sent_count > 0 and failed_count == 0 and skipped_count == 0:
            batch.send_status = "Completed"
        elif sent_count > 0 and (failed_count > 0 or skipped_count > 0):
            batch.send_status = "Partially Failed"
        else:
            batch.send_status = "Failed"

        # 6. Check campaign-wide completion
        all_batches = db.scalars(
            select(CampaignBatch).where(CampaignBatch.campaign_id == campaign.id)
        ).all()
        if all(b.send_status in ("Completed", "Partially Failed", "Failed") for b in all_batches):
            campaign.status = "Completed"
        else:
            campaign.status = "In Progress"

        db.commit()
        db.refresh(batch)
        db.refresh(campaign)

        return {
            "batch_id": batch.id,
            "campaign_id": campaign.id,
            "batch_number": batch.batch_number,
            "total_recipients": len(recipients),
            "sent_count": sent_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "send_status": batch.send_status,
        }

    @classmethod
    def get_campaign_report(cls, db: Session, campaign_id: int) -> Dict[str, Any]:
        """Aggregate campaign metrics including batches, approvals, and webhook delivery counts."""
        campaign = cls.get_campaign(db, campaign_id)
        batches = cls.list_batches(db, campaign_id)

        pending_approvals = sum(
            1 for b in batches if b.approval_status in ("Pending", "PENDING_APPROVAL")
        )
        approved_batches = sum(1 for b in batches if b.approval_status in ("Approved", "APPROVED"))
        rejected_batches = sum(1 for b in batches if b.approval_status in ("Rejected", "REJECTED"))
        sent_batches = sum(1 for b in batches if b.send_status in ("Completed", "Sent"))

        total_partitioned = sum(b.batch_size for b in batches)

        # Message status counts from message_logs linked to this campaign
        logs = db.scalars(
            select(MessageLog).where(MessageLog.campaign_id == campaign_id)
        ).all()

        accepted_messages = sum(1 for m in logs if m.delivery_status == "Accepted")
        sent_messages = sum(1 for m in logs if m.delivery_status == "Sent")
        delivered_messages = sum(1 for m in logs if m.delivery_status == "Delivered")
        read_messages = sum(1 for m in logs if m.delivery_status == "Read")
        
        # Consistent failure tracking: use get_failed_recipients so summary matches audit log exactly
        failed_list = cls.get_failed_recipients(db, campaign_id)
        failed_messages = len(failed_list)

        total_dispatched = sent_messages + delivered_messages + read_messages + failed_messages
        # Correct delivery rate: 0.0% if no messages sent (never false 100%)
        delivery_rate = round((delivered_messages / total_dispatched) * 100, 1) if total_dispatched > 0 else 0.0

        return {
            "campaign_id": campaign.id,
            "campaign_name": campaign.campaign_name,
            "name": campaign.campaign_name,
            "template_name": campaign.template_name,
            "template_language": campaign.template_language,
            "status": campaign.status,
            "total_selected_leads": campaign.total_leads_selected,
            "eligible_leads": campaign.total_leads_eligible,
            "excluded_leads": campaign.total_leads_excluded,
            "total_partitioned_recipients": total_partitioned,
            "total_recipients": total_partitioned,
            "number_of_batches": len(batches),
            "total_batches": len(batches),
            "batches_total": len(batches),
            "pending_approvals": pending_approvals,
            "batches_pending": pending_approvals,
            "approved_batches": approved_batches,
            "batches_approved": approved_batches,
            "batches_sent": sent_batches,
            "batches_rejected": rejected_batches,
            "accepted_messages": accepted_messages,
            "sent_messages": sent_messages,
            "sent_count": sent_messages,
            "delivered_messages": delivered_messages,
            "delivered_count": delivered_messages,
            "read_messages": read_messages,
            "read_count": read_messages,
            "failed_messages": failed_messages,
            "failed_count": failed_messages,
            "dispatch_failures": failed_messages,
            "delivery_rate": delivery_rate,
            "created_at": campaign.created_at,
        }

    @classmethod
    def get_failed_recipients(cls, db: Session, campaign_id: int) -> List[Dict[str, Any]]:
        """Retrieve all failed recipients in a campaign for manual review."""
        cls.get_campaign(db, campaign_id)

        failed_list: List[Dict[str, Any]] = []
        seen_lead_ids: Set[int] = set()

        # 1. Failed recipients from campaign_recipients
        stmt = (
            select(CampaignRecipient, CampaignBatch, Lead)
            .join(CampaignBatch, CampaignRecipient.batch_id == CampaignBatch.id)
            .join(Lead, CampaignRecipient.lead_id == Lead.id)
            .where(
                CampaignBatch.campaign_id == campaign_id,
                CampaignRecipient.send_status == "Failed",
            )
            .order_by(CampaignBatch.batch_number.asc(), CampaignRecipient.id.asc())
        )
        results = db.execute(stmt).all()

        for rec, batch, lead in results:
            attempted = rec.sent_at or rec.created_at
            err_msg = rec.error_details or "Dispatch failure"
            failed_list.append({
                "recipient_id": rec.id,
                "batch_id": batch.id,
                "batch_number": batch.batch_number,
                "lead_id": lead.id,
                "customer_name": lead.customer_name,
                "lead_name": lead.customer_name,
                "phone_number": lead.phone_number,
                "send_status": rec.send_status,
                "error_details": err_msg,
                "error_message": err_msg,
                "error_code": None,
                "attempted_at": attempted,
                "failed_at": attempted,
            })
            seen_lead_ids.add(lead.id)

        # 2. Also retrieve any failed message_logs linked to this campaign
        stmt_logs = (
            select(MessageLog)
            .where(
                MessageLog.campaign_id == campaign_id,
                MessageLog.delivery_status == "Failed",
            )
            .order_by(MessageLog.id.asc())
        )
        logs = db.scalars(stmt_logs).all()
        for log in logs:
            if log.lead_id and log.lead_id in seen_lead_ids:
                continue
            batch_no = None
            if log.batch_id:
                b = db.get(CampaignBatch, log.batch_id)
                if b:
                    batch_no = b.batch_number
            lead = log.lead
            lead_name = lead.customer_name if lead else (f"Lead #{log.lead_id}" if log.lead_id else "Unknown")
            phone = lead.phone_number if lead else ""
            attempted = log.failed_at or log.sent_at or log.created_at
            err_msg = log.error_details or log.api_status or "Dispatch failure"
            failed_list.append({
                "recipient_id": None,
                "batch_id": log.batch_id,
                "batch_number": batch_no,
                "lead_id": log.lead_id,
                "customer_name": lead_name,
                "lead_name": lead_name,
                "phone_number": phone,
                "send_status": "Failed",
                "error_details": err_msg,
                "error_message": err_msg,
                "error_code": log.api_status,
                "attempted_at": attempted,
                "failed_at": attempted,
            })
            if log.lead_id:
                seen_lead_ids.add(log.lead_id)

        return failed_list

    @classmethod
    def list_all_batches(
        cls,
        db: Session,
        approval_status: Optional[str] = None,
        send_status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Retrieve batches across all campaigns with campaign names and template metadata."""
        stmt = (
            select(CampaignBatch, Campaign.campaign_name, Campaign.template_name)
            .join(Campaign, CampaignBatch.campaign_id == Campaign.id)
        )
        if approval_status and approval_status.upper() != "ALL":
            if approval_status.upper() in ("PENDING", "PENDING_APPROVAL"):
                stmt = stmt.where(CampaignBatch.approval_status.in_(["Pending", "PENDING_APPROVAL"]))
            elif approval_status.upper() == "APPROVED":
                stmt = stmt.where(CampaignBatch.approval_status.in_(["Approved", "APPROVED"]))
            elif approval_status.upper() == "REJECTED":
                stmt = stmt.where(CampaignBatch.approval_status.in_(["Rejected", "REJECTED"]))
            else:
                stmt = stmt.where(CampaignBatch.approval_status == approval_status)
        if send_status and send_status.upper() != "ALL":
            stmt = stmt.where(CampaignBatch.send_status == send_status)

        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        offset = (page - 1) * page_size
        records = db.execute(
            stmt.order_by(CampaignBatch.created_at.desc(), CampaignBatch.id.desc())
            .offset(offset)
            .limit(page_size)
        ).all()

        items = []
        for batch, c_name, t_name in records:
            approval_display = "PENDING_APPROVAL" if batch.approval_status == "Pending" else batch.approval_status
            items.append({
                "id": batch.id,
                "campaign_id": batch.campaign_id,
                "campaign_name": c_name,
                "template_name": t_name,
                "batch_number": batch.batch_number,
                "batch_size": batch.batch_size,
                "approval_status": approval_display,
                "approved_at": batch.approved_at,
                "send_status": batch.send_status,
                "sent_at": batch.sent_at,
                "scheduled_at": batch.scheduled_at,
                "total_messages_count": batch.total_messages_count,
                "sent_messages_count": batch.sent_messages_count,
                "failed_messages_count": batch.failed_messages_count,
                "created_at": batch.created_at,
            })
        return items, total

    @classmethod
    def get_eligible_summary(cls, db: Session) -> Dict[str, int]:
        """Get summary counts of total leads and eligible opted-in candidates."""
        total = db.scalar(select(func.count(Lead.id)).where(Lead.is_deleted == False)) or 0
        eligible, excluded = cls.evaluate_leads_eligibility(db)
        return {
            "total_leads": total,
            "eligible_leads_count": len(eligible),
            "excluded_leads_count": len(excluded),
        }

    @classmethod
    def get_eligible_leads_list(cls, db: Session) -> List[Dict[str, Any]]:
        """Get full list of candidate leads eligible for targeted campaign creation."""
        eligible, _ = cls.evaluate_leads_eligibility(db)
        return [
            {
                "id": lead.id,
                "customer_name": lead.customer_name,
                "phone_number": lead.phone_number,
                "opt_in_status": lead.opt_in_status,
                "status": lead.status,
                "destination": getattr(lead, "destination", None) or getattr(lead, "preferred_destinations", None),
                "created_at": lead.created_at,
            }
            for lead in eligible
        ]
