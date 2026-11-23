"""API endpoints for managing WhatsApp message templates."""

from pathlib import Path
import re
from typing import Any, Dict, Optional
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.integrations.whatsapp.client import get_whatsapp_client
from app.integrations.whatsapp.exceptions import WhatsAppAuthError
from app.schemas.template_schemas import (
    TemplateCreate,
    TemplateListResponse,
    TemplateResponse,
    TemplateUpdate,
)
from app.services.template_service import TemplateService

router = APIRouter(prefix="/api/templates", tags=["Templates"])

ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/jpg"}
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
MAX_IMAGE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB


@router.post(
    "/upload-image",
    status_code=status.HTTP_201_CREATED,
    summary="Upload header image for WhatsApp message template",
)
async def upload_template_image(
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    """Upload template header image. Strictly accepts .jpg, .jpeg, .png only (max 5MB).

    Explicitly rejects PDFs, documents, videos, and non-image files with HTTP 400.
    """
    filename = file.filename or "image.jpg"
    ext = Path(filename).suffix.lower()

    # Strict file type validation (Reject PDFs, docs, videos)
    if ext not in ALLOWED_IMAGE_EXTS or (file.content_type and file.content_type.lower() not in ALLOWED_IMAGE_MIMES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image format. Only JPEG (.jpg, .jpeg) and PNG (.png) files are accepted. PDFs and documents are strictly prohibited.",
        )

    # Read content to verify file size <= 5MB
    content = await file.read()
    if len(content) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum allowed size of 5MB (received {len(content) / (1024 * 1024):.2f}MB).",
        )

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # Save to data/uploads/templates/
    upload_dir = Path("data/uploads/templates")
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r"[^a-zA-Z0-9_\.-]", "_", filename)
    unique_filename = f"{uuid.uuid4().hex[:12]}_{safe_name}"
    target_path = upload_dir / unique_filename

    with open(target_path, "wb") as f:
        f.write(content)

    rel_path = f"data/uploads/templates/{unique_filename}"
    image_url = f"/uploads/templates/{unique_filename}"

    return {
        "image_path": rel_path,
        "image_url": image_url,
        "filename": unique_filename,
        "size_bytes": len(content),
    }


@router.get(
    "",
    response_model=TemplateListResponse,
    status_code=status.HTTP_200_OK,
    summary="List registered WhatsApp message templates",
)
async def list_templates(
    approval_status: Optional[str] = Query(None, description="Filter by approval status (APPROVED, PENDING, REJECTED)"),
    category: Optional[str] = Query(None, description="Filter by category (MARKETING, UTILITY, AUTHENTICATION)"),
    db: Session = Depends(get_db),
) -> TemplateListResponse:
    """Retrieve all local template metadata with optional filtering."""
    templates = await TemplateService.get_or_sync_approved_templates(
        db,
        approval_status=approval_status,
        category=category,
    )
    items = [TemplateResponse.model_validate(t) for t in templates]
    return TemplateListResponse(items=items, total=len(items))


@router.post(
    "",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register or submit WhatsApp template",
)
async def register_template(
    payload: TemplateCreate,
    db: Session = Depends(get_db),
) -> TemplateResponse:
    """Register or submit metadata for a WhatsApp template."""
    settings = get_settings()

    # Validate template name format (lowercase letters, numbers, underscores only)
    sanitized_name = payload.template_name.strip().lower()
    if not re.match(r"^[a-z0-9_]+$", sanitized_name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Template name must contain only lowercase alphanumeric characters and underscores (e.g. 'monsoon_offer_2026').",
        )
    payload.template_name = sanitized_name

    # If body_text contains {{1}}, {{2}}, extract expected parameters if not provided
    if payload.body_text and not payload.expected_parameters:
        matches = re.findall(r"\{\{(\d+)\}\}", payload.body_text)
        if matches:
            payload.expected_parameters = [f"param_{m}" for m in sorted(set(matches), key=int)]

    # Validate header image if IMAGE header
    if payload.header_type == "IMAGE" and payload.header_image_path:
        img_path = Path(payload.header_image_path)
        if not img_path.exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Header image file not found at '{payload.header_image_path}'. Please upload image first.",
            )

    # If live Meta API is enabled, submit to Meta
    if settings.WHATSAPP_ENABLED:
        try:
            client = get_whatsapp_client()
            await client.create_meta_template(
                name=payload.template_name,
                category=payload.category,
                language=payload.language,
                body_text=payload.body_text or "",
                header_type=payload.header_type,
                header_image_path=payload.header_image_path,
            )
            payload.approval_status = "PENDING"
        except WhatsAppAuthError as auth_err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Meta Access Token is expired or invalid (Error 190). Please update WHATSAPP_ACCESS_TOKEN in .env with a permanent System User token and restart the server.",
            ) from auth_err
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Meta template submission failed: {str(exc)}",
            ) from exc

    template = TemplateService.register_template(db, payload)
    return TemplateResponse.model_validate(template)


@router.post(
    "/sync",
    status_code=status.HTTP_200_OK,
    summary="Sync template statuses from Meta Cloud API",
)
async def sync_templates_from_meta(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Force synchronization of approved templates from Meta Graph API."""
    settings = get_settings()
    if not settings.WHATSAPP_ENABLED:
        templates = TemplateService.list_templates(db)
        return {
            "synced": True,
            "mock_mode": True,
            "count": len(templates),
            "message": "Meta Cloud API integration is disabled in .env (WHATSAPP_ENABLED=False). Operating in local development mock mode.",
        }

    try:
        client = get_whatsapp_client()
        meta_templates = await client.fetch_meta_templates()
        count = TemplateService.sync_meta_templates_list(db, meta_templates)
        return {
            "synced": True,
            "count": count,
            "message": f"Successfully checked and synchronized {count} templates from Meta Cloud API.",
        }
    except WhatsAppAuthError as auth_err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Meta Access Token is expired or invalid (Error 190). Please update WHATSAPP_ACCESS_TOKEN in .env with a permanent System User token and restart the server.",
        ) from auth_err
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Meta template sync failed: {str(exc)}",
        ) from exc


@router.post(
    "/{template_id}/mock-approve",
    response_model=TemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve template locally in mock development mode",
)
def mock_approve_template(
    template_id: int,
    db: Session = Depends(get_db),
) -> TemplateResponse:
    """Mark a template as APPROVED in local mock mode (available only when WHATSAPP_ENABLED=False)."""
    settings = get_settings()
    if settings.WHATSAPP_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mock approval is not permitted when live WhatsApp Cloud API is enabled. Templates must be approved by Meta.",
        )
    try:
        template = TemplateService.mock_approve_template(db, template_id)
        return TemplateResponse.model_validate(template)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/{template_id}",
    response_model=TemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Get WhatsApp template details",
)
def get_template(
    template_id: int,
    db: Session = Depends(get_db),
) -> TemplateResponse:
    """Retrieve details for a specific WhatsApp template."""
    template = TemplateService.get_template_by_id(db, template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template with ID {template_id} not found",
        )
    return TemplateResponse.model_validate(template)


@router.patch(
    "/{template_id}",
    response_model=TemplateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update WhatsApp template metadata",
)
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    db: Session = Depends(get_db),
) -> TemplateResponse:
    """Update fields of an existing template."""
    try:
        template = TemplateService.update_template(db, template_id, payload)
        return TemplateResponse.model_validate(template)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
