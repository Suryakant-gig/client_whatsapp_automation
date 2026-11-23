"""Pydantic schemas for Excel/CSV lead import and preview operations."""

from typing import List, Optional
from pydantic import BaseModel, Field


class RowValidationError(BaseModel):
    """Detailed error entry for a specific row in the uploaded file."""

    row_number: int = Field(description="1-based row index from original file")
    field: str = Field(description="Name of the field failing validation")
    value: Optional[str] = Field(default=None, description="Problematic value observed")
    error_code: str = Field(description="Machine-readable error classification")
    message: str = Field(description="Human-readable explanation of the validation failure")


class EligibleRecord(BaseModel):
    """Clean, validated lead candidate ready for confirmed import."""

    row_number: int = Field(description="Original row index")
    serial_number: str = Field(description="Cleaned lead serial number")
    customer_name: str = Field(description="Customer full name")
    phone_number: str = Field(description="Normalized phone number preserving country code")


class ImportPreviewResponse(BaseModel):
    """Summary and diagnostic preview returned prior to database commit."""

    total_rows: int = Field(description="Total data rows parsed from workbook")
    valid_rows: int = Field(description="Rows meeting syntactic validation")
    invalid_rows: int = Field(description="Rows with missing or malformed fields")
    duplicate_rows: int = Field(description="Rows rejected as duplicate phone numbers within file")
    existing_leads: int = Field(description="Rows already present in SQLite database")
    eligible_for_import: int = Field(description="Net new, valid records eligible for insertion")
    errors: List[RowValidationError] = Field(default_factory=list, description="Row-level diagnostics")
    eligible_records: List[EligibleRecord] = Field(default_factory=list, description="List of importable leads")


class ImportConfirmRequest(BaseModel):
    """Client confirmation payload submitting eligible records for database insertion."""

    records: List[EligibleRecord] = Field(description="List of records explicitly confirmed for import")
    file_name: Optional[str] = Field(default="uploaded_file", description="Original filename for audit log")


class ImportConfirmResponse(BaseModel):
    """Result of confirmed database import transaction."""

    success: bool = Field(description="True if the batch import committed successfully")
    imported_count: int = Field(description="Number of lead records newly committed")
    skipped_count: int = Field(description="Number of records skipped during commit")
    message: str = Field(description="Status description")
