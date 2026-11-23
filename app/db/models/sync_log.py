"""Data import and synchronization audit log model."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SyncLog(Base):
    """Audit log tracking Excel/CSV lead import and synchronization runs."""

    __tablename__ = "sync_logs"
    __table_args__ = (
        Index("ix_sync_logs_op_status", "operation", "sync_status"),
        Index("ix_sync_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    operation: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )  # e.g., "excel_import", "csv_import", "manual_sync"
    file_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    sync_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )  # e.g., "Success", "Failed", "Partial"
    records_processed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<SyncLog id={self.id} op='{self.operation}' "
            f"status='{self.sync_status}' count={self.records_processed}>"
        )
