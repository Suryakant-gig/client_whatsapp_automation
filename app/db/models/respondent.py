"""Respondent database model definition.

Represents every customer contact who responds via WhatsApp.
Classifications:
- UNCLASSIFIED (default on inbound reply)
- INTERESTED
- NOT_INTERESTED
- OTHER
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.campaign import Campaign
    from app.db.models.lead import Lead


ALLOWED_CLASSIFICATIONS = {
    "UNCLASSIFIED",
    "INTERESTED",
    "NOT_INTERESTED",
    "OTHER",
}


class Respondent(Base):
    """WhatsApp respondent record storing customer reply history and manual classification."""

    __tablename__ = "respondents"
    __table_args__ = (
        CheckConstraint(
            "classification IN ('UNCLASSIFIED', 'INTERESTED', 'NOT_INTERESTED', 'OTHER')",
            name="ck_respondents_classification_allowed",
        ),
        UniqueConstraint("phone_number", name="uq_respondents_phone_number"),
        Index("ix_respondents_classification", "classification"),
        Index("ix_respondents_last_reply_at", "last_reply_at"),
        Index("ix_respondents_lead_id", "lead_id"),
        Index("ix_respondents_campaign_id", "original_campaign_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lead_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    phone_number: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        unique=True,
        index=True,
    )
    name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    classification: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="UNCLASSIFIED",
        server_default=text("'UNCLASSIFIED'"),
        index=True,
    )
    first_reply_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_reply_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    original_campaign_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    internal_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    lead: Mapped[Optional["Lead"]] = relationship(
        "Lead",
        back_populates="respondents",
    )
    original_campaign: Mapped[Optional["Campaign"]] = relationship(
        "Campaign",
        back_populates="respondents",
    )

    @validates("classification")
    def validate_classification(self, key: str, value: str) -> str:
        """Enforce valid respondent classification."""
        if value not in ALLOWED_CLASSIFICATIONS:
            raise ValueError(
                f"Invalid classification '{value}'. Allowed: {', '.join(sorted(ALLOWED_CLASSIFICATIONS))}"
            )
        return value

    def __repr__(self) -> str:
        return f"<Respondent id={self.id} phone='{self.phone_number}' classification='{self.classification}'>"
