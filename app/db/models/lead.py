"""Lead database model definition."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.campaign import CampaignRecipient
    from app.db.models.follow_up import FollowUpSchedule
    from app.db.models.message import IncomingMessage, MessageLog


ALLOWED_LEAD_STATUSES = {"Pending", "Replied", "Not Interested", "Interested"}
ALLOWED_OPT_IN_STATUSES = {"OPTED_IN", "NOT_OPTED_IN", "OPTED_OUT"}


class Lead(Base):
    """Lead model representing travel agency prospects and customer contacts."""

    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Pending', 'Replied', 'Not Interested', 'Interested')",
            name="ck_leads_status_allowed",
        ),
        CheckConstraint(
            "opt_in_status IN ('OPTED_IN', 'NOT_OPTED_IN', 'OPTED_OUT')",
            name="ck_leads_opt_in_status_allowed",
        ),
        Index("ix_leads_phone_status", "phone_number", "status"),
        Index("ix_leads_is_deleted", "is_deleted"),
        Index("ix_leads_opt_in_status", "opt_in_status"),
        Index("ix_leads_needs_manual_followup", "needs_manual_followup"),
        Index("ix_leads_last_replied_at", "last_replied_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    serial_number: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Pending",
    )
    follow_up_paused: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    max_follow_up_limit: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        server_default=text("5"),
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    opt_in_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="NOT_OPTED_IN",
        server_default=text("'NOT_OPTED_IN'"),
    )
    opt_in_source: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    opt_in_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    opt_out_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_reply_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    last_replied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    needs_manual_followup: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
        index=True,
    )
    followed_up_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    followup_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    follow_up_schedules: Mapped[List["FollowUpSchedule"]] = relationship(
        "FollowUpSchedule",
        back_populates="lead",
        cascade="all, delete-orphan",
    )
    campaign_recipients: Mapped[List["CampaignRecipient"]] = relationship(
        "CampaignRecipient",
        back_populates="lead",
        cascade="all, delete-orphan",
    )
    message_logs: Mapped[List["MessageLog"]] = relationship(
        "MessageLog",
        back_populates="lead",
    )
    incoming_messages: Mapped[List["IncomingMessage"]] = relationship(
        "IncomingMessage",
        back_populates="lead",
    )

    @validates("status")
    def validate_status(self, key: str, value: str) -> str:
        """Enforce strict business rules on lead statuses."""
        if value not in ALLOWED_LEAD_STATUSES:
            raise ValueError(
                f"Invalid lead status '{value}'. Allowed statuses are: {', '.join(sorted(ALLOWED_LEAD_STATUSES))}"
            )
        return value

    @validates("opt_in_status")
    def validate_opt_in_status(self, key: str, value: str) -> str:
        """Enforce valid consent / opt-in status."""
        if value not in ALLOWED_OPT_IN_STATUSES:
            raise ValueError(
                f"Invalid opt_in_status '{value}'. Allowed statuses are: {', '.join(sorted(ALLOWED_OPT_IN_STATUSES))}"
            )
        return value

    def __repr__(self) -> str:
        return f"<Lead id={self.id} name='{self.customer_name}' phone='{self.phone_number}' status='{self.status}' is_deleted={self.is_deleted}>"
