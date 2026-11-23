"""Message logs and incoming webhook message models."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.lead import Lead


class MessageLog(Base):
    """Outbound message audit and delivery status log."""

    __tablename__ = "message_logs"
    __table_args__ = (
        UniqueConstraint("whatsapp_message_id", name="uq_message_logs_wa_id"),
        Index("ix_message_logs_lead_status", "lead_id", "delivery_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lead_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    campaign_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    batch_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("campaign_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    message_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )  # e.g., "template", "follow_up", "campaign", "custom"
    template_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    whatsapp_message_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    delivery_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="Sent",
    )  # e.g., "Sent", "Accepted", "Delivered", "Read", "Failed"
    api_status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )  # e.g., "ACCEPTED", "SUBMITTED", "FAILED"
    error_details: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    failed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    lead: Mapped[Optional["Lead"]] = relationship(
        "Lead",
        back_populates="message_logs",
    )

    def __repr__(self) -> str:
        return (
            f"<MessageLog id={self.id} lead_id={self.lead_id} "
            f"type='{self.message_type}' status='{self.delivery_status}' wa_id='{self.whatsapp_message_id}'>"
        )


class IncomingMessage(Base):
    """Inbound customer webhook message tracking.

    Enforces duplicate prevention via unique WhatsApp message IDs.
    """

    __tablename__ = "incoming_messages"
    __table_args__ = (
        Index("ix_incoming_messages_phone", "sender_phone"),
        Index("ix_incoming_messages_received", "received_at"),
        Index("ix_incoming_messages_status", "processing_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lead_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("leads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    whatsapp_message_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )
    sender_phone: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )
    message_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    message_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="text",
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    processing_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="RECEIVED",
        server_default=text("'RECEIVED'"),
    )
    raw_payload: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    lead: Mapped[Optional["Lead"]] = relationship(
        "Lead",
        back_populates="incoming_messages",
    )

    def __repr__(self) -> str:
        return (
            f"<IncomingMessage id={self.id} from='{self.sender_phone}' "
            f"wa_id='{self.whatsapp_message_id}' lead_id={self.lead_id}>"
        )
