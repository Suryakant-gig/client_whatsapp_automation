"""Service managing WhatsApp message template metadata and component validation."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.template import Template
from app.integrations.whatsapp.exceptions import (
    TemplateNotApprovedError,
    TemplateValidationError,
    WhatsAppAuthError,
)
from app.schemas.template_schemas import TemplateCreate, TemplateUpdate

logger = logging.getLogger("app.services.template")


class TemplateService:
    """Business logic for local WhatsApp message templates."""

    @staticmethod
    def list_templates(
        db: Session,
        approval_status: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Template]:
        """Query templates with optional filtering by status or category."""
        stmt = select(Template)
        if approval_status:
            stmt = stmt.where(Template.approval_status == approval_status.upper())
        if category:
            stmt = stmt.where(Template.category == category.upper())
        stmt = stmt.order_by(Template.template_name.asc(), Template.language.asc())
        return list(db.scalars(stmt).all())

    @classmethod
    def sync_meta_templates_list(
        cls,
        db: Session,
        meta_templates: List[Dict[str, Any]],
    ) -> int:
        """Parse raw Meta Graph API templates list and register/update them in local DB.

        Returns the number of templates processed and stored.
        """
        import re
        count = 0
        for item in meta_templates:
            name = item.get("name")
            if not name:
                continue
            language = item.get("language", "en")
            cat = str(item.get("category", "MARKETING")).upper()
            status = str(item.get("status", "APPROVED")).upper()

            body_text = None
            expected_params = []
            header_type = None
            header_text = None

            for comp in item.get("components", []):
                ctype = comp.get("type", "").upper()
                if ctype == "BODY":
                    body_text = comp.get("text")
                    if body_text:
                        matches = re.findall(r"\{\{(\d+)\}\}", body_text)
                        if matches:
                            expected_params = [f"param_{m}" for m in sorted(set(matches), key=int)]
                elif ctype == "HEADER":
                    header_type = comp.get("format", "TEXT")
                    header_text = comp.get("text")

            cls.register_template(
                db,
                TemplateCreate(
                    template_name=name,
                    language=language,
                    category=cat,
                    approval_status=status or "APPROVED",
                    body_text=body_text,
                    expected_parameters=expected_params if expected_params else None,
                    header_type=header_type,
                    header_text=header_text,
                ),
            )
            count += 1
        return count

    @classmethod
    async def get_or_sync_approved_templates(
        cls,
        db: Session,
        approval_status: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Template]:
        """Query templates, syncing approved templates from Meta Cloud API if configured."""
        from app.core.config import get_settings
        from app.integrations.whatsapp.client import get_whatsapp_client

        settings = get_settings()
        # If WHATSAPP_ENABLED is True and access token is present, attempt read-only sync
        if (
            settings.WHATSAPP_ENABLED
            and settings.WHATSAPP_ACCESS_TOKEN.strip()
            and settings.WHATSAPP_BUSINESS_ACCOUNT_ID.strip()
        ):
            try:
                client = get_whatsapp_client()
                meta_templates = await client.fetch_meta_templates()
                # Only sync approved ones during background read-only sync
                approved_meta = [
                    item for item in meta_templates
                    if str(item.get("status", "")).upper() == "APPROVED"
                ]
                cls.sync_meta_templates_list(db, approved_meta)
            except WhatsAppAuthError as auth_err:
                logger.warning("Meta template sync skipped due to authentication failure: %s", auth_err.message)
            except Exception as e:
                logger.warning("Error during Meta template sync: %s", str(e))

        # Query local database
        templates = cls.list_templates(db, approval_status=approval_status, category=category)

        # Fallback if no templates exist in DB
        if not templates and (approval_status is None or approval_status.upper() == "APPROVED"):
            fallback = Template(
                id=1,
                template_name="sample_travel_followup",
                language="en",
                category="MARKETING",
                approval_status="APPROVED",
                body_text="Hi {{1}}, thank you for your interest in our travel packages to {{2}}! How can we assist you today?",
                expected_parameters=json.dumps(["customer_name", "destination"]),
                header_type="TEXT",
                header_text="Exclusive Travel Offers",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            return [fallback]

        return templates

    @staticmethod
    def get_template_by_id(db: Session, template_id: int) -> Optional[Template]:
        """Fetch a template by its primary key ID."""
        return db.get(Template, template_id)

    @staticmethod
    def get_template_by_name(
        db: Session,
        template_name: str,
        language: str = "en",
    ) -> Optional[Template]:
        """Fetch a template by name and language code."""
        stmt = select(Template).where(
            Template.template_name == template_name.strip(),
            Template.language == language.strip(),
        )
        return db.scalar(stmt)

    @classmethod
    def register_template(
        cls,
        db: Session,
        payload: TemplateCreate,
    ) -> Template:
        """Register or update a template's local metadata."""
        existing = cls.get_template_by_name(
            db,
            template_name=payload.template_name,
            language=payload.language,
        )

        expected_json = (
            json.dumps(payload.expected_parameters)
            if payload.expected_parameters is not None
            else None
        )

        now_utc = datetime.now(timezone.utc)

        if existing:
            existing.category = payload.category.upper()
            existing.approval_status = payload.approval_status.upper()
            existing.body_text = payload.body_text
            existing.expected_parameters = expected_json
            existing.header_type = payload.header_type
            existing.header_text = payload.header_text
            if payload.header_image_path is not None:
                existing.header_image_path = payload.header_image_path
            existing.updated_at = now_utc
            db.commit()
            db.refresh(existing)
            logger.info("Updated existing template '%s' [lang=%s]", existing.template_name, existing.language)
            return existing

        template = Template(
            template_name=payload.template_name.strip(),
            language=payload.language.strip(),
            category=payload.category.upper(),
            approval_status=payload.approval_status.upper(),
            body_text=payload.body_text,
            expected_parameters=expected_json,
            header_type=payload.header_type,
            header_text=payload.header_text,
            header_image_path=payload.header_image_path,
            created_at=now_utc,
            updated_at=now_utc,
        )
        db.add(template)
        db.commit()
        db.refresh(template)
        logger.info("Registered new template '%s' [lang=%s, status=%s]", template.template_name, template.language, template.approval_status)
        return template

    @classmethod
    def update_template(
        cls,
        db: Session,
        template_id: int,
        payload: TemplateUpdate,
    ) -> Template:
        """Update fields of an existing template."""
        template = cls.get_template_by_id(db, template_id)
        if not template:
            raise ValueError(f"Template with ID {template_id} not found")

        if payload.category is not None:
            template.category = payload.category.upper()
        if payload.approval_status is not None:
            template.approval_status = payload.approval_status.upper()
        if payload.body_text is not None:
            template.body_text = payload.body_text
        if payload.expected_parameters is not None:
            template.expected_parameters = json.dumps(payload.expected_parameters)
        if payload.header_type is not None:
            template.header_type = payload.header_type
        if payload.header_text is not None:
            template.header_text = payload.header_text
        if payload.header_image_path is not None:
            template.header_image_path = payload.header_image_path

        template.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(template)
        return template

    @classmethod
    def mock_approve_template(cls, db: Session, template_id: int) -> Template:
        """Mark a template as APPROVED locally in mock/development mode."""
        template = cls.get_template_by_id(db, template_id)
        if not template:
            raise ValueError(f"Template with ID {template_id} not found")
        template.approval_status = "APPROVED"
        template.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(template)
        logger.info("Mock-approved template '%s' (ID %d)", template.template_name, template.id)
        return template

    @staticmethod
    def build_components(
        template: Template,
        parameters: Optional[Union[Dict[str, Any], List[Any]]] = None,
        header_parameters: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Validate and construct the official Meta Cloud API components structure.

        Args:
            template: Target approved Template model.
            parameters: Body parameters as ordered list or key-value dictionary.
            header_parameters: Optional list of text parameters for template header.

        Returns:
            List of components matching Meta Graph API format.

        Raises:
            TemplateNotApprovedError: If template is not APPROVED.
            TemplateValidationError: If required parameters are missing or invalid.
        """
        # 1. Enforce Meta approval status
        if template.approval_status != "APPROVED":
            raise TemplateNotApprovedError(
                template_name=template.template_name,
                status=template.approval_status,
            )

        components: List[Dict[str, Any]] = []

        # 2. Add header component if parameters provided
        if header_parameters:
            components.append({
                "type": "header",
                "parameters": [
                    {"type": "text", "text": str(hp)} for hp in header_parameters
                ],
            })

        # 3. Parse expected parameters
        expected_names: List[str] = []
        if template.expected_parameters:
            try:
                parsed = json.loads(template.expected_parameters)
                if isinstance(parsed, list):
                    expected_names = [str(x) for x in parsed]
            except Exception:
                expected_names = [
                    p.strip() for p in template.expected_parameters.split(",") if p.strip()
                ]

        # 4. Validate body parameters against expected schema
        body_param_objects: List[Dict[str, Any]] = []

        if expected_names:
            if not parameters:
                raise TemplateValidationError(
                    f"Template '{template.template_name}' requires parameters {expected_names}, but none were provided"
                )

            if isinstance(parameters, dict):
                for name in expected_names:
                    if name not in parameters or parameters[name] is None:
                        raise TemplateValidationError(
                            f"Missing required parameter '{name}' for template '{template.template_name}'"
                        )
                    val = str(parameters[name]).strip()
                    if not val:
                        raise TemplateValidationError(
                            f"Parameter '{name}' cannot be empty for template '{template.template_name}'"
                        )
                    body_param_objects.append({"type": "text", "text": val})

            elif isinstance(parameters, list):
                if len(parameters) < len(expected_names):
                    raise TemplateValidationError(
                        f"Template '{template.template_name}' expects {len(expected_names)} parameters, but got {len(parameters)}"
                    )
                for val in parameters[:len(expected_names)]:
                    if val is None or not str(val).strip():
                        raise TemplateValidationError("Template parameter values cannot be empty")
                    body_param_objects.append({"type": "text", "text": str(val).strip()})

        elif parameters:
            # No expected names specified, but caller provided a list or dict
            if isinstance(parameters, list):
                for val in parameters:
                    body_param_objects.append({"type": "text", "text": str(val)})
            elif isinstance(parameters, dict):
                for val in parameters.values():
                    body_param_objects.append({"type": "text", "text": str(val)})

        if body_param_objects:
            components.append({
                "type": "body",
                "parameters": body_param_objects,
            })

        return components
