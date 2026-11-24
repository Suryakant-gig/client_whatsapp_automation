"""Dashboard service providing aggregated metrics and activity streams."""

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.campaign import Campaign
from app.db.models.lead import Lead
from app.db.models.message import IncomingMessage, MessageLog
from app.db.models.respondent import Respondent
from app.db.models.sync_log import SyncLog
from app.schemas.dashboard_schemas import (
    ActivityItemResponse,
    DashboardOverviewResponse,
    DashboardStatsResponse,
)
from app.schemas.lead_schemas import LeadResponse


class DashboardService:
    """Service calculating aggregated database metrics and activity for CRM dashboard."""

    @staticmethod
    def get_stats(db: Session) -> DashboardStatsResponse:
        """Compute aggregated statistics across leads, campaigns, messages, and schedules using SQL aggregation."""
        # 1. Lead metrics via single SQL statement
        lead_stmt = select(
            func.count(Lead.id).filter(Lead.is_deleted.is_(False)).label("total"),
            func.count(Lead.id).filter(Lead.is_deleted.is_(False), Lead.status == "Pending").label("pending"),
            func.count(Lead.id).filter(Lead.is_deleted.is_(False), Lead.status == "Replied").label("replied"),
            func.count(Lead.id).filter(Lead.is_deleted.is_(False), Lead.status == "Interested").label("interested"),
            func.count(Lead.id).filter(Lead.is_deleted.is_(False), Lead.needs_manual_followup.is_(True)).label("interested_pending_call"),
            func.count(Lead.id).filter(Lead.is_deleted.is_(False), Lead.status == "Not Interested").label("not_interested"),
            func.count(Lead.id).filter(Lead.is_deleted.is_(False), Lead.opt_in_status == "OPTED_IN").label("opted_in"),
            func.count(Lead.id).filter(Lead.is_deleted.is_(False), Lead.opt_in_status == "OPTED_OUT").label("opted_out"),
        )
        lead_row = db.execute(lead_stmt).first()
        total_leads = lead_row.total if lead_row else 0
        pending_leads = lead_row.pending if lead_row else 0
        replied_leads = lead_row.replied if lead_row else 0
        interested_leads = lead_row.interested if lead_row else 0
        interested_pending_call_count = lead_row.interested_pending_call if lead_row else 0
        not_interested_leads = lead_row.not_interested if lead_row else 0
        opted_in_leads = lead_row.opted_in if lead_row else 0
        opted_out_leads = lead_row.opted_out if lead_row else 0

        # Note: Lead model uses statuses {'Pending', 'Replied', 'Not Interested', 'Interested'}
        confirmed_leads = 0

        # 2. Campaign metrics
        camp_stmt = select(
            func.count(Campaign.id).label("total"),
            func.count(Campaign.id).filter(Campaign.status.in_(["Scheduled", "In Progress"])).label("active"),
        )
        camp_row = db.execute(camp_stmt).first()
        total_campaigns = camp_row.total if camp_row else 0
        active_campaigns = camp_row.active if camp_row else 0

        # 3. Message metrics
        msg_stmt = select(
            func.count(MessageLog.id).label("total"),
            func.count(MessageLog.id).filter(MessageLog.delivery_status == "Delivered").label("delivered"),
            func.count(MessageLog.id).filter(MessageLog.delivery_status == "Read").label("read"),
            func.count(MessageLog.id).filter(MessageLog.delivery_status == "Failed").label("failed"),
        )
        msg_row = db.execute(msg_stmt).first()
        total_messages_sent = msg_row.total if msg_row else 0
        delivered_messages = msg_row.delivered if msg_row else 0
        read_messages = msg_row.read if msg_row else 0
        failed_messages = msg_row.failed if msg_row else 0

        # 4. Respondent metrics
        resp_stmt = select(
            func.count(Respondent.id).label("total"),
            func.count(Respondent.id).filter(Respondent.classification == "INTERESTED").label("interested"),
            func.count(Respondent.id).filter(Respondent.classification == "UNCLASSIFIED").label("unclassified"),
        )
        resp_row = db.execute(resp_stmt).first()
        total_respondents = resp_row.total if resp_row else 0
        interested_respondents = resp_row.interested if resp_row else 0
        unclassified_respondents = resp_row.unclassified if resp_row else 0
        scheduled_follow_ups = 0

        # 5. Last sync timestamp
        sync_stmt = select(SyncLog.created_at).order_by(SyncLog.created_at.desc()).limit(1)
        last_sync_timestamp = db.scalar(sync_stmt)

        return DashboardStatsResponse(
            total_leads=total_leads,
            pending_leads=pending_leads,
            replied_leads=replied_leads,
            interested_leads=interested_leads,
            interested_pending_call_count=interested_pending_call_count,
            confirmed_leads=confirmed_leads,
            not_interested_leads=not_interested_leads,
            opted_in_leads=opted_in_leads,
            opted_out_leads=opted_out_leads,
            total_campaigns=total_campaigns,
            active_campaigns=active_campaigns,
            total_messages_sent=total_messages_sent,
            delivered_messages=delivered_messages,
            read_messages=read_messages,
            failed_messages=failed_messages,
            scheduled_follow_ups=scheduled_follow_ups,
            total_respondents=total_respondents,
            interested_respondents=interested_respondents,
            unclassified_respondents=unclassified_respondents,
            last_sync_timestamp=last_sync_timestamp,
        )

    @staticmethod
    def get_recent_activity(db: Session, limit: int = 10) -> List[ActivityItemResponse]:
        """Retrieve merged and chronological timeline of recent CRM events."""
        events: List[ActivityItemResponse] = []

        # Outbound message logs
        msg_stmt = (
            select(MessageLog)
            .order_by(MessageLog.created_at.desc())
            .limit(limit)
        )
        for msg in db.scalars(msg_stmt).all():
            events.append(
                ActivityItemResponse(
                    id=f"msg_{msg.id}",
                    category="message",
                    title=f"Outbound Message: {msg.message_type.title()}",
                    description=f"Status: {msg.delivery_status} (Template: {msg.template_name or 'custom'})",
                    timestamp=msg.created_at,
                    status=msg.delivery_status,
                )
            )

        # Inbound incoming messages
        inc_stmt = (
            select(IncomingMessage)
            .order_by(IncomingMessage.received_at.desc())
            .limit(limit)
        )
        for inc in db.scalars(inc_stmt).all():
            snippet = f": \"{inc.message_text[:40]}...\"" if inc.message_text and len(inc.message_text) > 40 else (f": \"{inc.message_text}\"" if inc.message_text else "")
            events.append(
                ActivityItemResponse(
                    id=f"inc_{inc.id}",
                    category="incoming",
                    title=f"Incoming Customer Message",
                    description=f"From: {inc.sender_phone} ({inc.message_type}){snippet}",
                    timestamp=inc.received_at,
                    status=inc.processing_status,
                )
            )

        # Followed-up calls activity
        call_stmt = (
            select(Lead)
            .where(Lead.followed_up_at.is_not(None))
            .order_by(Lead.followed_up_at.desc())
            .limit(limit)
        )
        for lead in db.scalars(call_stmt).all():
            ts_int = int(lead.followed_up_at.timestamp()) if lead.followed_up_at else 0
            desc = f"Call notes: {lead.followup_notes}" if lead.followup_notes else "Agent completed telephone call."
            events.append(
                ActivityItemResponse(
                    id=f"call_{lead.id}_{ts_int}",
                    category="lead",
                    title=f"Manual follow-up completed for {lead.customer_name}",
                    description=desc,
                    timestamp=lead.followed_up_at,
                    status="Completed",
                )
            )

        # Sync logs
        sync_stmt = (
            select(SyncLog)
            .order_by(SyncLog.created_at.desc())
            .limit(limit)
        )
        for sync in db.scalars(sync_stmt).all():
            events.append(
                ActivityItemResponse(
                    id=f"sync_{sync.id}",
                    category="sync",
                    title=f"Workbook Sync: {sync.operation}",
                    description=f"{sync.records_processed} records processed ({sync.sync_status})",
                    timestamp=sync.created_at,
                    status=sync.sync_status,
                )
            )

        # Sort all combined events descending by timestamp
        events.sort(key=lambda x: x.timestamp, reverse=True)
        return events[:limit]

    @staticmethod
    def get_overview(db: Session) -> DashboardOverviewResponse:
        """Retrieve complete combined overview data including configuration flags."""
        settings = get_settings()
        stats = DashboardService.get_stats(db)
        recent_activity = DashboardService.get_recent_activity(db, limit=8)

        latest_interested = db.scalars(
            select(Lead)
            .where(Lead.is_deleted.is_(False), Lead.needs_manual_followup.is_(True))
            .order_by(Lead.last_replied_at.desc().nullslast(), Lead.created_at.desc())
            .limit(5)
        ).all()

        return DashboardOverviewResponse(
            stats=stats,
            recent_activity=recent_activity,
            interested_pending_call_count=stats.interested_pending_call_count,
            latest_interested_leads=[LeadResponse.model_validate(l) for l in latest_interested],
            server_time=datetime.now(timezone.utc),
            scheduler_enabled=False,
            whatsapp_enabled=settings.WHATSAPP_ENABLED,
        )
