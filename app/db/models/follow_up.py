"""Follow-up schedule database model definition."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.lead import Lead


ALLOWED_FOLLOW_UP_STATUSES = {
    "Scheduled",
    "Approved",
    "Sent",
    "Skipped",
    "Failed",
    "Cancelled",
}


class FollowUpSchedule(Base):
    """Customer individual follow-up schedule model."""

    __tablename__ = "follow_up_schedules"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Scheduled', 'Approved', 'Sent', 'Skipped', 'Failed', 'Cancelled')",
            name="ck_follow_up_status_allowed",
        ),
        Index("ix_follow_up_due_lookup", "status", "scheduled_at"),
        Index("ix_follow_up_lead_seq", "lead_id", "sequence_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Scheduled",
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    skip_reason: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
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
    lead: Mapped["Lead"] = relationship(
        "Lead",
        back_populates="follow_up_schedules",
    )

    @validates("status")
    def validate_status(self, key: str, value: str) -> str:
        """Enforce valid schedule status."""
        if value not in ALLOWED_FOLLOW_UP_STATUSES:
            raise ValueError(
                f"Invalid schedule status '{value}'. Allowed statuses: {', '.join(sorted(ALLOWED_FOLLOW_UP_STATUSES))}"
            )
        return value

    def __repr__(self) -> str:
        return f"<FollowUpSchedule id={self.id} lead_id={self.lead_id} seq={self.sequence_number} status='{self.status}'>"
