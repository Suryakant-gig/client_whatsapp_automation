"""WhatsApp message template model."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Template(Base):
    """Meta-approved WhatsApp message template definition."""

    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint("template_name", "language", name="uq_template_name_language"),
        Index("ix_templates_category_status", "category", "approval_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    template_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="en",
    )
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )  # e.g., "MARKETING", "UTILITY", "AUTHENTICATION"
    approval_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
    )  # e.g., "APPROVED", "PENDING", "REJECTED"
    body_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    expected_parameters: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )  # JSON-encoded list of expected parameter names
    header_type: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
    )  # e.g., "TEXT", "IMAGE", "DOCUMENT", "VIDEO"
    header_text: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    header_image_path: Mapped[Optional[str]] = mapped_column(
        String(500),
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

    def __repr__(self) -> str:
        return (
            f"<Template id={self.id} name='{self.template_name}' "
            f"lang='{self.language}' status='{self.approval_status}'>"
        )
