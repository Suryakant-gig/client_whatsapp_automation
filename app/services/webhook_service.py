"""Service handling Meta WhatsApp Webhook verification, security, and event processing."""

import hashlib
import hmac
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.campaign import CampaignBatch, CampaignRecipient
from app.db.models.lead import Lead
from app.db.models.message import IncomingMessage, MessageLog
from app.db.models.respondent import Respondent

logger = logging.getLogger("app.services.webhook")

# Delivery status progression hierarchy (higher number = further in lifecycle)
STATUS_HIERARCHY: Dict[str, int] = {
    "Accepted": 1,
    "Sent": 2,
    "Delivered": 3,
    "Read": 4,
}

# Sensitive keys to sanitize in payloads
SENSITIVE_KEYS = {"access_token", "secret", "authorization", "auth", "token", "password"}


def mask_phone(phone: Optional[str]) -> str:
    """Mask phone number to protect customer privacy in application logs.
    
    Example: '+919876543210' -> '+91****10', '123' -> '***'
    """
    if not phone:
        return "***"
    phone_clean = str(phone).strip()
    if len(phone_clean) <= 5:
        return "***"
    return f"{phone_clean[:3]}****{phone_clean[-2:]}"


def sanitize_dict(data: Any) -> Any:
    """Recursively mask or redact sensitive keys from dictionaries before storing in raw_payload."""
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                sanitized[k] = sanitize_dict(v)
            elif any(sensitive in k.lower() for sensitive in SENSITIVE_KEYS):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(data, list):
        return [sanitize_dict(item) for item in data]
    return data


OPTOUT_KEYWORDS = {"STOP", "UNSUBSCRIBE", "OPT OUT", "OPTOUT", "NOT INTERESTED", "REMOVE", "CANCEL"}


def is_opt_out_reply(text: Optional[str]) -> bool:
    """Evaluate whether an inbound reply expresses opt-out intent."""
    if not text:
        return False
    upper = text.strip().upper()
    if upper in OPTOUT_KEYWORDS:
        return True
    cleaned = re.sub(r"[^\w\s]", " ", upper).strip()
    words = [w for w in cleaned.split() if w]
    if not words:
        return False
    phrase = " ".join(words)
    if phrase in OPTOUT_KEYWORDS:
        return True
    if words[0] in {"STOP", "UNSUBSCRIBE", "OPTOUT", "REMOVE", "CANCEL"}:
        return True
    if len(words) >= 2 and f"{words[0]} {words[1]}" in {"OPT OUT", "NOT INTERESTED"}:
        return True
    return False


