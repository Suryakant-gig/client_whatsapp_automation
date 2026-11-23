"""API routes for Excel workbook synchronization."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.sync_schemas import ExcelSyncRequest, ExcelSyncResponse
from app.services.excel_service import ExcelService

router = APIRouter(prefix="/api/excel", tags=["Excel Sync"])


@router.post(
    "/sync",
    response_model=ExcelSyncResponse,
    status_code=status.HTTP_200_OK,
    summary="Synchronize database state to Excel workbook",
    description="Updates authorized workbook with latest lead status, follow-up dates, and activity timestamps after creating a timestamped backup.",
)
def sync_excel_workbook(
    payload: ExcelSyncRequest = ExcelSyncRequest(),
    db: Session = Depends(get_db),
) -> ExcelSyncResponse:
    """Safely synchronize SQLite lead records back to original workbook."""
    try:
        response = ExcelService.sync_to_workbook(
            target_path=payload.file_path,
            db=db,
        )
        return response
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except BlockingIOError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workbook synchronization failed: {str(e)}",
        ) from e


@router.get(
    "/backups",
    status_code=status.HTTP_200_OK,
    summary="List existing timestamped Excel workbook backups",
)
def list_excel_backups(
    db: Session = Depends(get_db),
) -> dict:
    """Retrieve existing workbook backups and authorized file location."""
    from app.core.config import get_settings
    settings = get_settings()
    backups = ExcelService.list_backups()
    return {
        "workbook_path": settings.AUTHORIZED_EXCEL_PATH,
        "backup_dir": settings.BACKUP_DIR,
        "backups": backups,
        "total": len(backups),
    }
