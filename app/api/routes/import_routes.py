"""API routes for Excel/CSV lead import and preview operations."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.import_schemas import (
    ImportConfirmRequest,
    ImportConfirmResponse,
    ImportPreviewResponse,
)
from app.services.excel_service import ExcelService

router = APIRouter(prefix="/api/import", tags=["Lead Import"])


@router.post(
    "/preview",
    response_model=ImportPreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Preview Excel/CSV lead upload",
    description="Parses an uploaded workbook, validates rows, detects duplicates/existing records, and returns preview.",
)
async def preview_lead_import(
    file: UploadFile = File(..., description="Excel (.xlsx) or CSV (.csv) workbook"),
    db: Session = Depends(get_db),
) -> ImportPreviewResponse:
    """Validate workbook and generate import preview without committing data."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must have a filename",
        )

    lower_name = file.filename.lower()
    if not (lower_name.endswith(".xlsx") or lower_name.endswith(".csv")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format. Please upload an Excel (.xlsx) or CSV (.csv) file.",
        )

    try:
        content = await file.read()
        df = ExcelService.read_file_to_dataframe(content, file.filename)
        preview = ExcelService.generate_preview(df, db)
        return preview
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process workbook: {str(e)}",
        ) from e


@router.post(
    "/confirm",
    response_model=ImportConfirmResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm and commit eligible leads",
    description="Transactionally commits confirmed eligible records to SQLite database and logs the sync operation.",
)
def confirm_lead_import(
    payload: ImportConfirmRequest,
    db: Session = Depends(get_db),
) -> ImportConfirmResponse:
    """Commit verified leads into the database."""
    try:
        result = ExcelService.confirm_import(
            records=payload.records,
            file_name=payload.file_name or "uploaded_workbook",
            db=db,
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Import failed: {str(e)}",
        ) from e
