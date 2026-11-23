"""Pydantic schemas for Excel workbook synchronization operations."""

from typing import Optional
from pydantic import BaseModel, Field


class ExcelSyncRequest(BaseModel):
    """Request payload for workbook synchronization."""

    file_path: Optional[str] = Field(
        default=None,
        description="Path to target Excel/CSV workbook (must match or reside in authorized path)",
    )


class ExcelSyncResponse(BaseModel):
    """Result summary of workbook synchronization."""

    success: bool = Field(description="True if synchronization completed without error")
    file_path: str = Field(description="Target workbook path updated")
    backup_path: Optional[str] = Field(default=None, description="Timestamped backup copy location")
    records_matched: int = Field(description="Number of workbook rows matched to SQLite leads")
    records_updated: int = Field(description="Number of rows updated with automation columns")
    message: str = Field(description="Status description")