class WebhookService:
    """Service handling Meta WhatsApp Cloud API webhooks."""

    @staticmethod
    def verify_hub_challenge(
        mode: Optional[str],
        token: Optional[str],
        challenge: Optional[str],
    ) -> Optional[str]:
        """Verify the Webhook challenge issued by Meta during endpoint setup.
        
        Args:
            mode: hub.mode parameter (must be 'subscribe')
            token: hub.verify_token parameter (must match WHATSAPP_WEBHOOK_VERIFY_TOKEN)
            challenge: hub.challenge parameter (returned verbatim if valid)
            
        Returns:
            challenge string if valid, None if invalid.
        """
        settings = get_settings()
        configured_token = settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN.strip()

        if not configured_token:
            logger.error("WHATSAPP_WEBHOOK_VERIFY_TOKEN is not configured in settings")
            return None

        if mode == "subscribe" and token == configured_token and challenge:
            logger.info("WhatsApp webhook challenge verification succeeded")
            return challenge

        logger.warning(
            "WhatsApp webhook verification failed. mode=%s, token_match=%s",
            mode,
            token == configured_token if token else False,
        )
        return None

    @staticmethod
    def verify_hub_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
        """Validate Meta X-Hub-Signature-256 HMAC-SHA256 signature against request body bytes.
        
        Args:
            raw_body: Exact raw request payload bytes.
            signature_header: Contents of X-Hub-Signature-256 header (e.g. 'sha256=abcdef...')
            
        Returns:
            True if signature matches, False otherwise.
        """
        settings = get_settings()
        secret = settings.META_APP_SECRET.strip()

        if not secret:
            logger.error("META_APP_SECRET is not configured; cannot verify signature")
            return False

        if not signature_header or not signature_header.startswith("sha256="):
            logger.warning("Missing or malformed X-Hub-Signature-256 header")
            return False

        expected_sig = hmac.new(
            key=secret.encode("utf-8"),
            msg=raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        provided_sig = signature_header[7:].strip()

        is_valid = hmac.compare_digest(expected_sig, provided_sig)
        if not is_valid:
            logger.warning("Webhook HMAC signature mismatch")
        return is_valid

    @staticmethod
    def update_delivery_status(db: Session, status_data: Dict[str, Any]) -> Optional[MessageLog]:
        """Process a WhatsApp delivery status event ('sent', 'delivered', 'read', 'failed').
        
        Enforces:
        - Explicit transition rules: Failed must NOT overwrite Delivered or Read.
        - Preservation of historical sent_at timestamp.
        - Out-of-order event protection: Lower status rank does not regress higher rank.
        - Idempotent execution.
        """
        wa_id = status_data.get("id")
        if not wa_id:
            logger.warning("Status event missing message ID: %s", status_data)
            return None

        log_entry = db.execute(
            select(MessageLog).where(MessageLog.whatsapp_message_id == wa_id)
        ).scalar_one_or_none()

        if not log_entry:
            logger.warning("Delivery status received for unknown WhatsApp message ID: %s", wa_id)
            return None

        # Parse event timestamp
        raw_ts = status_data.get("timestamp")
        try:
            event_dt = (
                datetime.fromtimestamp(int(raw_ts), tz=timezone.utc)
                if raw_ts
                else datetime.now(timezone.utc)
            )
        except (ValueError, TypeError):
            event_dt = datetime.now(timezone.utc)

        raw_status = (status_data.get("status") or "").lower().strip()
        current_status = log_entry.delivery_status
        current_rank = STATUS_HIERARCHY.get(current_status, 0)

        if raw_status == "sent":
            # Preserve existing sent_at timestamp (set during dispatch)
            if log_entry.sent_at is None:
                log_entry.sent_at = event_dt

            # Only advance to Sent if currently below Sent and not failed
            if current_rank < 2 and current_status != "Failed":
                log_entry.delivery_status = "Sent"

        elif raw_status == "delivered":
            if log_entry.delivered_at is None:
                log_entry.delivered_at = event_dt

            # Advance to Delivered if currently below Delivered
            if current_rank < 3:
                log_entry.delivery_status = "Delivered"

        elif raw_status == "read":
            if log_entry.read_at is None:
                log_entry.read_at = event_dt
            if log_entry.delivered_at is None:
                log_entry.delivered_at = event_dt

            # Advance to Read
            if current_rank < 4:
                log_entry.delivery_status = "Read"

        elif raw_status == "failed":
            # Record failed_at timestamp
            if log_entry.failed_at is None:
                log_entry.failed_at = event_dt

            # Parse error details
            errors = status_data.get("errors") or []
            err_parts = []
            for err in errors:
                code = err.get("code")
                title = err.get("title") or err.get("message")
                details = err.get("error_data", {}).get("details")
                part = f"[{code}] {title}" if code else str(title)
                if details:
                    part += f": {details}"
                err_parts.append(part)

            if err_parts:
                log_entry.error_details = "; ".join(err_parts)
            elif not log_entry.error_details:
                log_entry.error_details = "Message delivery failed according to WhatsApp webhook."

            # Terminal state preservation: Never overwrite Delivered or Read with Failed
            if current_status in ("Delivered", "Read"):
                logger.info(
                    "Preserving terminal delivery status '%s' for wa_id=%s despite late failure event",
                    current_status,
                    wa_id,
                )
            else:
                log_entry.delivery_status = "Failed"

        else:
            logger.warning("Unrecognized delivery status '%s' for wa_id=%s", raw_status, wa_id)

        return log_entry

    @staticmethod
    def extract_message_text(message_data: Dict[str, Any], msg_type: str) -> str:
        """Safely extract readable text from various WhatsApp message types without KeyError."""
        if msg_type == "text":
            return (message_data.get("text", {}) or {}).get("body", "").strip()

        elif msg_type == "button":
            btn = message_data.get("button", {}) or {}
            return (btn.get("text") or btn.get("payload") or "").strip() or "[Received button message]"

        elif msg_type == "interactive":
            inter = message_data.get("interactive", {}) or {}
            itype = inter.get("type", "")
            if itype == "button_reply":
                reply = inter.get("button_reply", {}) or {}
                return (reply.get("title") or reply.get("id") or "").strip() or "[Received button reply]"
            elif itype == "list_reply":
                reply = inter.get("list_reply", {}) or {}
                return (reply.get("title") or reply.get("id") or "").strip() or "[Received list reply]"
            return f"[Received interactive message]"

        elif msg_type in ("image", "video", "audio", "voice", "document", "location", "contacts", "sticker"):
            caption = ""
            if msg_type in ("image", "video", "document"):
                media_obj = message_data.get(msg_type, {}) or {}
                caption = media_obj.get("caption", "").strip()
            if caption:
                return f"[Received {msg_type} message] {caption}"
            return f"[Received {msg_type} message]"

        return f"[Received {msg_type} message]"

    @staticmethod
    def find_lead_by_phone(db: Session, sender_phone: str) -> Optional[Lead]:
        """Match incoming phone against leads handling 10-digit, 91-prefixed, and +-prefixed variations."""
        if not sender_phone:
            return None
        raw = str(sender_phone).strip()
        digits = re.sub(r"\D", "", raw)
        if not digits:
            return None

        candidates = {raw, digits, f"+{digits}"}
        if digits.startswith("91") and len(digits) == 12:
            local_10 = digits[2:]
            candidates.update({local_10, f"+91{local_10}", f"91{local_10}", f"+{local_10}"})
        elif len(digits) == 10:
            candidates.update({f"+91{digits}", f"91{digits}", f"+{digits}"})

        lead = db.execute(
            select(Lead).where(
                Lead.phone_number.in_(candidates),
                Lead.is_deleted == False,
            )
        ).scalars().first()
        if lead:
            return lead

        if len(digits) >= 10:
            last_10 = digits[-10:]
            lead = db.execute(
                select(Lead).where(
                    Lead.phone_number.like(f"%{last_10}"),
                    Lead.is_deleted == False,
                )
            ).scalars().first()
            if lead:
                return lead

        return None

    @staticmethod
    def process_incoming_message(
        db: Session,
        message_data: Dict[str, Any],
        profile_name: Optional[str] = None,
    ) -> Optional[IncomingMessage]:
        """Process an inbound customer WhatsApp message and maintain Respondent record.

        Enforces:
        - Unique whatsapp_message_id check (idempotency deduplication).
        - Normalized phone matching across country-code formats.
        - Every incoming sender is permanently recorded in the respondents table.
        - Existing respondent records are updated rather than creating duplicates.
        - Default classification is UNCLASSIFIED (NEVER automatically classified as Interested).
        - Message stored in IncomingMessage and MessageLog.
        - Opt-out intent detection enforces marketing consent revocation on Lead.
        - Privacy protection: phone masked in logs, sensitive data sanitized.
        """
        wa_id = message_data.get("id")
        if not wa_id:
            logger.warning("Incoming message missing 'id' field: %s", message_data)
            return None

        # 1. Idempotency check: Return existing message if already received
        existing_inc = db.execute(
            select(IncomingMessage).where(IncomingMessage.whatsapp_message_id == wa_id)
        ).scalar_one_or_none()
        if existing_inc:
            logger.info("Incoming message %s already recorded; skipping duplicate", wa_id)
            return existing_inc

        existing_log = db.execute(
            select(MessageLog).where(MessageLog.whatsapp_message_id == wa_id)
        ).scalar_one_or_none()
        if existing_log:
            logger.info("MessageLog %s already recorded; skipping duplicate", wa_id)
            return None

        sender_phone = str(message_data.get("from", "")).strip()
        msg_type = (message_data.get("type") or "text").lower().strip()
        message_text = WebhookService.extract_message_text(message_data, msg_type)

        # Parse timestamp
        raw_ts = message_data.get("timestamp")
        try:
            received_at = (
                datetime.fromtimestamp(int(raw_ts), tz=timezone.utc)
                if raw_ts
                else datetime.now(timezone.utc)
            )
        except (ValueError, TypeError):
            received_at = datetime.now(timezone.utc)

        # Normalize phone for consistent respondent storage (+<digits>)
        digits_only = re.sub(r"\D", "", sender_phone)
        canonical_phone = f"+{digits_only}" if digits_only else sender_phone

        # 2. Match lead by sender phone number (normalized)
        lead = WebhookService.find_lead_by_phone(db, sender_phone)
        lead_id: Optional[int] = lead.id if lead else None

        # 3. Identify original broadcast campaign if applicable
        original_campaign_id = None
        if lead:
            original_campaign_id = db.scalar(
                select(CampaignBatch.campaign_id)
                .join(CampaignRecipient, CampaignRecipient.batch_id == CampaignBatch.id)
                .where(CampaignRecipient.lead_id == lead.id)
                .order_by(CampaignRecipient.id.desc())
            )

        # 4. Create or update Respondent record (never duplicate)
        phone_candidates = {canonical_phone, sender_phone}
        if digits_only:
            phone_candidates.update({digits_only, f"+{digits_only}"})

        respondent = db.execute(
            select(Respondent).where(Respondent.phone_number.in_(phone_candidates))
        ).scalars().first()

        resolved_name = (
            profile_name
            or (lead.customer_name if lead and lead.customer_name else None)
        )

        if respondent:
            # Update existing respondent
            respondent.last_reply_at = received_at
            if not respondent.lead_id and lead_id:
                respondent.lead_id = lead_id
            if not respondent.original_campaign_id and original_campaign_id:
                respondent.original_campaign_id = original_campaign_id
            if resolved_name and not respondent.name:
                respondent.name = resolved_name
            respondent.updated_at = received_at
            logger.info("Updated existing respondent %d for %s", respondent.id, mask_phone(canonical_phone))
        else:
            # Create new permanent respondent with default classification UNCLASSIFIED
            # STRICT INSTRUCTION: Do NOT automatically classify as Interested
            respondent = Respondent(
                lead_id=lead_id,
                phone_number=canonical_phone,
                name=resolved_name,
                classification="UNCLASSIFIED",
                first_reply_at=received_at,
                last_reply_at=received_at,
                original_campaign_id=original_campaign_id,
                internal_notes=None,
            )
            db.add(respondent)
            logger.info("Created new UNCLASSIFIED respondent for %s", mask_phone(canonical_phone))

        # 5. Lead consent & status tracking
        if lead:
            if is_opt_out_reply(message_text):
                logger.info("Opt-out keyword received from lead %d (%s)", lead.id, mask_phone(sender_phone))
                lead.opt_in_status = "OPTED_OUT"
                lead.opt_out_timestamp = received_at
                lead.status = "Not Interested"
                lead.needs_manual_followup = False
                lead.last_reply_text = message_text
                lead.last_replied_at = received_at
                lead.follow_up_paused = True
                lead.updated_at = received_at
                # Cancel any legacy follow-up schedules if present
                try:
                    from app.db.models.followup import FollowUpSchedule
                    from sqlalchemy import update
                    db.execute(
                        update(FollowUpSchedule)
                        .where(FollowUpSchedule.lead_id == lead.id, FollowUpSchedule.status.in_(["Scheduled", "Approved"]))
                        .values(status="Cancelled")
                    )
                except Exception:
                    pass
            else:
                logger.info("Inbound reply recorded for lead %d (%s)", lead.id, mask_phone(sender_phone))
                lead.status = "Replied"
                lead.last_reply_text = message_text
                lead.last_replied_at = received_at
                lead.updated_at = received_at
        else:
            logger.info("Inbound WhatsApp message from non-lead contact %s recorded", mask_phone(sender_phone))

        # Log event with masked phone number
        logger.info(
            "Inbound WhatsApp message recorded: wa_id=%s, type=%s, sender=%s, matched_lead=%s",
            wa_id,
            msg_type,
            mask_phone(sender_phone),
            lead_id,
        )

        # Prepare sanitized raw payload
        sanitized_payload = sanitize_dict(message_data)
        raw_payload_str = json.dumps(sanitized_payload, ensure_ascii=False)

        incoming = IncomingMessage(
            lead_id=lead_id,
            whatsapp_message_id=wa_id,
            sender_phone=sender_phone,
            message_text=message_text,
            message_type=msg_type,
            received_at=received_at,
            processing_status="RECEIVED",
            raw_payload=raw_payload_str,
        )
        db.add(incoming)

        # Also record in MessageLog for unified message auditing
        inbound_log = MessageLog(
            lead_id=lead_id,
            message_type="inbound",
            template_name=None,
            whatsapp_message_id=wa_id,
            delivery_status="Received",
            api_status="RECEIVED",
            error_details=f"Inbound reply: {message_text[:200]}" if message_text else "Inbound WhatsApp message",
            sent_at=received_at,
            delivered_at=received_at,
            read_at=received_at,
            created_at=received_at,
        )
        db.add(inbound_log)

        return incoming

    @staticmethod
    def process_webhook_payload(db: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process complete WhatsApp Cloud API webhook event payload containing entries, changes, statuses, and messages."""
        processed_statuses = 0
        processed_messages = 0

        entries = payload.get("entry", [])
        if not isinstance(entries, list):
            return {
                "status": "ok",
                "processed_messages": 0,
                "processed_statuses": 0,
            }

        for entry in entries:
            changes = entry.get("changes", [])
            if not isinstance(changes, list):
                continue

            for change in changes:
                value = change.get("value", {})
                if not isinstance(value, dict):
                    continue

                # Extract contact profile names if present in payload
                contacts_list = value.get("contacts", [])
                profile_map: Dict[str, str] = {}
                if isinstance(contacts_list, list):
                    for c in contacts_list:
                        if isinstance(c, dict):
                            wa_id = str(c.get("wa_id") or "").strip()
                            name = (c.get("profile", {}) or {}).get("name")
                            if wa_id and name:
                                profile_map[wa_id] = name
                                digits = re.sub(r"\D", "", wa_id)
                                if digits:
                                    profile_map[digits] = name

                # Process delivery status events (DO NOT touch Respondents)
                statuses = value.get("statuses", [])
                if isinstance(statuses, list):
                    for st in statuses:
                        if isinstance(st, dict):
                            res = WebhookService.update_delivery_status(db, st)
                            if res:
                                processed_statuses += 1

                # Process incoming messages
                messages = value.get("messages", [])
                if isinstance(messages, list):
                    for msg in messages:
                        if isinstance(msg, dict):
                            sender = str(msg.get("from") or "").strip()
                            sender_digits = re.sub(r"\D", "", sender)
                            p_name = profile_map.get(sender) or profile_map.get(sender_digits)
                            res = WebhookService.process_incoming_message(db, msg, profile_name=p_name)
                            if res:
                                processed_messages += 1

        db.commit()
        return {
            "status": "ok",
            "processed_messages": processed_messages,
            "processed_statuses": processed_statuses,
        }
