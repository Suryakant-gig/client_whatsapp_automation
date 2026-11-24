"""Campaign, campaign batch, and campaign recipient models."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.lead import Lead
    from app.db.models.message import MessageLog
    from app.db.models.respondent import Respondent


ALLOWED_CAMPAIGN_STATUSES = {"Draft", "Scheduled", "In Progress", "Completed", "Cancelled"}
ALLOWED_BATCH_APPROVAL_STATUSES = {"Pending", "Approved", "Rejected", "PENDING_APPROVAL"}
ALLOWED_BATCH_SEND_STATUSES = {"Pending", "In Progress", "Completed", "Partially Failed", "Failed"}
ALLOWED_SEND_STATUSES = {"Pending", "Sent", "Failed", "Skipped"}


class Campaign(Base):
    """Marketing and follow-up broadcast campaign model."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    template_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    template_language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="en",
        server_default=text("'en'"),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Draft",
    )
    total_leads_selected: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    total_leads_eligible: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    total_leads_excluded: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    batches: Mapped[List["CampaignBatch"]] = relationship(
        "CampaignBatch",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    respondents: Mapped[List["Respondent"]] = relationship(
        "Respondent",
        back_populates="original_campaign",
    )

    @validates("status")
    def validate_status(self, key: str, value: str) -> str:
        """Enforce valid campaign status."""
        if value not in ALLOWED_CAMPAIGN_STATUSES:
            raise ValueError(
                f"Invalid campaign status '{value}'. Allowed: {', '.join(sorted(ALLOWED_CAMPAIGN_STATUSES))}"
            )
        return value

    def __repr__(self) -> str:
        return f"<Campaign id={self.id} name='{self.campaign_name}' status='{self.status}'>"


class CampaignBatch(Base):
    """Individual batch within a campaign requiring human review and approval.

    Enforces batch limits (normally up to 50 recipients).
    """

    __tablename__ = "campaign_batches"
    __table_args__ = (
        CheckConstraint(
            "batch_size > 0 AND batch_size <= 50",
            name="ck_batch_size_limit",
        ),
        CheckConstraint(
            "approval_status IN ('Pending', 'Approved', 'Rejected')",
            name="ck_batch_approval_status",
        ),
        UniqueConstraint("campaign_id", "batch_number", name="uq_campaign_batch_number"),
        Index("ix_campaign_batch_status", "campaign_id", "approval_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_number: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    approval_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Pending",
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    send_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Pending",
        server_default=text("'Pending'"),
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    total_messages_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    sent_messages_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    failed_messages_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    campaign: Mapped["Campaign"] = relationship(
        "Campaign",
        back_populates="batches",
    )
    recipients: Mapped[List["CampaignRecipient"]] = relationship(
        "CampaignRecipient",
        back_populates="batch",
        cascade="all, delete-orphan",
    )

    @validates("batch_size")
    def validate_batch_size(self, key: str, value: int) -> int:
        """Enforce maximum batch limit of 50 recipients."""
        if value <= 0 or value > 50:
            raise ValueError(
                f"Batch size must be between 1 and 50 recipients (received: {value})"
            )
        return value

    @validates("approval_status")
    def validate_approval_status(self, key: str, value: str) -> str:
        """Enforce valid batch approval status."""
        val = value.strip()
        if val.upper() == "PENDING_APPROVAL":
            val = "Pending"
        elif val.upper() == "APPROVED":
            val = "Approved"
        elif val.upper() == "REJECTED":
            val = "Rejected"
        if val not in ALLOWED_BATCH_APPROVAL_STATUSES:
            raise ValueError(
                f"Invalid approval status '{value}'. Allowed: {', '.join(sorted(ALLOWED_BATCH_APPROVAL_STATUSES))}"
            )
        return val

    def __repr__(self) -> str:
        return (
            f"<CampaignBatch id={self.id} campaign_id={self.campaign_id} "
            f"batch_no={self.batch_number} size={self.batch_size} status='{self.approval_status}'>"
        )


class CampaignRecipient(Base):
    """Specific recipient lead included in a campaign batch.

    Enforces prevention of duplicate leads in the same batch.
    """

    __tablename__ = "campaign_recipients"
    __table_args__ = (
        UniqueConstraint("batch_id", "lead_id", name="uq_batch_lead_recipient"),
        CheckConstraint(
            "send_status IN ('Pending', 'Sent', 'Failed', 'Skipped')",
            name="ck_recipient_send_status",
        ),
        Index("ix_recipient_batch_status", "batch_id", "send_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("campaign_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    send_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Pending",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    message_log_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("message_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    error_details: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationships
    batch: Mapped["CampaignBatch"] = relationship(
        "CampaignBatch",
        back_populates="recipients",
    )
    lead: Mapped["Lead"] = relationship(
        "Lead",
        back_populates="campaign_recipients",
    )

    @validates("send_status")
    def validate_send_status(self, key: str, value: str) -> str:
        """Enforce valid send status."""
        if value not in ALLOWED_SEND_STATUSES:
            raise ValueError(
                f"Invalid send status '{value}'. Allowed: {', '.join(sorted(ALLOWED_SEND_STATUSES))}"
            )
        return value

    def __repr__(self) -> str:
        return f"<CampaignRecipient id={self.id} batch_id={self.batch_id} lead_id={self.lead_id} status='{self.send_status}'>"
